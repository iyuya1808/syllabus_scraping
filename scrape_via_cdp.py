"""
手元の Google Chrome（GX10 上）を閉じずに、そのセッションでシラバスを取得する。

前提:
  - GX10 で **GUI が使える**（デスクトップ、VNC、X11 転送など）。DISPLAY が空だと Chrome が起動しない。
  - Chrome を **リモートデバッグ付き**で起動し、そこで一度だけ手動ログインする。
  - **Chrome のウィンドウは閉じない**（閉じるとセッションが消える）。

1) Chrome 起動例（別ターミナル・バックグラウンド）:

     google-chrome --remote-debugging-port=9222 \\
       --user-data-dir=\"$HOME/.chrome-keio-debug\" &

   無い場合は `google-chrome-stable` や `chromium` を試す。

2) 開いた Chrome で https://gslbs.keio.jp/pub-syllabus/ にログインまで完了。

3) スクレイピング（同じマシン上）:

     cd syllabus_scraping
     ../venv/bin/python scrape_via_cdp.py --cdp-url http://127.0.0.1:9222 --entnos 00010,00012

   Playwright は CDP で接続するだけなので、**Chrome 本体は終了させません**。
"""

from __future__ import annotations

import argparse
import re
import time
from playwright.sync_api import Error, sync_playwright

from test_login import _stable_content

DEFAULT_CDP = "http://127.0.0.1:9222"


class KeioChromeCdpSession:
    """既存の Chrome に connect_over_cdp で接続し、新しいタブで URL を開く。"""

    def __init__(self, cdp_url: str = DEFAULT_CDP) -> None:
        self.cdp_url = cdp_url.rstrip("/")
        self._pw = None
        self._browser = None

    def connect(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
        if not self._browser.contexts:
            raise RuntimeError(
                "接続できましたが BrowserContext がありません。"
                "Chrome を --remote-debugging-port 付きで起動し直してください。"
            )

    def disconnect(self) -> None:
        """WebSocket を切るだけ。リモートの Chrome プロセスは止めない。"""
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    def _default_context(self):
        assert self._browser is not None
        return self._browser.contexts[0]

    def _goto_detail_stable(
        self, page, year: int, entno: str, *, lang: str = "jp", timeout_ms: int = 120_000
    ) -> str:
        ent = str(entno).zfill(5)
        url = (
            "https://gslbs.keio.jp/pub-syllabus/detail?"
            f"ttblyr={year}&entno={ent}&lang={lang}"
        )
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Error:
            pass
        return _stable_content(page)

    def fetch_detail_html(
        self, year: int, entno: str, *, lang: str = "jp", timeout_ms: int = 120_000
    ) -> str:
        """ログイン済みコンテキストと同じ Cookie を共有する新規タブで取得する。"""
        ctx = self._default_context()
        page = ctx.new_page()
        try:
            return self._goto_detail_stable(page, year, entno, lang=lang, timeout_ms=timeout_ms)
        finally:
            page.close()

    def __enter__(self) -> KeioChromeCdpSession:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()


def _main() -> None:
    parser = argparse.ArgumentParser(description="CDP 接続でシラバス詳細 HTML を取得")
    parser.add_argument("--cdp-url", default=DEFAULT_CDP, help="例: http://127.0.0.1:9222")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--entnos", default="00010", help="カンマ区切り")
    args = parser.parse_args()
    entnos = [e.strip().zfill(5) for e in args.entnos.split(",") if e.strip()]

    with KeioChromeCdpSession(args.cdp_url) as session:
        for ent in entnos:
            t0 = time.perf_counter()
            html = session.fetch_detail_html(args.year, ent)
            dt = time.perf_counter() - t0
            m = re.search(r"<h2[^>]*>(.*?)</h2>", html, re.DOTALL)
            h2 = (m.group(1)[:60] + "…") if m else "?"
            print(f"{ent}: {len(html)} bytes, {dt:.2f}s, h2≈{h2!r}")


if __name__ == "__main__":
    _main()
