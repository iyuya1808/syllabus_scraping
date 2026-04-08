import argparse
import re
from playwright.sync_api import sync_playwright

def strip_(html: str) -> str:
    if not html: return ""
    # タグと空白の除去
    t = re.sub(r"<[^>]+>", "", html)
    t = t.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", t).strip()

def peek(year, entno, cdp_url="http://127.0.0.1:9222"):
    ent = str(entno).zfill(5)
    # ポイント: ログイン済み用の /syllabus/ パスを使用
    url = f"https://gslbs.keio.jp/syllabus/detail?ttblyr={year}&entno={ent}&lang=jp"
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0]
            page = context.new_page()
            
            print(f"Fetching: {url} ...")
            page.goto(url, wait_until="networkidle")
            
            title_node = page.query_selector("h2")
            title = strip_(title_node.inner_html()) if title_node else "No Title"
            print(f"\n--- 【{ent}】 {title} ---")
            
            # テーブル項目の抽出
            rows = page.query_selector_all("table tr")
            for row in rows:
                th = row.query_selector("th")
                td = row.query_selector("td")
                if th and td:
                    key = strip_(th.inner_html())
                    val = strip_(td.inner_html())
                    # 認証が効いていれば「ログインすると表示」が含まれないはず
                    marker = " [★認証済データ]" if "ログイン" not in val else " [⚠️未認証]"
                    print(f"{key:15}: {val}{marker}")
            
            # セクション (h3) の抽出
            sections = page.query_selector_all("h3")
            for sec in sections:
                sec_title = strip_(sec.inner_html()).replace("[説明]", "").strip()
                # h3 の次の div を取得
                content_node = page.evaluate_handle("node => node.nextElementSibling", sec)
                if content_node:
                    val = strip_(page.evaluate("node => node.innerHTML", content_node))
                    if val:
                        marker = " [★認証済データ]" if "ログイン" not in val else " [⚠️未認証]"
                        preview = (val[:50] + "...") if len(val) > 50 else val
                        print(f"[{sec_title}] {preview}{marker}")

            page.close()
            browser.close()
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("entno", help="確認したい科目ID (例: 00010)")
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()
    
    peek(args.year, args.entno)
