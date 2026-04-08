"""auth.json がサーバー上の headless Chromium で有効か確認するテスト。"""

from playwright.sync_api import Error, sync_playwright


def _stable_content(page, attempts: int = 10, delay_ms: int = 400) -> str:
    """リダイレクトやクライアント遷移中の Page.content 失敗を避ける。"""
    last: Error | None = None
    for _ in range(attempts):
        try:
            return page.content()
        except Error as e:
            last = e
            if "navigating" in str(e).lower():
                page.wait_for_timeout(delay_ms)
            else:
                raise
    assert last is not None
    raise last


def test():
    with sync_playwright() as p:
        # サーバーなので headless=True
        browser = p.chromium.launch(headless=True)
        # 保存した認証情報を使用
        context = browser.new_context(storage_state="auth.json")
        page = context.new_page()

        # GAS と同じ pub-syllabus URL（/syllabus/ だと Cookie 適用が異なることがある）
        url = "https://gslbs.keio.jp/pub-syllabus/detail?ttblyr=2026&entno=00010&lang=jp"
        page.goto(url, wait_until="load", timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Error:
            pass

        # ログインしていないと「ログイン」という文字が並ぶはずなのでチェック
        content = _stable_content(page)
        if "指定した科目のシラバスは存在しません" in content:
            print("ページには到達しましたが、該当する科目シラバスが存在しないようです。")
        elif "ログインしてください" in content or "Login" in content:
            print("失敗：ログイン状態が反映されていません。auth.json を作り直してください。")
        else:
            print("成功：ログイン状態でページを取得できました！")
            # デバッグ用にタイトルなどを表示
            h2 = page.locator("h2")
            print("Title:", h2.inner_text() if h2.count() > 0 else "No Title")

        browser.close()


if __name__ == "__main__":
    test()
