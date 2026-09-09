#!/usr/bin/env python3
"""手元のマシンの X MCP 設定を読み取り、伏字レポートを吐く。

クラウド側からは見えないローカルの実物を、そのまま貼れる形にして持ってくるためのもの。
標準ライブラリのみ。読み取り専用で、何も書き換えない。

    python3 local_env_report.py

出力は秘密の値を伏字にする。redirect_uri と scope だけは、原因判定に必須なので
そのまま出す（どちらも秘密情報ではない）。
"""

from __future__ import annotations

import json
import os
import platform
import re
import sys
import urllib.parse

X_HINT = re.compile(r"(twitter|(?<![a-z])x[-_ ]?(api|mcp|post|tweet)|tweet)", re.I)

SECRET_HINT = re.compile(
    r"(secret|token|password|passwd|key|credential|bearer|verifier|cookie|auth)", re.I
)
# 秘密ではない = 全文表示してよいキー（原因判定に全文が要るもの）
PLAIN_HINT = re.compile(r"(redirect|callback|scope|url|endpoint)", re.I)
# 秘密ではないが識別子なので長さだけ見せるキー
IDENT_HINT = re.compile(r"(client_id|app_id|consumer_key)", re.I)


def mask(value: str) -> str:
    if not isinstance(value, str):
        return repr(value)
    if not value:
        return "(空)"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:4]}...{'*' * 6}(len={len(value)})"


def show(key: str, value) -> str:
    if not isinstance(value, str):
        return f"{key} = {value!r}"
    if PLAIN_HINT.search(key) and not SECRET_HINT.search(key):
        return f"{key} = {value!r}"
    if IDENT_HINT.search(key):
        return f"{key} = {mask(value)}   [設定あり・長さが合っているか確認]"
    if SECRET_HINT.search(key):
        return f"{key} = {mask(value)}   [設定あり]"
    return f"{key} = {value!r}"


def candidate_paths() -> list[str]:
    home = os.path.expanduser("~")
    system = platform.system()
    paths = [
        os.path.join(home, ".claude.json"),
        os.path.join(home, ".claude", "settings.json"),
        os.path.join(home, ".claude", "settings.local.json"),
        os.path.join(os.getcwd(), ".mcp.json"),
        os.path.join(os.getcwd(), ".claude", "settings.json"),
        os.path.join(os.getcwd(), ".claude", "settings.local.json"),
    ]
    if system == "Darwin":
        paths += [
            os.path.join(home, "Library", "Application Support", "Claude", "claude_desktop_config.json"),
            os.path.join(home, "Library", "Application Support", "Claude", "claude_desktop_config.local.json"),
        ]
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        paths += [os.path.join(appdata, "Claude", "claude_desktop_config.json")]
    else:
        paths += [
            os.path.join(home, ".config", "Claude", "claude_desktop_config.json"),
            os.path.join(home, ".config", "claude", "claude_desktop_config.json"),
        ]
    seen, out = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def collect_servers(path: str) -> dict:
    """設定ファイルから mcpServers を集める。projects 配下も掘る。"""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return {"__error__": str(exc)}
    if not isinstance(data, dict):
        return {}
    found = dict(data.get("mcpServers") or {})
    for proj, cfg in (data.get("projects") or {}).items():
        if not isinstance(cfg, dict):
            continue
        for name, scfg in (cfg.get("mcpServers") or {}).items():
            found[f"{name}  (project: {proj})"] = scfg
    return found


def describe_server(name: str, cfg: dict) -> list[str]:
    lines = [f"  ● {name}"]
    if not isinstance(cfg, dict):
        lines.append(f"      (形式が想定外: {type(cfg).__name__})")
        return lines
    kind = cfg.get("type") or ("stdio" if cfg.get("command") else "unknown")
    lines.append(f"      type    : {kind}")
    if cfg.get("command"):
        lines.append(f"      command : {cfg['command']}")
    if cfg.get("args"):
        safe_args = [a if not SECRET_HINT.search(str(a)) else mask(str(a)) for a in cfg["args"]]
        lines.append(f"      args    : {safe_args}")
    if cfg.get("url"):
        lines.append(f"      url     : {cfg['url']!r}")
    env = cfg.get("env") or {}
    if env:
        lines.append("      env     :")
        for k in sorted(env):
            lines.append(f"          {show(k, env[k])}")
    else:
        lines.append("      env     : (なし)")
    return lines


def judge(env: dict) -> list[str]:
    """env の顔ぶれから 1.0a 構成か 2.0 構成かを判定し、静的な穴を指摘する。"""
    out: list[str] = []
    keys = {k.upper() for k in env}
    joined = " ".join(keys)

    has_1a = any("API_KEY" in k or "CONSUMER" in k for k in keys) and any(
        "ACCESS_TOKEN_SECRET" in k or "ACCESS_SECRET" in k for k in keys
    )
    has_2 = any("CLIENT_ID" in k for k in keys)

    if has_1a:
        out.append("      判定: OAuth 1.0a 構成（API Key/Secret + Access Token/Secret）")
    if has_2:
        out.append("      判定: OAuth 2.0 構成（Client ID あり）")
    if not has_1a and not has_2:
        out.append("      判定: 認証情報が env に見当たらない。別ファイル（.env 等）から読んでいる可能性。")

    if has_2:
        secret_key = next((k for k in keys if "CLIENT_SECRET" in k), None)
        if secret_key and env.get(secret_key):
            out.append("      → client_secret あり = Confidential client 前提。")
            out.append("        Portal の Type of App が Native App なら、これが 401 の原因。")
        else:
            out.append("      → client_secret なし = Public client 前提。")
            out.append("        Portal の Type of App が Web App / Automated App or Bot なら、これが 401 の原因。")

        redirect_key = next((k for k in keys if "REDIRECT" in k or "CALLBACK" in k), None)
        if not redirect_key:
            out.append("      [NG] redirect_uri / callback が env に無い。MCP 内部でハードコードされている可能性。")
        else:
            raw = env[[k for k in env if k.upper() == redirect_key][0]]
            out += check_redirect(raw)

        scope_key = next((k for k in keys if "SCOPE" in k), None)
        if not scope_key:
            out.append("      [警告] scope が env に無い。MCP 内部の既定値が使われている。")
        else:
            raw = env[[k for k in env if k.upper() == scope_key][0]]
            out += check_scope(raw)

        if "OFFLINE" not in joined and not any("SCOPE" in k for k in keys):
            out.append("      [警告] offline.access の指定が確認できない。Refresh Token 未発行だと常駐運用で死ぬ。")
    return out


def check_redirect(raw) -> list[str]:
    out = [f"      redirect_uri: {raw!r}  <-- Portal の Callback URI と1バイトずつ照合すること"]
    if not isinstance(raw, str):
        return out + ["      [NG] 文字列ではない。"]
    if raw != raw.strip():
        out.append("      [NG] 前後に空白が入っている。完全一致しない。")
    if raw.endswith("/"):
        out.append("      [警告] 末尾が / 。Portal 側が / なしなら不一致になる。")
    if re.search(r"[^\x00-\x7f]", raw):
        out.append("      [NG] 非ASCII文字（全角コロン・全角スラッシュ等）が混入している。")
    p = urllib.parse.urlparse(raw)
    if p.scheme not in ("http", "https"):
        out.append(f"      [NG] scheme が {p.scheme!r}。")
    if p.scheme == "http" and p.hostname not in ("localhost", "127.0.0.1"):
        out.append("      [NG] localhost 以外で http は不可。https にする。")
    if p.query or p.fragment:
        out.append("      [NG] ? や # を含めてはいけない。")
    return out


def check_scope(raw) -> list[str]:
    out = [f"      scope: {raw!r}"]
    if not isinstance(raw, str):
        return out + ["      [NG] 文字列ではない。"]
    if "," in raw:
        out.append("      [NG] カンマ区切りは通らない。半角スペース区切りにする。")
    parts = raw.split()
    if "offline.access" not in parts:
        out.append("      [警告] offline.access が無い。Refresh Token が発行されない。")
    if "tweet.write" not in parts:
        out.append("      [警告] tweet.write が無い。投稿はできない。")
    if "users.read" not in parts:
        out.append("      [警告] users.read が無い。/2/users/me が 403 になる。")
    return out


def scan_env_files() -> list[str]:
    """カレント配下の .env 系に X 関連キーがあるか。値は読まず、キー名だけ。"""
    out = []
    for root, dirs, files in os.walk(os.getcwd()):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", "venv", ".venv")]
        if root.count(os.sep) - os.getcwd().count(os.sep) > 3:
            dirs[:] = []
        for fname in files:
            if not (fname == ".env" or fname.startswith(".env.")):
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    keys = [
                        ln.split("=", 1)[0].strip()
                        for ln in fh
                        if "=" in ln and not ln.strip().startswith("#")
                    ]
            except OSError:
                continue
            hits = [k for k in keys if X_HINT.search(k) or "CLIENT" in k.upper() or "OAUTH" in k.upper()]
            if hits:
                out.append(f"  {path}  ->  {hits}")
    return out


def main() -> int:
    print("=" * 70)
    print(" X MCP ローカル環境レポート")
    print("=" * 70)
    print(f"OS      : {platform.system()} {platform.release()}")
    print(f"Python  : {sys.version.split()[0]}")
    print(f"cwd     : {os.getcwd()}")
    print()

    any_x = False
    for path in candidate_paths():
        if not os.path.exists(path):
            print(f"[なし] {path}")
            continue
        servers = collect_servers(path)
        if "__error__" in servers:
            print(f"[読めず] {path}  ({servers['__error__']})")
            continue
        print(f"[存在] {path}  -> MCPサーバー {len(servers)} 件")
        for name, cfg in servers.items():
            is_x = bool(X_HINT.search(name)) or bool(
                X_HINT.search(json.dumps(cfg, ensure_ascii=False)) if isinstance(cfg, dict) else False
            )
            marker = "  ★X関連" if is_x else ""
            print(f"    - {name}{marker}")
            if is_x:
                any_x = True
        for name, cfg in servers.items():
            is_x = bool(X_HINT.search(name)) or bool(
                X_HINT.search(json.dumps(cfg, ensure_ascii=False)) if isinstance(cfg, dict) else False
            )
            if not is_x:
                continue
            print()
            for line in describe_server(name, cfg):
                print(line)
            for line in judge((cfg.get("env") or {}) if isinstance(cfg, dict) else {}):
                print(line)
        print()

    print("=== 環境変数（キー名のみ・値は出さない）===")
    hits = sorted(
        k for k in os.environ
        if X_HINT.search(k) or re.match(r"^(X_|TW_|OAUTH_|CONSUMER_)", k, re.I)
    )
    print(f"  {hits if hits else '該当なし'}")
    print()

    print("=== .env 系ファイル（キー名のみ）===")
    envs = scan_env_files()
    print("\n".join(envs) if envs else "  該当なし")
    print()

    if not any_x:
        print("結論: X 関連の MCP サーバーが設定ファイル上に見つからなかった。")
        print("      別のクライアント（ChatGPT デスクトップ等）に入れている場合は、そちらの設定を見る。")
    print("=" * 70)
    print("この出力は秘密の値を伏字にしている。そのまま貼ってよい。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
