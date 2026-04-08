#!/usr/bin/env bash
# GX10 で手動ログイン用のブラウザをデバッグポート付きで起動する。
# 使い方: ./start_chrome_debug.sh
# 前提: GUI セッション（echo $DISPLAY が空でないこと）
#
# 環境変数:
#   CHROME_CMD      実行ファイルのフルパス（最優先）
#   CHROME_DEBUG_PORT  既定 9222
#   CHROME_KEIO_PROFILE  ユーザーデータディレクトリ
#   CHROME_NO_SANDBOX  既定 1（共有サーバで Chromium のサンドボックスが使えないとき）
#                        0 にすると --no-sandbox を付けない（ローカル PC の Chrome 向け）

set -euo pipefail
PORT="${CHROME_DEBUG_PORT:-9222}"
PROFILE="${CHROME_KEIO_PROFILE:-$HOME/.chrome-keio-debug}"
mkdir -p "$PROFILE"

# AppArmor / user namespace 制限環境（GX10 等）では Chromium が "No usable sandbox" で落ちるため
# ローカルの Mac では 0 (オフ) にすることを推奨。
IS_MAC=0
if [[ "$(uname)" == "Darwin" ]]; then
  IS_MAC=1
fi

SANDBOX_ARGS=()
# Mac の場合はデフォルトでサンドボックス無効フラグを付けない
DEFAULT_NO_SANDBOX="$((1 - IS_MAC))"
if [[ "${CHROME_NO_SANDBOX:-$DEFAULT_NO_SANDBOX}" != "0" ]]; then
  SANDBOX_ARGS=( --no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage )
fi

run_browser() {
  local bin="$1"
  shift
  echo "起動: $bin (port=$PORT, profile=$PROFILE)"
  if ((${#SANDBOX_ARGS[@]})); then
    echo "（CHROME_NO_SANDBOX: サンドボックス無効フラグを付与しています。不要なら CHROME_NO_SANDBOX=0）"
  fi
  # Bash 4.4 未満の set -u 対策で ${VAR[@]+"${VAR[@]}"} の形式を使用
  exec "$bin" ${SANDBOX_ARGS[@]+"${SANDBOX_ARGS[@]}"} \
    --remote-debugging-port="$PORT" \
    --user-data-dir="$PROFILE" \
    "https://gslbs.keio.jp/pub-syllabus/" \
    "$@"
}

if [[ -n "${CHROME_CMD:-}" ]]; then
  if [[ -x "$CHROME_CMD" ]]; then
    run_browser "$CHROME_CMD" "$@"
  else
    echo "CHROME_CMD が実行できません: $CHROME_CMD" >&2
    exit 1
  fi
fi

# 検索パスの追加
SEARCH_PATHS=(
  "google-chrome"
  "google-chrome-stable"
  "chromium"
  "chromium-browser"
  "brave-browser"
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  "/Applications/Chromium.app/Contents/MacOS/Chromium"
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
)

for cmd in "${SEARCH_PATHS[@]}"; do
  if [[ -x "$cmd" ]] || command -v "$cmd" &>/dev/null; then
    if [[ -x "$cmd" ]]; then
       run_browser "$cmd" "$@"
    else
       run_browser "$(command -v "$cmd")" "$@"
    fi
  fi
done

# Playwright が venv で入っている Chromium
playwright_chrome=""
shopt -s nullglob
if [[ "$IS_MAC" -eq 1 ]]; then
  pw=( "$HOME"/Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium )
else
  pw=( "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux/chrome )
fi

if ((${#pw[@]} > 0)); then
  IFS=$'\n' readarray -t sorted < <(printf '%s\n' "${pw[@]}" | sort -V)
  playwright_chrome="${sorted[-1]}"
fi
shopt -u nullglob

if [[ -n "$playwright_chrome" && -x "$playwright_chrome" ]]; then
  echo "（ヒント: システムに Google Chrome が無いため、Playwright 同梱 Chromium を使います）"
  run_browser "$playwright_chrome" "$@"
fi

echo "ブラウザが見つかりません。次を試してください:" >&2
echo "  1) venv で: python -m playwright install chromium" >&2
echo "  2) 実行ファイルを指定: CHROME_CMD=/path/to/chrome $0" >&2
echo "  3) 管理者に google-chrome-stable のインストールを依頼" >&2
exit 1
