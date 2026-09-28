#!/bin/bash
# SessionStart フック: x-mcp-oauth の構文チェックを最初に表面化させる。
# ネットワークアクセスはしない。失敗してもセッションは止めない（常に exit 0）。
set -u

if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    cd "$CLAUDE_PROJECT_DIR" || exit 0
else
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cd "$script_dir/../.." || exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "[session-start] 警告: python3 が見つからない。構文チェックをスキップする。"
    exit 0
fi

if ! python3 -m py_compile x-mcp-oauth/*.py; then
    echo "[session-start] 警告: x-mcp-oauth の構文チェックに失敗した。上記の出力を確認すること。"
fi

exit 0
