import json
import argparse
from pathlib import Path

def merge_jsonl(output_file, input_files):
    data = {}
    
    for file_path in input_files:
        path = Path(file_path)
        if not path.exists():
            print(f"Warning: {file_path} not found. Skipping.")
            continue
            
        print(f"Reading {file_path}...")
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)
                entno = item.get("entno")
                if entno:
                    # 重複がある場合は、より新しいデータを優先（Fetched At で比較も可能だが、ここでは上書き）
                    data[entno] = item
    
    # entno 順にソート
    sorted_items = sorted(data.values(), key=lambda x: x["entno"])
    
    print(f"Writing {len(sorted_items)} items to {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        for item in sorted_items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    print("Done!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="昇順・降順のJSONLファイルをマージしてソートします。")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    
    out_file = args.out or f"syllabus_{args.year}.jsonl"
    in_files = [f"syllabus_{args.year}_up.jsonl", f"syllabus_{args.year}_down.jsonl"]
    
    # 既存の syllabus_2026.jsonl も含める（もしあれば）
    legacy_file = f"syllabus_{args.year}.jsonl"
    if Path(legacy_file).exists() and legacy_file != out_file:
        in_files.append(legacy_file)
        
    merge_jsonl(out_file, in_files)
