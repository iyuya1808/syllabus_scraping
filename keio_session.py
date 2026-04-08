"""
GX10 上で Chromium を1回だけ起動し、閉じずにシラバスを連続取得する。

- auth.json を読み込んだ BrowserContext を使い続ける
- 別スレッドで定期的に pub-syllabus トップへアクセスし、セッションを温存（間隔は任意）
- 取得処理とキープアライブは同一 Page を共有するため threading.Lock で直列化

初回ログイン:
  手元 PC で gen_auth.py → auth.json を GX10 に置く（サーバー上で MFA ログインは想定しない）。

セッション切れ:
  手元で gen_auth を再実行し auth.json を上書きアップロード後、
  session.reload_auth_from_disk() するか、fetch_detail_html(..., auto_reload_auth=True) で1回だけ再試行。

使用例:

    from pathlib import Path
    from keio_session import KeioAuthExpiredError, KeioSyllabusSession

    with KeioSyllabusSession(
        auth_path=Path("auth.json"),
        keepalive_interval_sec=300,
    ) as session:
        for entno in ["00010", "00011"]:
            try:
                html = session.fetch_detail_html(2026, entno, auto_reload_auth=True)
            except KeioAuthExpiredError as e:
                ...  # 通知して停止など
"""

from __future__ import annotations

import argparse
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error, sync_playwright

from test_login import _stable_content

DEFAULT_AUTH = Path(__file__).resolve().parent / "auth.json"
KEEPALIVE_URL = "https://gslbs.keio.jp/pub-syllabus/"

# 詳細ページに「科目あり」のとき、セル内の「ログインすると表示されます」は除外したい
_LOGIN_WALL_MARKERS = (
    "ログインしてください",
    "再度ログイン",
    "セッションが無効",
    "セッションの有効期限",
    "Session Expired",
    "This session has expired",
    "Shibboleth",
    "慶應義塾大学ログイン",
)


class KeioAuthExpiredError(RuntimeError):
    """auth.json の期限切れや IdP へのリダイレクトなど。手元で gen_auth して差し替え。"""


def looks_like_login_wall_html(html: str) -> bool:
    """シラバス詳細のプレースホルダ（ログインすると表示…）はセッション切れとみなさない。"""
    return any(m in html for m in _LOGIN_WALL_MARKERS)


class KeioSyllabusSession:
    def __init__(
        self,
        auth_path: Path | None = None,
        *,
        headless: bool = True,
        keepalive_interval_sec: float = 0,
        keepalive_url: str = KEEPALIVE_URL,
        flush_storage_on_keepalive: bool = False,
    ) -> None:
        """
        keepalive_interval_sec > 0 のとき、バックグラウンドで定期的に keepalive_url を開く。
        flush_storage_on_keepalive が True なら、キープアライブ後に auth.json を上書き保存する。
        """
        self.auth_path = Path(auth_path) if auth_path else DEFAULT_AUTH
        self.headless = headless
        self.keepalive_interval_sec = keepalive_interval_sec
        self.keepalive_url = keepalive_url
        self.flush_storage_on_keepalive = flush_storage_on_keepalive

        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        if not self.auth_path.is_file():
            raise FileNotFoundError(f"auth.json がありません: {self.auth_path}")

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            storage_state=str(self.auth_path),
        )
        self._page = self._context.new_page()

        if self.keepalive_interval_sec > 0:
            self._worker = threading.Thread(
                target=self._keepalive_loop, name="keio-keepalive", daemon=True
            )
            self._worker.start()

    def _raise_if_login_wall(self, html: str) -> None:
        assert self._page is not None
        loc = (urlparse(self._page.url).hostname or "").lower()
        if loc and "gslbs.keio.jp" not in loc:
            raise KeioAuthExpiredError(
                f"gslbs 以外に遷移しています（{self._page.url}）。"
                "セッション切れの可能性。手元で gen_auth して auth.json を差し替えてください。"
            )
        if looks_like_login_wall_html(html):
            raise KeioAuthExpiredError(
                "ログイン案内・セッション無効ページに見えます。"
                "手元で gen_auth を再実行し auth.json をアップロード後、"
                "reload_auth_from_disk() またはプロセス再起動してください。"
            )

    def _load_url_stable(self, url: str, timeout_ms: int = 60_000) -> str:
        assert self._page is not None
        self._page.goto(url, wait_until="load", timeout=timeout_ms)
        try:
            self._page.wait_for_load_state("networkidle", timeout=20_000)
        except Error:
            pass
        return _stable_content(self._page)

    def reload_auth_from_disk(self) -> None:
        """ディスク上の auth.json で BrowserContext を作り直す（ブラウザは開いたまま）。"""
        with self._lock:
            if self._browser is None:
                raise RuntimeError("ブラウザが起動していません。start() 後に呼び出してください。")
            if not self.auth_path.is_file():
                raise FileNotFoundError(f"auth.json がありません: {self.auth_path}")
            if self._context is not None:
                self._context.close()
            self._context = self._browser.new_context(
                storage_state=str(self.auth_path),
            )
            self._page = self._context.new_page()

    def _keepalive_loop(self) -> None:
        while not self._stop.wait(timeout=self.keepalive_interval_sec):
            try:
                self.keepalive()
            except KeioAuthExpiredError as e:
                print(f"[keepalive] 認証切れ: {e}")
            except Exception as e:
                print(f"[keepalive] 失敗: {e}")

    def keepalive(self) -> None:
        with self._lock:
            html = self._load_url_stable(self.keepalive_url)
            self._raise_if_login_wall(html)
            if self.flush_storage_on_keepalive:
                self._context.storage_state(path=str(self.auth_path))

    def fetch_detail_html(
        self,
        year: int,
        entno: str,
        *,
        lang: str = "jp",
        timeout_ms: int = 60_000,
        auto_reload_auth: bool = False,
    ) -> str:
        ent = str(entno).zfill(5)
        url = (
            "https://gslbs.keio.jp/pub-syllabus/detail?"
            f"ttblyr={year}&entno={ent}&lang={lang}"
        )

        def once() -> str:
            with self._lock:
                html = self._load_url_stable(url, timeout_ms=timeout_ms)
                self._raise_if_login_wall(html)
                return html

        try:
            return once()
        except KeioAuthExpiredError:
            if not auto_reload_auth:
                raise
            self.reload_auth_from_disk()
            return once()

    def save_storage_state(self) -> None:
        with self._lock:
            self._context.storage_state(path=str(self.auth_path))

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=self.keepalive_interval_sec + 2)
            self._worker = None

        if self._context is not None:
            try:
                with self._lock:
                    self._context.storage_state(path=str(self.auth_path))
            except Exception:
                pass

        if self._browser is not None:
            self._browser.close()
            self._browser = None
            self._context = None
            self._page = None

        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    def __enter__(self) -> KeioSyllabusSession:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()


def _demo_main() -> None:
    parser = argparse.ArgumentParser(description="長寿命セッションのデモ取得")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument(
        "--entnos",
        default="00010,00012",
        help="カンマ区切り entno",
    )
    parser.add_argument(
        "--keepalive-sec",
        type=float,
        default=300,
        help="0 ならバックグラウンドキープアライブなし（取得のたびに URL を開くだけ）",
    )
    parser.add_argument(
        "--flush-auth",
        action="store_true",
        help="キープアライブのたびに auth.json を上書き保存する",
    )
    args = parser.parse_args()
    entnos = [e.strip().zfill(5) for e in args.entnos.split(",") if e.strip()]

    print(
        f"起動: keepalive 間隔 {args.keepalive_sec} 秒、"
        f"entnos={entnos}（Ctrl+C で終了・終了時に auth を保存）"
    )
    with KeioSyllabusSession(
        keepalive_interval_sec=args.keepalive_sec,
        flush_storage_on_keepalive=args.flush_auth,
    ) as session:
        for ent in entnos:
            t0 = time.perf_counter()
            html = session.fetch_detail_html(args.year, ent)
            dt = time.perf_counter() - t0
            title_m = re.search(r"<h2[^>]*>(.*?)</h2>", html, re.DOTALL)
            title = title_m.group(1)[:80] if title_m else "?"
            print(f"  {ent}: {len(html)} bytes, {dt:.2f}s, h2≈{title!r}")
        if args.keepalive_sec <= 0:
            print("ヒント: 長時間ジョブでは --keepalive-sec 300 などで定期アクセスを有効にできます。")
        else:
            print(f"キープアライブは {args.keepalive_sec} 秒ごとにバックグラウンド実行中。数分待って Ctrl+C…")
            try:
                while True:
                    time.sleep(30)
            except KeyboardInterrupt:
                print("\n終了します。")


if __name__ == "__main__":
    _demo_main()
