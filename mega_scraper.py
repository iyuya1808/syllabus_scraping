import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from playwright.async_api import Error, async_playwright


async def _stable_content(page, attempts: int = 10, delay_ms: int = 400) -> str:
    last_error: Error | None = None
    for _ in range(attempts):
        try:
            return await page.content()
        except Error as e:
            last_error = e
            if "navigating" in str(e).lower() or "connected" in str(e).lower():
                await page.wait_for_timeout(delay_ms)
            else:
                raise
    if last_error:
        raise last_error
    return ""


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    lines = text.split("\n")
    cleaned_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in lines]
    return "\n".join(line for line in cleaned_lines if line)


async def parse_detail_content(page) -> dict:
    data: dict = {"title": "", "table": {}, "sections": {}}

    title_node = await page.query_selector("h2")
    if title_node:
        data["title"] = clean_text(await title_node.inner_text())

    rows = await page.query_selector_all("table tr")
    for row in rows:
        th = await row.query_selector("th")
        td = await row.query_selector("td")
        if th and td:
            key = clean_text(await th.inner_text())
            val = clean_text(await td.inner_text())
            if key:
                data["table"][key] = val

    sections = await page.query_selector_all("h3")
    for sec in sections:
        sec_title = clean_text(await sec.inner_text()).replace("[説明]", "").strip()
        content_node = await page.evaluate_handle("node => node.nextElementSibling", sec)
        if content_node:
            val = clean_text(await page.evaluate("node => node.innerText", content_node))
            if sec_title:
                data["sections"][sec_title] = val

    return data


class MegaScraper:
    def __init__(self, year, direction="up", start_id=None, output_file=None,
                 progress_file=None, auth_file=None, headless=False,
                 workers=5, delay=0.3):
        self.year = year
        self.direction = direction
        self.workers = workers
        self.delay = delay

        out = output_file or f"syllabus_{year}_{direction}.jsonl"
        prog = progress_file or f"progress_{year}_{direction}.json"

        self.output_file = Path(out)
        self.progress_file = Path(prog)
        self.auth_file = Path(auth_file) if auth_file else None
        self.headless = headless

        self.progress = self._load_progress()
        if start_id is not None:
            self.progress["next_entno"] = start_id

    def _load_progress(self) -> dict:
        if self.progress_file.exists():
            with open(self.progress_file, "r") as f:
                return json.load(f)
        start = 1 if self.direction == "up" else 99999
        return {"next_entno": start}

    def _save_progress(self, next_entno: int) -> None:
        self.progress["next_entno"] = next_entno
        with open(self.progress_file, "w") as f:
            json.dump(self.progress, f)

    async def _fetch_one(self, context, entno: int, sem: asyncio.Semaphore) -> tuple[int, dict | None]:
        async with sem:
            ent = str(entno).zfill(5)
            url = f"https://gslbs.keio.jp/syllabus/detail?ttblyr={self.year}&entno={ent}&lang=jp"
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="load", timeout=60000)
                content = await _stable_content(page)

                if "指定した科目のシラバスは存在しません" in content:
                    return entno, None
                if len(content) < 1000:
                    print(f"\n[{ent}] Warning: Content too short ({len(content)} bytes)")
                    return entno, None

                item_data = await parse_detail_content(page)
                if not item_data["title"]:
                    print(f"\n[{ent}] Warning: Title not found.")
                    return entno, None

                return entno, {
                    "entno": ent,
                    "year": self.year,
                    "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    **item_data,
                }
            except Exception as e:
                print(f"\n[{ent}] Error: {e}")
                return entno, None
            finally:
                await page.close()
                # セマフォを保持したまま待機することで全体のリクエスト頻度を制御
                await asyncio.sleep(self.delay)

    async def _run_async(self, batch_size: int) -> None:
        start_entno = self.progress["next_entno"]
        print(
            f"Starting mega scrape "
            f"(Year: {self.year}, Direction: {self.direction}, "
            f"StartID: {start_entno}, Workers: {self.workers}, Headless: {self.headless})"
        )

        async with async_playwright() as p:
            print(f"Launching browser (Headless: {self.headless}, Auth: {self.auth_file})")
            browser = await p.chromium.launch(headless=self.headless)
            storage_state = (
                str(self.auth_file)
                if self.auth_file and self.auth_file.exists()
                else None
            )
            context = await browser.new_context(storage_state=storage_state)
            sem = asyncio.Semaphore(self.workers)

            # チャンクサイズ = workers の倍数にすることで均等に並列化しつつ
            # 定期的に進捗を保存する
            chunk_size = self.workers * 4
            current_entno = start_entno
            total_done = 0

            try:
                while total_done < batch_size:
                    # 今回処理するIDリストを構築
                    chunk: list[int] = []
                    temp = current_entno
                    for _ in range(min(chunk_size, batch_size - total_done)):
                        if temp < 1 or temp > 99999:
                            break
                        chunk.append(temp)
                        temp = temp + 1 if self.direction == "up" else temp - 1

                    if not chunk:
                        print(f"\nReached ID boundary at {current_entno}.")
                        break

                    tasks = [self._fetch_one(context, eno, sem) for eno in chunk]
                    results = await asyncio.gather(*tasks)

                    # ファイル書き込みはまとめて行う（I/O回数を削減）
                    with open(self.output_file, "a", encoding="utf-8") as f:
                        for _, record in results:
                            if record:
                                f.write(json.dumps(record, ensure_ascii=False) + "\n")

                    current_entno = temp
                    total_done += len(chunk)
                    self._save_progress(current_entno)
                    print(
                        f"Progress: {total_done}/{batch_size} "
                        f"(next: {str(current_entno).zfill(5)})   ",
                        end="\r",
                    )

                print(f"\nBatch completed. Next starting ID: {str(current_entno).zfill(5)}")

            except KeyboardInterrupt:
                print("\nInterrupted. Saving progress...")
            finally:
                self._save_progress(current_entno)
                await browser.close()

    def run(self, batch_size: int = 1000) -> None:
        asyncio.run(self._run_async(batch_size))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=1000, help="1回の実行で取得する件数")
    parser.add_argument("--year", type=int, default=2026, help="シラバスの年度")
    parser.add_argument("--start", type=str, default=None, help="開始する登録番号 (entno)")
    parser.add_argument("--direction", choices=["up", "down"], default="up")
    parser.add_argument("--workers", type=int, default=5, help="並列タブ数 (推奨: 3〜10)")
    parser.add_argument("--delay", type=float, default=0.3, help="1リクエストあたりの待機秒数")
    parser.add_argument("--out", default=None)
    parser.add_argument("--prog", default=None)
    parser.add_argument("--auth", default="auth.json")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    start_id = None
    if args.start and args.start.strip():
        try:
            start_id = int(args.start)
        except ValueError:
            print(f"Warning: Invalid start ID '{args.start}', using default.")

    scraper = MegaScraper(
        args.year,
        direction=args.direction,
        start_id=start_id,
        output_file=args.out,
        progress_file=args.prog,
        auth_file=args.auth,
        headless=args.headless,
        workers=args.workers,
        delay=args.delay,
    )
    scraper.run(batch_size=args.batch)
