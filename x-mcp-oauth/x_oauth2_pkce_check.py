#!/usr/bin/env python3
"""X (Twitter) API OAuth 2.0 Authorization Code Flow + PKCE の切り分けツール。

標準ライブラリだけで動く。MCPサーバーを経由せず、素のHTTPで同じ認可を通し、
どの工程で落ちているかを実データで確定させるのが目的。

使い方:
    cp .env.example .env   # 値を埋める
    python3 x_oauth2_pkce_check.py --check-config     # 設定の目視ズレを検出
    python3 x_oauth2_pkce_check.py                    # 認可フローを実走
    python3 x_oauth2_pkce_check.py --refresh <token>  # 更新だけ検証

トークンは伏字で表示する。標準出力をそのまま貼っても秘密は漏れない。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
REVOKE_URL = "https://api.x.com/2/oauth2/revoke"
ME_URL = "https://api.x.com/2/users/me"

DEFAULT_SCOPES = "tweet.read tweet.write users.read offline.access"


# ---------------------------------------------------------------- env loading


def load_dotenv(path: str) -> None:
    """.env を最小限だけ読む。既に環境変数にある値は上書きしない。"""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


class Config:
    def __init__(self) -> None:
        self.client_id = os.environ.get("X_CLIENT_ID", "")
        self.client_secret = os.environ.get("X_CLIENT_SECRET", "")
        self.redirect_uri = os.environ.get("X_REDIRECT_URI", "")
        self.scopes = os.environ.get("X_SCOPES", DEFAULT_SCOPES)
        self.challenge_method = os.environ.get("X_CODE_CHALLENGE_METHOD", "S256")

    def missing(self) -> list[str]:
        out = []
        if not self.client_id:
            out.append("X_CLIENT_ID")
        if not self.redirect_uri:
            out.append("X_REDIRECT_URI")
        return out


def mask(value: str, keep: int = 6) -> str:
    if not value:
        return "(empty)"
    if len(value) <= keep:
        return "*" * len(value)
    return f"{value[:keep]}...{'*' * 8}(len={len(value)})"


# ------------------------------------------------------------ config checking


def check_config(cfg: Config) -> int:
    """目で見ても分からないズレ ── 末尾スラッシュ、空白、全角、大小文字 ── を暴く。"""
    print("=== 設定チェック ===")
    problems: list[str] = []
    warnings: list[str] = []

    missing = cfg.missing()
    if missing:
        print(f"[NG] 未設定: {', '.join(missing)}")
        return 1

    print(f"client_id      : {mask(cfg.client_id)}")
    print(f"client_secret  : {mask(cfg.client_secret) if cfg.client_secret else '(未設定 = Public client として扱う)'}")
    print(f"redirect_uri   : {cfg.redirect_uri!r}   <-- Developer Portal の Callback URI と1バイトずつ比較すること")
    print(f"scopes         : {cfg.scopes!r}")
    print(f"challenge方式  : {cfg.challenge_method}")
    print()

    raw = os.environ.get("X_REDIRECT_URI", "")
    if raw != raw.strip():
        problems.append("X_REDIRECT_URI の前後に空白がある。")
    if cfg.redirect_uri.endswith("/"):
        warnings.append(
            "redirect_uri が / で終わっている。Portal 側が / なしなら完全一致しない。"
        )
    if re.search(r"[^\x00-\x7f]", cfg.redirect_uri):
        problems.append("redirect_uri に非ASCII文字（全角スラッシュ・全角コロンなど）が混ざっている。")
    parsed = urllib.parse.urlparse(cfg.redirect_uri)
    if parsed.scheme not in ("http", "https"):
        problems.append(f"redirect_uri の scheme が {parsed.scheme!r}。http か https にする。")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1"):
        problems.append("http は localhost / 127.0.0.1 以外では受け付けられない。https にする。")
    if parsed.query or parsed.fragment:
        problems.append("redirect_uri に ? や # を付けてはいけない。")

    scopes = cfg.scopes.split()
    if len(scopes) != len(set(scopes)):
        warnings.append("scope に重複がある。")
    if "," in cfg.scopes:
        problems.append("scope の区切りはカンマではなく半角スペース。")
    if "tweet.write" in scopes and "tweet.read" not in scopes:
        warnings.append("tweet.write を使うなら tweet.read も要る構成が一般的。")
    if "offline.access" not in scopes:
        warnings.append(
            "offline.access が無い。Refresh Token が発行されず、MCP常駐運用ではトークン切れで死ぬ。"
        )
    if cfg.challenge_method not in ("S256", "plain"):
        problems.append("X_CODE_CHALLENGE_METHOD は S256 か plain。")

    for p in problems:
        print(f"[NG] {p}")
    for w in warnings:
        print(f"[警告] {w}")
    if not problems and not warnings:
        print("[OK] 静的チェックでは問題なし。実走に進む。")
    print()
    print("Portal 側の確認事項（ツールからは見えない）:")
    print("  - User authentication settings が有効で、App permissions が Read and write 以上か")
    print("  - Type of App が Web App / Automated App or Bot なら Confidential client → client_secret 必須")
    print("  - Type of App が Native App なら Public client → client_secret は送ってはいけない")
    print("  - Callback URI に上記 redirect_uri が1件として登録されているか")
    return 1 if problems else 0


# ------------------------------------------------------------------ PKCE core


def make_pkce(method: str) -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    if method == "plain":
        return verifier, verifier
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def build_authorize_url(cfg: Config, challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "scope": cfg.scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": cfg.challenge_method,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"


# --------------------------------------------------------------- HTTP helpers


def post_form(url: str, data: dict[str, str], basic_auth: tuple[str, str] | None) -> tuple[int, dict, str]:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if basic_auth:
        token = base64.b64encode(f"{basic_auth[0]}:{basic_auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", "replace")
            return resp.status, safe_json(text), text
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        return exc.code, safe_json(text), text
    except urllib.error.URLError as exc:
        return 0, {}, f"network error: {exc.reason}"


def get_json(url: str, bearer: str) -> tuple[int, str]:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        return 0, f"network error: {exc.reason}"


def safe_json(text: str) -> dict:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


# -------------------------------------------------------------- callback wait


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict = {}
    expected_path: str = "/"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != self.expected_path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(
                f"path mismatch: got {parsed.path} / expected {self.expected_path}".encode()
            )
            _CallbackHandler.result = {
                "error": "path_mismatch",
                "got": parsed.path,
                "expected": self.expected_path,
            }
            return
        query = dict(urllib.parse.parse_qsl(parsed.query))
        _CallbackHandler.result = query
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("受け取った。ターミナルに戻ってよい。\n".encode("utf-8"))

    def log_message(self, *_args) -> None:
        return


def wait_for_callback(redirect_uri: str, timeout: int) -> dict:
    parsed = urllib.parse.urlparse(redirect_uri)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    _CallbackHandler.result = {}
    _CallbackHandler.expected_path = parsed.path or "/"
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = 1
    deadline = time.time() + timeout
    while time.time() < deadline and not _CallbackHandler.result:
        server.handle_request()
    server.server_close()
    return _CallbackHandler.result


def is_local(redirect_uri: str) -> bool:
    host = urllib.parse.urlparse(redirect_uri).hostname
    return host in ("localhost", "127.0.0.1")


# ------------------------------------------------------------------ diagnosis


def diagnose_token_error(status: int, payload: dict, body: str, cfg: Config, elapsed: float) -> None:
    err = payload.get("error", "")
    desc = payload.get("error_description", "") or payload.get("detail", "")
    print("--- 判定 ---")
    if status == 0:
        print("ネットワーク到達性の問題。プロキシ／DNS を疑う。OAuth の設定ではない。")
        return
    if status == 401:
        if cfg.client_secret:
            print("client認証で弾かれた。Confidential client 前提で Basic 認証を送ったが通っていない。")
            print("  → client_id / client_secret の組が正しいか、Portal で Regenerate した後の値かを確認。")
        else:
            print("client認証で弾かれた。client_secret を送っていない。")
            print("  → Portal の Type of App が Web App / Automated App or Bot なら Confidential client。")
            print("     X_CLIENT_SECRET を設定して再実行すると、ここが原因かどうか一発で分かる。")
        return
    if err == "invalid_grant" or "code" in desc.lower():
        print("認可コードの交換に失敗。原因は次のどれか。")
        print(f"  a. コードの期限切れ（リダイレクトから交換まで {elapsed:.1f} 秒かかった）")
        print("  b. code_verifier が認可時のものと違う（PKCEの持ち回りミス。MCP側で最頻）")
        print("  c. redirect_uri が認可時と交換時で不一致")
        print("  d. コードの二重使用（1回きり。リトライで再送していないか）")
        return
    if err == "invalid_request":
        print("リクエストの形が違う。送信パラメータの欠落・重複を疑う。")
        print("  → 特に redirect_uri と code_verifier の同梱漏れ。")
        return
    if status == 403:
        print("Portal 側の権限不足の可能性が高い。App permissions が Read only のままだと tweet.write は降りない。")
        print("  → 権限を変更した場合、既存トークンは無効。認可からやり直しが要る。")
        return
    print(f"未分類のエラー。status={status} error={err!r} description={desc!r}")
    print(f"raw: {body[:500]}")


# ----------------------------------------------------------------- main flows


def run_flow(cfg: Config, timeout: int, manual: bool) -> int:
    verifier, challenge = make_pkce(cfg.challenge_method)
    state = secrets.token_urlsafe(16)
    url = build_authorize_url(cfg, challenge, state)

    print("=== 手順1: 認可URL ===")
    print("ブラウザで開いて承認する。")
    print()
    print(url)
    print()

    if manual or not is_local(cfg.redirect_uri):
        if not is_local(cfg.redirect_uri):
            print("redirect_uri が localhost ではないので自動受信できない。")
        print("承認後に飛ばされたURLを、まるごと貼り付けてEnter:")
        pasted = input("> ").strip()
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(pasted).query))
        redirect_at = time.time()
    else:
        print(f"=== 手順2: {cfg.redirect_uri} で待ち受け中（{timeout}秒）===")
        query = wait_for_callback(cfg.redirect_uri, timeout)
        redirect_at = time.time()

    if not query:
        print("[NG] コールバックが来なかった。")
        print("  → 承認画面が出なかったなら client_id か scope の問題。")
        print("  → 承認画面は出たが戻らなかったなら Callback URI の登録漏れ・不一致。")
        return 1
    if query.get("error"):
        print(f"[NG] 認可段階で拒否された: {query}")
        if query.get("error") == "path_mismatch":
            print("  → 登録した Callback のパスと実際のパスが違う。ここが完全一致の穴。")
        return 1
    if query.get("state") != state and "state" in query:
        print("[NG] state が一致しない。CSRF対策として中断する。")
        return 1

    code = query.get("code", "")
    if not code:
        print(f"[NG] code が返っていない: {query}")
        return 1
    print(f"[OK] 認可コードを取得: {mask(code, 8)}")
    print()

    print("=== 手順3: トークン交換 ===")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg.redirect_uri,
        "code_verifier": verifier,
        "client_id": cfg.client_id,
    }
    basic = (cfg.client_id, cfg.client_secret) if cfg.client_secret else None
    print(f"client認証: {'Basic (Confidential client)' if basic else 'なし (Public client)'}")
    status, payload, body = post_form(TOKEN_URL, data, basic)
    elapsed = time.time() - redirect_at
    print(f"リダイレクトから交換完了まで: {elapsed:.1f} 秒")
    print(f"HTTP {status}")

    if status != 200:
        print(f"レスポンス: {body[:800]}")
        print()
        diagnose_token_error(status, payload, body, cfg, elapsed)
        return 1

    access = payload.get("access_token", "")
    refresh = payload.get("refresh_token", "")
    print("[OK] トークン取得成功")
    print(f"  scope         : {payload.get('scope', '')}")
    print(f"  expires_in    : {payload.get('expires_in', '')} 秒")
    print(f"  access_token  : {mask(access)}")
    print(f"  refresh_token : {mask(refresh) if refresh else '(なし)'}")
    if not refresh:
        print("  [警告] Refresh Token が無い。offline.access を scope に入れて取り直す。")
    print()

    print("=== 手順4: トークンでAPIを叩く ===")
    me_status, me_body = get_json(ME_URL, access)
    print(f"GET /2/users/me -> HTTP {me_status}")
    if me_status == 200:
        print(f"  {me_body[:300]}")
    else:
        print(f"  {me_body[:500]}")
        if me_status == 403:
            print("  → scope 不足。users.read が付いているか確認。")
    print()

    if refresh:
        print("=== 手順5: リフレッシュ検証 ===")
        do_refresh(cfg, refresh)
    return 0


def do_refresh(cfg: Config, refresh_token: str) -> int:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": cfg.client_id,
    }
    basic = (cfg.client_id, cfg.client_secret) if cfg.client_secret else None
    status, payload, body = post_form(TOKEN_URL, data, basic)
    print(f"HTTP {status}")
    if status != 200:
        print(f"レスポンス: {body[:800]}")
        print("  → refresh に失敗。client認証の方式（Basic の有無）は認可時と揃える必要がある。")
        return 1
    new_refresh = payload.get("refresh_token", "")
    print("[OK] リフレッシュ成功")
    print(f"  新 access_token : {mask(payload.get('access_token', ''))}")
    print(f"  新 refresh_token: {mask(new_refresh)}")
    print()
    print("  重要: refresh_token はローテーションする。返ってきた新しい値を必ず保存し直すこと。")
    print("  古い値を使い回す実装だと、2回目の更新で必ず落ちる。MCP常駐運用の定番の死因。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="X OAuth 2.0 + PKCE 切り分けツール")
    parser.add_argument("--check-config", action="store_true", help="静的チェックのみ")
    parser.add_argument("--refresh", metavar="TOKEN", help="Refresh Token の検証のみ")
    parser.add_argument("--manual", action="store_true", help="コールバックURLを手貼りする")
    parser.add_argument("--timeout", type=int, default=180, help="コールバック待ち秒数")
    parser.add_argument("--env", default=".env", help=".env のパス")
    args = parser.parse_args()

    load_dotenv(args.env)
    cfg = Config()

    missing = cfg.missing()
    if missing:
        print(f"[NG] 未設定: {', '.join(missing)}  ({args.env} を用意する)")
        return 1

    if args.check_config:
        return check_config(cfg)
    if args.refresh:
        return do_refresh(cfg, args.refresh)

    rc = check_config(cfg)
    if rc != 0:
        print("静的チェックで NG。直してから実走する。")
        return rc
    return run_flow(cfg, args.timeout, args.manual)


if __name__ == "__main__":
    sys.exit(main())
