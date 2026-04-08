import argparse
from playwright.sync_api import sync_playwright
import re

def strip_(html: str) -> str:
    if not html: return ""
    return re.sub(r"<[^>]+>", "", html).replace("&nbsp;", " ").strip()

def check_auth_content(cdp_url, year, entno):
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]
        page = context.new_page()
        
        url = f"https://gslbs.keio.jp/pub-syllabus/detail?ttblyr={year}&entno={entno}&lang=jp"
        page.goto(url, wait_until="networkidle")
        
        html = page.content()
        
        # ログイン文言が残っているかチェック
        login_markers = ["ログインすると表示されます", "慶應ID", "Login to view"]
        found_markers = [m for m in login_markers if m in html]
        
        print(f"--- Result for {entno} ---")
        if found_markers:
            print(f"Warning: Still found login placeholders: {found_markers}")
        else:
            print("Success: No login placeholders found!")
            
        # 特定のフィールドを抽出してみる
        # 例：ページ全体のテキストから「場所」や「評語」などを探す
        text = page.inner_text("body")
        for key in ["教室", "場所", "評語", "コメント", "質問"]:
            if key in text:
                print(f"Found keyword '{key}'")
                # 周辺のテキストを表示
                m = re.search(f"{key}.{{1,50}}", text)
                if m:
                    print(f"  Preview: {m.group(0)}")

        page.close()
        browser.close()

if __name__ == "__main__":
    check_auth_content("http://127.0.0.1:9222", 2026, "00010")
