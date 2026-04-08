"""
GAS（parseDetailHtml_）相当の見取りで、ログイン時に「全項目」が取れるか検証する。

- ゲスト（storage_state なし）と認証（auth.json）の HTML をそれぞれ取得
- 表・h3 セクションの各行について、値に「ログイン」が含まれるか等を列挙
- GAS と同じ省略ルールで取り込んだキー集合も併記（!value.includes("ログイン") の行は捨てる）

使い方（syllabus_scraping ディレクトリで）:
  ../venv/bin/python verify_login_fields.py
  ../venv/bin/python verify_login_fields.py --year 2026 --entno 00010
  ../venv/bin/python verify_login_fields.py --entnos 00010,00012,00015
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Error, sync_playwright

from test_login import _stable_content

AUTH_JSON = Path(__file__).resolve().parent / "auth.json"


def strip_(html: str) -> str:
    if not html:
        return ""
    t = re.sub(r"<[^>]+>", "", html)
    t = t.replace("&nbsp;", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


@dataclass
class TableRowDiag:
    key: str
    value: str
    has_login: bool


@dataclass
class SectionDiag:
    title: str
    content: str
    has_login: bool


def parse_title_gas(html: str) -> str:
    m = re.search(r"<h2[^>]*>(.*?)</h2>", html, re.DOTALL)
    if m:
        t = strip_(m.group(1))
        if t:
            return t
    m = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    return strip_(m.group(1)) if m else ""


def diagnostic_table_rows(html: str) -> list[TableRowDiag]:
    out: list[TableRowDiag] = []
    m = re.search(r"<table[\s\S]*?</table>", html)
    if not m:
        return out
    block = m.group(0)
    for row in re.findall(r"<tr[\s\S]*?</tr>", block):
        th = re.search(r"<th[^>]*>(.*?)</th>", row, re.DOTALL)
        td = re.search(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if not th or not td:
            continue
        key = strip_(th.group(1))
        value = strip_(td.group(1))
        out.append(
            TableRowDiag(key=key, value=value, has_login="ログイン" in value)
        )
    return out


def diagnostic_sections(html: str) -> list[SectionDiag]:
    """GAS: 各 h3 の直後に最初の <div>...</div> を本文とみなす。"""
    out: list[SectionDiag] = []
    for m in re.finditer(r"<h3[^>]*>(.*?)</h3>", html, re.DOTALL):
        title = strip_(m.group(1)).replace("[説明]", "").strip()
        after = html[m.end() :]
        div = re.search(r"<div[^>]*>([\s\S]*?)</div>", after)
        if not div:
            continue
        content = strip_(div.group(1))
        out.append(
            SectionDiag(title=title, content=content, has_login="ログイン" in content)
        )
    return out


def gas_like_dicts(
    title: str, rows: list[TableRowDiag], sections: list[SectionDiag]
) -> tuple[dict[str, str], dict[str, str]]:
    """GAS と同じ「ログインを含む値は捨てる」後の table / sections。"""
    table = {r.key: r.value for r in rows if r.key and not r.has_login}
    sect = {s.title: s.content for s in sections if s.title and not s.has_login}
    return table, sect


def fetch_html(
    browser, storage_state: Path | None, url: str, timeout_ms: int = 60_000
) -> tuple[str, list[dict]]:
    ctx = browser.new_context(
        storage_state=str(storage_state) if storage_state else None
    )
    try:
        page = ctx.new_page()
        page.goto(url, wait_until="load", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Error:
            pass
        html = _stable_content(page)
        cookies = ctx.cookies()
        return html, cookies
    finally:
        ctx.close()


def format_cookie_diag(cookies: list[dict]) -> str:
    """storage_state が効いているかの目安（keio 系ドメインの Cookie 数）。"""
    if not cookies:
        return "Cookie: 0 件（このコンテキストに保存された Cookie はありません）"
    keio = [c for c in cookies if "keio" in (c.get("domain") or "").lower()]
    names = sorted({c["name"] for c in keio})
    preview = ", ".join(names[:12])
    if len(names) > 12:
        preview += ", …"
    return (
        f"Cookie 合計 {len(cookies)} 件 / keio 系ドメイン {len(keio)} 件"
        f"（例: {preview or '—'}）"
    )


def summarize(label: str, html: str, cookies: list[dict] | None = None) -> None:
    print(f"\n=== {label} ===")
    if cookies is not None:
        print(format_cookie_diag(cookies))

    if "指定した科目のシラバスは存在しません" in html:
        print("科目なしメッセージが含まれます。")
        return
    if len(html) < 1000:
        print(f"HTML が短すぎます（{len(html)} 文字）。GAS では [EMPTY HTML] 相当。")

    title = parse_title_gas(html)
    rows = diagnostic_table_rows(html)
    secs = diagnostic_sections(html)
    gas_table, gas_sections = gas_like_dicts(title, rows, secs)

    login_rows = [r for r in rows if r.has_login]
    login_secs = [s for s in secs if s.has_login]

    print(f"title (GAS 相当): {title!r}")
    print(f"表: 全 {len(rows)} 行 / ログイン文字列を含む値: {len(login_rows)} 行")
    print(f"h3 セクション: 全 {len(secs)} / ログイン文字列を含む本文: {len(login_secs)}")
    print(f"GAS 取り込み後 — table キー数: {len(gas_table)}, sections キー数: {len(gas_sections)}")

    if login_rows:
        print("  [表] ログインを含む行（未ログインだと GAS では列自体が消える）:")
        for r in login_rows:
            preview = (r.value[:120] + "…") if len(r.value) > 120 else r.value
            print(f"    - {r.key!r}: {preview!r}")

    if login_secs:
        print("  [セクション] ログインを含む本文（GAS では当該セクションごと捨て）:")
        for s in login_secs:
            preview = (s.content[:120] + "…") if len(s.content) > 120 else s.content
            print(f"    - {s.title!r}: {preview!r}")


def compare_keys(guest_html: str, auth_html: str) -> None:
    """認証でだけ埋まる・ゲストはログイン文言のキーを列挙。"""
    gr = diagnostic_table_rows(guest_html)
    ar = diagnostic_table_rows(auth_html)
    gs = diagnostic_sections(guest_html)
    as_ = diagnostic_sections(auth_html)

    g_tab = {r.key: r for r in gr}
    a_tab = {r.key: r for r in ar}
    g_sec = {s.title: s for s in gs}
    a_sec = {s.title: s for s in as_}

    print("\n=== 差分（表） ===")
    for k in sorted(a_tab.keys()):
        a = a_tab[k]
        g = g_tab.get(k)
        if g is None:
            print(
                f"  + {k!r}: ゲストでは行なし / 認証 "
                f"{'…ログイン含む' if a.has_login else '取得'}"
            )
            continue
        if g.has_login and not a.has_login:
            print(f"  ~ {k!r}: ゲストはログイン文言あり → 認証で本文取得")

    print("\n=== 差分（h3 セクション） ===")
    for t in sorted(a_sec.keys()):
        a = a_sec[t]
        g = g_sec.get(t)
        if g is None:
            print(f"  + {t!r}: ゲストではセクションなし")
            continue
        if g.has_login and not a.has_login:
            print(f"  ~ {t!r}: ゲストはログイン文言 → 認証で本文取得")


def _parse_entno_list(entnos: str | None, single: str) -> list[str]:
    if entnos:
        parts = [p.strip() for p in entnos.split(",")]
        return [p.zfill(5) for p in parts if p]
    return [single.zfill(5)]


def _run_one(
    browser,
    year: int,
    entno: str,
    guest_only: bool,
) -> None:
    url = (
        f"https://gslbs.keio.jp/pub-syllabus/detail?"
        f"ttblyr={year}&entno={entno}&lang=jp"
    )
    print(f"\n{'#' * 60}\nURL: {url}\n{'#' * 60}")

    guest_html, guest_cookies = fetch_html(browser, None, url)
    summarize("ゲスト（未ログイン）", guest_html, guest_cookies)

    if guest_only:
        return

    if not AUTH_JSON.is_file():
        raise SystemExit(f"auth.json がありません: {AUTH_JSON}")

    auth_html, auth_cookies = fetch_html(browser, AUTH_JSON, url)
    summarize("認証（auth.json）", auth_html, auth_cookies)

    n_guest_keio = sum(
        1 for c in guest_cookies if "keio" in (c.get("domain") or "").lower()
    )
    n_auth_keio = sum(
        1 for c in auth_cookies if "keio" in (c.get("domain") or "").lower()
    )
    if n_auth_keio <= n_guest_keio:
        print(
            "\n[Cookie ヒント] 認証コンテキストの keio 系 Cookie 件数がゲスト以下です。"
            "auth.json が空／期限切れ／別ドメインのみの可能性があります。"
        )

    compare_keys(guest_html, auth_html)

    ar = diagnostic_table_rows(auth_html)
    as_ = diagnostic_sections(auth_html)
    gr = diagnostic_table_rows(guest_html)
    gs = diagnostic_sections(guest_html)

    bad_auth = [r for r in ar if r.has_login] + [s for s in as_ if s.has_login]

    fp_auth = tuple((r.key, r.value) for r in ar if r.has_login) + tuple(
        (s.title, s.content) for s in as_ if s.has_login
    )
    fp_guest = tuple((r.key, r.value) for r in gr if r.has_login) + tuple(
        (s.title, s.content) for s in gs if s.has_login
    )

    print("\n=== 結論 ===")
    if not bad_auth:
        print(
            "このページでは、表・h3 セクションの値に「ログイン」は検出されませんでした。"
            "（他 entno でも確認するには --entnos を使ってください）"
        )
    elif fp_auth == fp_guest and fp_auth:
        if n_auth_keio > n_guest_keio:
            print(
                "ログイン用 Cookie（Shibboleth 等）は認証コンテキストに載っていますが、"
                "プレースホルダ文言はゲストと同一です。"
                "慶應IDでログインしていても「履修者のみ」「教員のみ」など別条件の項目で、"
                "サーバー側が本文を返さないパターンが考えられます。"
            )
        else:
            print(
                "ゲストと認証でプレースホルダが同一で、keio 系 Cookie も増えていません。"
                "auth.json の作り直し（pub-syllabus でログイン完了後に gen_auth）を試してください。"
            )
    else:
        print(
            "認証 HTML に「ログイン」を含む表セル／セクションが残っていますが、"
            "ゲストとは内容が異なります。権限や表示条件の差を確認してください。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="シラバス詳細のログイン項目検証")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--entno", type=str, default="00010")
    parser.add_argument(
        "--entnos",
        type=str,
        default="",
        help="カンマ区切りで複数 entno（例: 00010,00012）。指定時は --entno は無視。",
    )
    parser.add_argument(
        "--guest-only",
        action="store_true",
        help="ゲストのみ（auth.json 不要）",
    )
    args = parser.parse_args()
    entno_list = _parse_entno_list(args.entnos.strip() or None, args.entno)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for ent in entno_list:
                _run_one(browser, args.year, ent, args.guest_only)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
