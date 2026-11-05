#!/usr/bin/env python3
"""Claude の設定ファイル（JSON）に MCP サーバーを1件登録する。標準ライブラリのみ。

PowerShell の ConvertTo-Json は深い入れ子を切り捨てるので、~/.claude.json のような
大きな設定を壊しかねない。登録は必ずこの Python 側で、既存の中身を保ったまま行う。

    python mcp_register.py --config C:/Users/<名前>/.claude.json --code \
        --command C:/.../python.exe --arg C:/.../x_mcp_server.py

  --code   Claude Code 形式で書く（"type": "stdio" を付ける）
  --print  書き込まず、登録内容だけ表示する
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time


def build_entry(command: str, args: list[str], code: bool) -> dict:
    entry: dict = {"command": command, "args": args, "env": {}}
    if code:
        entry = {"type": "stdio", **entry}
    return entry


def register(config_path: str, name: str, entry: dict) -> tuple[int, str]:
    """設定に登録する。戻り値は (終了コード, メッセージ)。既存の中身は触らない。"""
    data: dict = {}
    backup = ""
    if os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return 1, f"[NG] 既存の設定が JSON として読めない。手を加えず中止した: {e}"
        if not isinstance(data, dict):
            return 1, "[NG] 既存の設定の最上位がオブジェクトではない。中止した。"
        backup = f"{config_path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(config_path, backup)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(config_path)), exist_ok=True)

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    replaced = name in servers
    servers[name] = entry

    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, config_path)

    lines = []
    if backup:
        lines.append(f"[OK] バックアップ: {backup}")
    lines.append(f"[OK] {'上書き' if replaced else '追加'}: mcpServers.{name} -> {config_path}")
    return 0, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude の設定に MCP サーバーを登録する")
    parser.add_argument("--config", required=True, help="設定ファイルのパス")
    parser.add_argument("--name", default="x-oauth1", help="登録名")
    parser.add_argument("--command", required=True, help="起動コマンド（python.exe の絶対パス）")
    parser.add_argument("--arg", action="append", default=[], help="起動引数（複数可）")
    parser.add_argument("--code", action="store_true", help="Claude Code 形式で書く")
    parser.add_argument("--print", action="store_true", help="書き込まず内容だけ表示")
    args = parser.parse_args()

    entry = build_entry(args.command, args.arg, args.code)
    print(json.dumps({"mcpServers": {args.name: entry}}, ensure_ascii=False, indent=2))
    if args.print:
        print("[..] --print 指定のため書き込まない。")
        return 0
    rc, msg = register(args.config, args.name, entry)
    print(msg)
    return rc


if __name__ == "__main__":
    sys.exit(main())
