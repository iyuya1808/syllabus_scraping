import json
from playwright.sync_api import sync_playwright

def save_auth(cdp_url="http://127.0.0.1:9222", output="auth.json"):
    with sync_playwright() as p:
        try:
            print(f"Connecting to Chrome via CDP: {cdp_url}")
            browser = p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0]
            
            # 認証状態（クッキー、ローカルストレージなど）を保存
            print(f"Saving storage state to {output}...")
            context.storage_state(path=output)
            
            print("Done! You can now close the visible Chrome window.")
            browser.close()
        except Exception as e:
            print(f"Failed to save auth: {e}")

if __name__ == "__main__":
    save_auth()
