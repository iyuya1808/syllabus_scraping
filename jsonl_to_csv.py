import json
import csv
import argparse
from pathlib import Path

def convert(input_jsonl, output_csv):
    input_path = Path(input_jsonl)
    if not input_path.exists():
        print(f"Error: {input_jsonl} not found.")
        return

    print(f"Reading {input_jsonl} and scanning for columns...")
    
    # 1. すべてのユニークなキー（カラム名）を収集
    all_keys = set()
    rows_dict = {} # entno をキーにして重複を排除
    
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try:
                data = json.loads(line)
                entno = data.get("entno", "")
                
                # ネストされた table と sections をフラット化
                flat_data = {
                    "entno": entno,
                    "year": data.get("year", ""),
                    "title": data.get("title", ""),
                    "fetched_at": data.get("fetched_at", ""),
                }
                flat_data.update(data.get("table", {}))
                flat_data.update(data.get("sections", {}))
                
                all_keys.update(flat_data.keys())
                # 同じ entno なら上書き（最新の状態を保持）
                rows_dict[entno] = flat_data
            except Exception as e:
                print(f"Error parsing line: {e}")

    # リストに変換してソート
    rows = sorted(rows_dict.values(), key=lambda x: x["entno"])
    header = ["entno", "year", "title", "fetched_at"]
    remaining_keys = sorted(list(all_keys - set(header)))
    full_header = header + remaining_keys

    # 3. CSV への書き出し
    print(f"Writing {len(rows)} rows with {len(full_header)} columns to {output_csv}...")
    with open(output_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=full_header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    # 4. JSON への書き出し (一括配列形式)
    output_json = output_csv.replace(".csv", ".json")
    print(f"Writing to {output_json}...")
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
            
    print("Done!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="syllabus_2026.jsonl")
    parser.add_argument("--output", default="syllabus_2026.csv")
    args = parser.parse_args()
    
    convert(args.input, args.output)
