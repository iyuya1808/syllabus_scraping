import argparse
import json
import os
import re
import time
from pathlib import Path
from playwright.sync_api import Error, sync_playwright

def _stable_content(page, attempts: int = 10, delay_ms: int = 400) -> str:
    """リダイレクトやクライアント遷移中の Page.content 失敗を避ける。"""
    last_error: Error | None = None
    for _ in range(attempts):
        try:
            return page.content()
        except Error as e:
            last_error = e
            if "navigating" in str(e).lower() or "connected" in str(e).lower():
                page.wait_for_timeout(delay_ms)
            else:
                raise
    if last_error:
        raise last_error
    return ""

def strip_(html: str) -> str:
    if not html: return ""
    t = re.sub(r"<[^>]+>", "", html)
    t = t.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", t).strip()

def parse_detail_content(page):
    """HTML をパースして JSON 構造に変換する"""
    data = {"title": "", "table": {}, "sections": {}}
    
    title_node = page.query_selector("h2")
    data["title"] = strip_(title_node.inner_html()) if title_node else ""
    
    # テーブル項目の抽出
    rows = page.query_selector_all("table tr")
    for row in rows:
        th = row.query_selector("th")
        td = row.query_selector("td")
        if th and td:
            key = strip_(th.inner_html())
            val = strip_(td.inner_html())
            if key:
                data["table"][key] = val
    
    # セクション (h3) の抽出
    sections = page.query_selector_all("h3")
    for sec in sections:
        sec_title = strip_(sec.inner_html()).replace("[説明]", "").strip()
        content_node = page.evaluate_handle("node => node.nextElementSibling", sec)
        if content_node:
            val = strip_(page.evaluate("node => node.innerHTML", content_node))
            if sec_title:
                data["sections"][sec_title] = val
                
    return data

class MegaScraper:
    def __init__(self, year, output_file, progress_file, cdp_url=None, auth_file=None, headless=False):
        self.year = year
        self.output_file = Path(output_file)
        self.progress_file = Path(progress_file)
        self.cdp_url = cdp_url
        self.auth_file = Path(auth_file) if auth_file else None
        self.headless = headless
        self.progress = self._load_progress()

    def _load_progress(self):
        if self.progress_file.exists():
            with open(self.progress_file, "r") as f:
                return json.load(f)
        return {"next_entno": 1}

    def _save_progress(self):
        with open(self.progress_file, "w") as f:
            json.dump(self.progress, f)

    def run(self, batch_size=1000):
        start_entno = self.progress["next_entno"]
        print(f"Starting mega scrape from entno: {start_entno} (Year: {self.year}, Headless: {self.headless})")
        
        with sync_playwright() as p:
            try:
                # 接続 or 起動の選択
                if self.cdp_url and not self.headless:
                    print(f"Connecting to existing Chrome via CDP: {self.cdp_url}")
                    browser = p.chromium.connect_over_cdp(self.cdp_url)
                    context = browser.contexts[0]
                else:
                    print(f"Launching new browser (Headless: {self.headless}, Auth: {self.auth_file})")
                    browser = p.chromium.launch(headless=self.headless)
                    storage_state = str(self.auth_file) if self.auth_file and self.auth_file.exists() else None
                    context = browser.new_context(storage_state=storage_state)

                count = 0
                current_entno = start_entno
                
                while count < batch_size:
                    ent = str(current_entno).zfill(5)
                    url = f"https://gslbs.keio.jp/syllabus/detail?ttblyr={self.year}&entno={ent}&lang=jp"
                    
                    page = context.new_page()
                    try:
                        print(f"[{ent}] Fetching ({count+1}/{batch_size})...", end="\r")
                        page.goto(url, wait_until="load", timeout=60000)
                        
                        # ページが存在するかチェック
                        content = _stable_content(page)
                        if "指定した科目のシラバスは存在しません" in content:
                            pass
                        elif len(content) < 1000:
                            print(f"\n[{ent}] Warning: Content too short.")
                        else:
                            item_data = parse_detail_content(page)
                            if item_data["title"]:
                                result = {
                                    "entno": ent,
                                    "year": self.year,
                                    "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                    **item_data
                                }
                                with open(self.output_file, "a", encoding="utf-8") as f:
                                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
                            else:
                                print(f"\n[{ent}] Warning: Title not found.")

                    except Exception as e:
                        print(f"\n[{ent}] Error: {e}")
                    finally:
                        page.close()
                    
                    current_entno += 1
                    count += 1
                    self.progress["next_entno"] = current_entno
                    
                    if count % 10 == 0:
                        self._save_progress()
                        
                    time.sleep(0.5)
                
                self._save_progress()
                print(f"\nBatch completed. Next starting ID will be: {current_entno}")
                browser.close()
                
            except Exception as e:
                print(f"\nExecution error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=1000, help="1回の実行で取得する件数")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--out", default="syllabus_2026.jsonl")
    parser.add_argument("--prog", default="progress_local.json")
    parser.add_argument("--auth", default="auth.json", help="認証状態を保存したファイル (save_auth.py で作成)")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    parser.add_argument("--headless", action="store_true", help="ブラウザ画面を表示せずにバックグラウンドで実行する")
    args = parser.parse_args()
    
    # ヘッドレスでない場合は CDP を優先し、ヘッドレスの場合は新規起動（auth.jsonを使用）
    scraper = MegaScraper(args.year, args.out, args.prog, 
                          cdp_url=args.cdp_url if not args.headless else None,
                          auth_file=args.auth,
                          headless=args.headless)
    scraper.run(batch_size=args.batch)
