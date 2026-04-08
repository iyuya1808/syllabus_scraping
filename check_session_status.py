import sys
from playwright.sync_api import sync_playwright

def check_login_status():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state="auth.json")
        page = context.new_page()
        
        # ログイン後のトップページ
        page.goto("https://gslbs.keio.jp/pub-syllabus/", wait_until="networkidle")
        
        content = page.content()
        
        print(f"URL: {page.url}")
        if "ログアウト" in content or "Logout" in content:
            print("Status: ログイン中です (Logout button found)")
        else:
            print("Status: ログインしていない、またはセッション切れです")
            
        # ユーザー名などが表示されているか確認
        # 実際の実装に合わせてセレクタを調整（ここではテキスト検索）
        if "様" in content:
            # 「〇〇 様」のような表示を探す
            import re
            m = re.search(r"(\S+)\s*様", content)
            if m:
                print(f"User: {m.group(0)}")

        browser.close()

if __name__ == "__main__":
    check_login_status()
