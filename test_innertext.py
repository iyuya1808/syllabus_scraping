import asyncio
from playwright.sync_api import sync_playwright

html = """
<div class="contents"><div class="syllabus-plan-outer"><div class="syllabus-plan-heading">第1回</div><div class="syllabus-plan-content">イントロダクション（テキスト紹介、報告担当者決め）</div></div><div class="syllabus-plan-outer"><div class="syllabus-plan-heading">第2回</div><div class="syllabus-plan-content">講義（欧文研究書・学術論文［イスラーム史］の読み方）</div></div>
"""

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html)
        val_innerhtml = page.evaluate("document.querySelector('.contents').innerHTML")
        val_innertext = page.evaluate("document.querySelector('.contents').innerText")
        print("--- INNER HTML ---")
        print(val_innerhtml)
        print("--- INNER TEXT ---")
        print(val_innertext)
        print("--- REPR ---")
        print(repr(val_innertext))
        browser.close()

if __name__ == "__main__":
    main()
