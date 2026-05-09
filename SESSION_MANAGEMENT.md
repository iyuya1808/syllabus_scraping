# セッション管理の仕組み

慶應義塾大学シラバスサイト（`gslbs.keio.jp`）はShibboleth + MFA認証が必要なため、
Playwrightだけでは自動ログインできない。そのため **CDPを経由した認証情報の横取り** という方式を採用している。

---

## 全体フロー

```
1. start_chrome_debug.sh
   └─ デバッグポート(9222)付きでChromeを起動

2. ユーザーが手動でMFA認証を完了

3. save_auth.py
   └─ CDP経由で認証済みコンテキストに接続
   └─ Cookie・LocalStorage等をauth.jsonに保存

4. mega_scraper.py / keio_session.py
   └─ auth.jsonをPlaywrightに渡してヘッドレス実行
   └─ Chromeを閉じた後もセッションが維持される
```

---

## Step 1: Chromeをデバッグモードで起動（`start_chrome_debug.sh`）

```bash
./start_chrome_debug.sh
```

- `--remote-debugging-port=9222` を付けてChromeを起動する
- プロファイルは `~/.chrome-keio-debug` に保存される（通常のChromeとは別の専用プロファイル）
- 起動後、自動的に `https://gslbs.keio.jp/pub-syllabus/` が開く
- Macでは `--no-sandbox` フラグを付けない（Linuxサーバーでは付ける）

**対応ブラウザの検索順序（`CHROME_CMD` 未指定時）:**
1. `google-chrome` / `google-chrome-stable` / `chromium` / `brave-browser` (PATHから)
2. `/Applications/Google Chrome.app/...` など Mac定番パス
3. Playwright同梱のChromium (`~/Library/Caches/ms-playwright/...`)

環境変数でカスタマイズ可能:

| 環境変数 | 既定値 | 説明 |
|---|---|---|
| `CHROME_CMD` | - | ブラウザ実行ファイルのフルパス（最優先） |
| `CHROME_DEBUG_PORT` | `9222` | CDPデバッグポート |
| `CHROME_KEIO_PROFILE` | `~/.chrome-keio-debug` | ユーザーデータディレクトリ |
| `CHROME_NO_SANDBOX` | Mac=`0`, Linux=`1` | `--no-sandbox` フラグの有無 |

---

## Step 2: ユーザーによる手動ログイン

起動されたChromeでShibboleth経由のMFA認証を完了させる。
スクリプトは一切介入しない。

---

## Step 3: 認証情報を保存（`save_auth.py`）

```bash
python save_auth.py
```

```python
# 内部処理
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")  # 起動中のChromeに接続
context = browser.contexts[0]
context.storage_state(path="auth.json")  # Cookie + LocalStorage を丸ごと保存
```

- PlaywrightのCDP接続機能で、**すでに起動中のChromeに後付けで接続**する
- Playwright独自の `storage_state` 形式（JSON）でクッキーとストレージを一括保存
- 保存後はChromeを閉じてよい（`auth.json` にセッション情報が全て入っている）

`auth.json` の構造（Playwright storage state形式）:

```json
{
  "cookies": [ { "name": "...", "value": "...", "domain": "gslbs.keio.jp", ... } ],
  "origins": [ { "origin": "https://gslbs.keio.jp", "localStorage": [...] } ]
}
```

---

## Step 4: ヘッドレス実行（`mega_scraper.py` / `keio_session.py`）

保存した `auth.json` をそのまま新規Playwrightコンテキストに渡す:

```python
context = browser.new_context(storage_state="auth.json")
```

これだけで、Chromeが閉じていてもログイン済み状態として動作する。

---

## セッション維持の仕組み（`keio_session.py`）

長時間スクレイピングでセッションが切れるのを防ぐため、`KeioSyllabusSession` クラスが以下を提供する:

### キープアライブ（バックグラウンドスレッド）

```python
with KeioSyllabusSession(keepalive_interval_sec=300) as session:
    ...
```

- 別スレッドで `keepalive_interval_sec` 秒ごとにシラバストップページへアクセスする
- `threading.Lock` で取得処理とキープアライブの競合を防ぐ
- `flush_storage_on_keepalive=True` にすると、キープアライブのたびに `auth.json` を上書き保存する

### セッション切れ検知

アクセスしたページのURLとHTMLコンテンツで切れを判断:

```python
# URLでの判定: gslbs.keio.jp 以外（Shibboleth等）にリダイレクトされていないか
# HTMLでの判定: 以下のキーワードが含まれていないか
_LOGIN_WALL_MARKERS = (
    "ログインしてください",
    "再度ログイン",
    "セッションが無効",
    "セッションの有効期限",
    "Session Expired",
    "Shibboleth",
    "慶應義塾大学ログイン",
)
```

切れが検知されると `KeioAuthExpiredError` が発生する。

### セッション切れからの自動復旧

```python
html = session.fetch_detail_html(year, entno, auto_reload_auth=True)
```

`auto_reload_auth=True` を指定すると、切れを検知した際に `auth.json` を再読み込みして1回だけリトライする。
（サーバー上で実行中に手元PCで `save_auth.py` を再実行し `auth.json` を差し替える運用と組み合わせる）

手動での認証再読み込みも可能:

```python
session.reload_auth_from_disk()  # ブラウザを再起動せずにContextだけ作り直す
```

---

## セッション状態の確認（`check_session_status.py`）

```bash
python check_session_status.py
```

`auth.json` を使って実際にログインできているか確認する。
「ログアウト」ボタンの有無と「様」の表示からログイン状態を判定する。

---

## 注意事項

- `auth.json` にはログインセッション情報が含まれるため `.gitignore` 対象（コミット禁止）
- セッションの有効期限はサーバー設定依存。切れた場合は Step 1〜3 をやり直す
- `start_chrome_debug.sh` と通常のChromeは**プロファイルが別**なので干渉しない
