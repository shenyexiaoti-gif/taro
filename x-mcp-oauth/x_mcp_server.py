#!/usr/bin/env python3
"""X (Twitter) を OAuth 1.0a で操作する最小の MCP サーバー。標準ライブラリのみ。

npm パッケージを落とさないので、外部実行ファイルを消すタイプのセキュリティ製品に
引っかからない。署名は x_oauth1_check.py の実装をそのまま使う（手元で read-write 通過済み）。

Claude Desktop / Claude Code から stdio 経由の JSON-RPC で呼ばれる。
公開するツールは3つ。

    x_get_me        自分のアカウント情報を返す（読み取り）
    x_search_recent 直近のポストを検索する（読み取り）
    x_post_tweet    ポストを1件投稿する（書き込み。実行前に Claude 側が承認を求める）

秘密の値は .env から読む。設定ファイル（JSON）には書かない。
単体で疎通を見るなら:  python3 x_mcp_server.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from x_oauth1_check import Config, authorization_header, load_dotenv

API_BASE = "https://api.x.com/2"
ME_URL = f"{API_BASE}/users/me"
TWEETS_URL = f"{API_BASE}/tweets"
SEARCH_URL = f"{API_BASE}/tweets/search/recent"

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "x-oauth1-mcp", "version": "0.1.0"}

TWEET_MAX = 280

TOOLS = [
    {
        "name": "x_get_me",
        "description": "認証中の X アカウント（自分）の id・username・name を返す。読み取りのみ。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "x_search_recent",
        "description": "直近7日のポストを検索する。読み取りのみ。query は X の検索構文。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索クエリ（例: from:someone キーワード）"},
                "max_results": {"type": "integer", "minimum": 10, "maximum": 100, "default": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "x_post_tweet",
        "description": (
            "ポストを1件投稿する。書き込み操作なので、実行前に必ず内容を人へ提示して承認を得ること。"
            f"本文は最大{TWEET_MAX}文字。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "投稿する本文"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "x_delete_tweet",
        "description": "指定した id のポストを削除する。書き込み操作。テスト投稿の後始末に使う。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "削除するポストの id"},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
]


# ---------------------------------------------------------------- HTTP


def _request(cfg: Config, method: str, url: str, oauth_params: dict[str, str] | None,
             body: bytes | None, content_type: str | None) -> tuple[int, str]:
    """署名付きで1本投げる。oauth_params は署名に含めるクエリ等（JSONボディは含めない）。"""
    header = authorization_header(cfg, method, url, oauth_params)
    headers = {"Authorization": header}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, json.dumps({"error": "network", "detail": str(getattr(e, "reason", e))})


def _fail(status: int, body: str) -> str:
    hint = {
        0: "X まで届いていない。回線・プロキシ・セキュリティ製品の遮断を疑う。",
        401: "署名が通っていない。.env の4つの値、または手元の時計のずれを疑う。",
        403: "権限不足。App が Project に紐づいているか、App permissions を確認する。",
        429: "レート制限。時間を置いて再実行する。",
    }.get(status, "想定外の応答。")
    return f"HTTP {status}: {hint}\n{body[:500]}"


# ---------------------------------------------------------------- tools


def tool_get_me(cfg: Config, _args: dict) -> str:
    status, body = _request(cfg, "GET", ME_URL, None, None, None)
    if status != 200:
        return _fail(status, body)
    data = json.loads(body).get("data", {})
    return json.dumps(data, ensure_ascii=False)


def tool_search_recent(cfg: Config, args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "query が空。"
    params = {"query": query, "max_results": str(int(args.get("max_results", 10)))}
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    # クエリ文字列のパラメータも署名対象に含める（GET のクエリは署名に入る）
    status, body = _request_with_query(cfg, url, params)
    if status != 200:
        return _fail(status, body)
    return body


def _request_with_query(cfg: Config, url: str, query_params: dict[str, str]) -> tuple[int, str]:
    base_url = url.split("?", 1)[0]
    header = authorization_header(cfg, "GET", base_url, query_params)
    req = urllib.request.Request(url, headers={"Authorization": header})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, json.dumps({"error": "network", "detail": str(getattr(e, "reason", e))})


def tool_post_tweet(cfg: Config, args: dict) -> str:
    text = args.get("text") or ""
    if not text.strip():
        return "text が空。投稿しない。"
    if len(text) > TWEET_MAX:
        return f"本文が長い（{len(text)}文字）。{TWEET_MAX}文字以内にする。投稿しない。"
    body = json.dumps({"text": text}).encode("utf-8")
    # JSON ボディは OAuth 1.0a の署名対象に含めない（form-urlencoded のときだけ含める）
    status, resp = _request(cfg, "POST", TWEETS_URL, None, body, "application/json")
    if status not in (200, 201):
        return _fail(status, resp)
    data = json.loads(resp).get("data", {})
    return f"投稿した。id={data.get('id', '')} text={data.get('text', '')}"


def tool_delete_tweet(cfg: Config, args: dict) -> str:
    tweet_id = (args.get("id") or "").strip()
    if not tweet_id:
        return "id が空。削除しない。"
    url = f"{TWEETS_URL}/{urllib.parse.quote(tweet_id)}"
    status, resp = _request(cfg, "DELETE", url, None, None, None)
    if status != 200:
        return _fail(status, resp)
    deleted = json.loads(resp).get("data", {}).get("deleted")
    return f"削除した（deleted={deleted}）。id={tweet_id}"


DISPATCH = {
    "x_get_me": tool_get_me,
    "x_search_recent": tool_search_recent,
    "x_post_tweet": tool_post_tweet,
    "x_delete_tweet": tool_delete_tweet,
}


# ---------------------------------------------------------------- JSON-RPC


def handle(msg: dict, cfg: Config) -> dict | None:
    """1件の JSON-RPC メッセージを処理する。通知（id なし）には None を返す。"""
    method = msg.get("method")
    mid = msg.get("id")

    if method == "initialize":
        return _ok(mid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        fn = DISPATCH.get(name)
        if fn is None:
            return _err(mid, -32602, f"未知のツール: {name}")
        try:
            text = fn(cfg, params.get("arguments") or {})
            return _ok(mid, {"content": [{"type": "text", "text": text}]})
        except Exception as e:  # ツールの失敗は結果として返す（サーバーは落とさない）
            return _ok(mid, {"content": [{"type": "text", "text": f"失敗: {e}"}], "isError": True})
    if mid is None:
        return None
    return _err(mid, -32601, f"未対応のメソッド: {method}")


def _ok(mid, result) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, message) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def serve(cfg: Config) -> int:
    """stdin から1行1メッセージで受け、stdout へ返す。"""
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        reply = handle(msg, cfg)
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False) + "\n")
            out.flush()
    return 0


def selftest(cfg: Config) -> int:
    missing = cfg.missing()
    if missing:
        print(f"[NG] .env に値が足りない: {', '.join(missing)}")
        return 1
    print("[..] x_get_me を実行")
    print(tool_get_me(cfg, {}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="X OAuth 1.0a MCP サーバー")
    parser.add_argument("--selftest", action="store_true", help="stdio を使わず x_get_me を1回叩く")
    parser.add_argument("--env", default=".env", help=".env のパス")
    args = parser.parse_args()

    load_dotenv(args.env)
    cfg = Config()
    if args.selftest:
        return selftest(cfg)
    return serve(cfg)


if __name__ == "__main__":
    sys.exit(main())
