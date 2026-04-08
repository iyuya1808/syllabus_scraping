# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 概要

慶應義塾大学シラバスサイト（`gslbs.keio.jp`）から、MFA認証が必要な科目情報を大量取得するPythonツール群。Playwrightでブラウザを操作し、JSONL形式で保存後にCSV/JSONへ変換する。

## セットアップ

```bash
pip install playwright
python -m playwright install chromium
```

## コマンド

### 認証フロー（初回・セッション切れ時）

```bash
# 1. デバッグポート付きでChromeを起動（GUIで手動ログイン・MFA完了）
./start_chrome_debug.sh

# 2. ログイン済みセッションをauth.jsonに保存
python save_auth.py
```

### スクレイピング

```bash
# 昇順（並列実行を推奨: 別ターミナルで降順も同時起動）
python mega_scraper.py --year 2026 --direction up --headless --batch 20000

# 降順（別ターミナルで同時実行）
python mega_scraper.py --year 2026 --direction down --headless --batch 20000
```

### データエクスポート

```bash
python jsonl_to_csv.py --input syllabus_2026.jsonl --output syllabus_2026.csv
# → syllabus_2026.csv と syllabus_2026.json が生成される
```

## アーキテクチャ

### 認証の仕組み

Playwrightには直接MFA認証を突破する手段がないため、**CDP（Chrome DevTools Protocol）経由**で迂回する。`start_chrome_debug.sh`でポート9222にデバッグ用Chromeを起動し、ユーザーが手動でログイン・MFAを完了した後、`save_auth.py`がCDP接続でクッキーやセッション情報を`auth.json`（Playwright storage state形式）に丸ごと保存する。以降の`mega_scraper.py`はこの`auth.json`をそのままPlaywrightのcontextに渡してヘッドレス実行する。

### スクレイピングの流れ（`mega_scraper.py`）

`MegaScraper`クラスが以下を管理する：

- **IDレンジ**: `entno`は`00001`〜`99999`の5桁ゼロパディング。`up`方向は1から昇順、`down`は99999から降順で進む。並列実行することで取得時間を約半分に短縮。
- **レジューム**: 10件ごとに`progress_{year}_{direction}.json`へ`next_entno`を書き込む。再実行時はここから再開。
- **出力**: `syllabus_{year}.jsonl`へアペンド。各行はJSON1オブジェクト（entno, year, title, table, sections）。
- **ページパース**: `parse_detail_content()`がページの`h2`（タイトル）、`table`（授業情報テーブル）、`h3`+次兄弟要素（各セクション本文）を抽出する。

### エクスポートの仕組み（`jsonl_to_csv.py`）

- `entno`をキーにした辞書で重複排除（昇順・降順が中央で重複取得した分を自動解消）
- ネストされた`table`と`sections`をフラット化してCSVカラムにマッピング
- 出力はUTF-8 BOM付きCSV（Excel対応）と通常のJSON配列

### ファイル命名規則

| ファイル | 内容 |
|---|---|
| `syllabus_{year}.jsonl` | スクレイピング生データ（アペンド） |
| `progress_{year}_{direction}.json` | 進捗管理（`next_entno`を保存） |
| `auth.json` | Playwrightセッション状態（`.gitignore`済み） |
| `syllabus_{year}.csv` / `.json` | エクスポート成果物 |

## 注意事項

- `auth.json`と`*.jsonl`は`.gitignore`対象。コミットしない。
- 取得速度は`time.sleep(0.5)`で制御。変更時はサーバへの負荷に注意。
- スクレイピング中はPCのスリープを無効にし、電源を接続すること。
