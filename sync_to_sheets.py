import argparse
import json
import re
import sys
import time
import requests
from playwright.sync_api import sync_playwright

def strip_(html: str) -> str:
    if not html: return ""
    t = re.sub(r"<[^>]+>", "", html)
    t = t.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", t).strip()

def parse_detail_content(page):
    """HTML をパースして GAS が期待する JSON 形式に変換する"""
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

def sync(gas_url, year, entnos, cdp_url="http://127.0.0.1:9222"):
    with sync_playwright() as p:
        try:
            print(f"Connecting to Chrome via CDP: {cdp_url}")
            browser = p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0]
            
            for entno in entnos:
                ent = str(entno).zfill(5)
                # ログイン後のパス /syllabus/ を使用
                url = f"https://gslbs.keio.jp/syllabus/detail?ttblyr={year}&entno={ent}&lang=jp"
                
                print(f"[{ent}] Fetching...")
                page = context.new_page()
                try:
                    page.goto(url, wait_until="networkidle", timeout=60000)
                    
                    if "指定した科目のシラバスは存在しません" in page.content():
                        print(f"[{ent}] No syllabus found.")
                        continue
                        
                    payload = {
                        "year": year,
                        "entno": ent,
                        "data": parse_detail_content(page)
                    }
                    
                    # GAS へ送信
                    print(f"[{ent}] Sending to GAS...")
                    res = requests.post(gas_url, json=payload, timeout=30)
                    if res.status_code == 200:
                        print(f"[{ent}] Successfully synced: {res.text}")
                    else:
                        print(f"[{ent}] Failed to sync: HTTP {res.status_code} - {res.text}")
                        
                except Exception as e:
                    print(f"[{ent}] Error during fetch: {e}")
                finally:
                    page.close()
                
                # 負荷軽減のためのウェイト
                time.sleep(1)
                
            browser.close()
        except Exception as e:
            print(f"Failed to connect or sync: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gas-url", required=True, help="GAS Web App URL")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--entnos", required=True, help="カンマ区切りID (例: 00010,00011)")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    args = parser.parse_args()
    
    entno_list = [e.strip() for e in args.entnos.split(",") if e.strip()]
    sync(args.gas_url, args.year, entno_list, args.cdp_url)
