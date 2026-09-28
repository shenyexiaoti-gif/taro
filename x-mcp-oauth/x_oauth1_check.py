#!/usr/bin/env python3
"""X (Twitter) API OAuth 1.0a User Context の接続確認ツール。

標準ライブラリだけで動く。MCPサーバーを経由せず、素のHTTPで
HMAC-SHA1 署名付きリクエストを1本送り、自分のアカウントが返るかを確かめる。
投稿はしない。叩くのは GET /2/users/me の1回だけ。

使い方:
    cp .env.example .env   # 1.0a の4つの値を埋める
    python3 x_oauth1_check.py --check-config   # 設定の目視ズレを検出
    python3 x_oauth1_check.py                  # users/me を1回叩く

秘密の値は伏字で表示する。標準出力をそのまま貼っても秘密は漏れない。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime

from x_oauth2_pkce_check import load_dotenv, mask

ME_URL = "https://api.x.com/2/users/me"

KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")

# Access Token は「数字のユーザーID-英数字」の形で発行される
ACCESS_TOKEN_SHAPE = re.compile(r"^\d+-[A-Za-z0-9]+$")


class Config:
    def __init__(self) -> None:
        self.api_key = os.environ.get("X_API_KEY", "")
        self.api_secret = os.environ.get("X_API_SECRET", "")
        self.access_token = os.environ.get("X_ACCESS_TOKEN", "")
        self.access_token_secret = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

    def missing(self) -> list[str]:
        return [k for k in KEYS if not os.environ.get(k, "")]


def check_config(cfg: Config) -> int:
    print("=== 静的チェック（OAuth 1.0a）===")
    missing = cfg.missing()
    if missing:
        print(f"[NG] 未設定: {', '.join(missing)}")
        return 1

    problems: list[str] = []
    warnings: list[str] = []
    for key in KEYS:
        raw = os.environ.get(key, "")
        if raw != raw.strip():
            problems.append(f"{key} の前後に空白がある。貼り付け時の混入。")
        if re.search(r"[^\x21-\x7e]", raw.strip()):
            problems.append(f"{key} に全角文字・不可視文字が混じっている。")

    if not ACCESS_TOKEN_SHAPE.match(cfg.access_token.strip()):
        warnings.append(
            "X_ACCESS_TOKEN が「数字-英数字」の形ではない。"
            "API Key や Bearer Token を取り違えて入れていないか確認する。"
        )
    if cfg.api_key.strip() == cfg.access_token.strip():
        problems.append("X_API_KEY と X_ACCESS_TOKEN が同じ値。取り違え。")
    if cfg.api_secret.strip() == cfg.access_token_secret.strip():
        problems.append("X_API_SECRET と X_ACCESS_TOKEN_SECRET が同じ値。取り違え。")

    print(f"  X_API_KEY             : {mask(cfg.api_key)}")
    print(f"  X_API_SECRET          : {mask(cfg.api_secret)}")
    print(f"  X_ACCESS_TOKEN        : {mask(cfg.access_token)}")
    print(f"  X_ACCESS_TOKEN_SECRET : {mask(cfg.access_token_secret)}")

    for w in warnings:
        print(f"[注意] {w}")
    for p in problems:
        print(f"[NG] {p}")
    if not problems:
        print("[OK] 静的チェックでは問題なし。")
    return 1 if problems else 0


# ------------------------------------------------------------ OAuth 1.0a core


def percent_encode(value: str) -> str:
    """RFC 5849 3.6 の percent-encode。英数字と - . _ ~ 以外はすべてエンコードする。"""
    return urllib.parse.quote(value, safe="~")


def signature_base_string(method: str, url: str, params: dict[str, str]) -> str:
    """RFC 5849 3.4.1 の署名ベース文字列を作る。params は oauth_* とクエリ・ボディを合わせたもの。"""
    pairs = sorted((percent_encode(k), percent_encode(v)) for k, v in params.items())
    normalized = "&".join(f"{k}={v}" for k, v in pairs)
    return "&".join([method.upper(), percent_encode(url), percent_encode(normalized)])


def hmac_sha1_signature(base_string: str, consumer_secret: str, token_secret: str) -> str:
    key = f"{percent_encode(consumer_secret)}&{percent_encode(token_secret)}"
    digest = hmac.new(key.encode("ascii"), base_string.encode("ascii"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def authorization_header(
    cfg: Config,
    method: str,
    url: str,
    extra_params: dict[str, str] | None = None,
    nonce: str | None = None,
    timestamp: str | None = None,
) -> str:
    """署名済みの Authorization ヘッダ値を返す。nonce / timestamp はテスト用に差し込める。"""
    oauth = {
        "oauth_consumer_key": cfg.api_key.strip(),
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": cfg.access_token.strip(),
        "oauth_version": "1.0",
    }
    base = signature_base_string(method, url, {**oauth, **(extra_params or {})})
    oauth["oauth_signature"] = hmac_sha1_signature(
        base, cfg.api_secret.strip(), cfg.access_token_secret.strip()
    )
    return "OAuth " + ", ".join(
        f'{percent_encode(k)}="{percent_encode(v)}"' for k, v in sorted(oauth.items())
    )


# ---------------------------------------------------------------- HTTP / 判定


def call_me(cfg: Config) -> tuple[int, dict[str, str], str]:
    header = authorization_header(cfg, "GET", ME_URL)
    req = urllib.request.Request(ME_URL, headers={"Authorization": header})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, {}, str(getattr(e, "reason", e))


def clock_skew(headers: dict[str, str]) -> float | None:
    """サーバーの Date ヘッダと手元の時計の差（秒）。取れなければ None。"""
    date = headers.get("Date") or headers.get("date")
    if not date:
        return None
    try:
        return time.time() - parsedate_to_datetime(date).timestamp()
    except (TypeError, ValueError):
        return None


def diagnose(status: int, body: str, skew: float | None) -> None:
    print("--- 判定 ---")
    if status == 0:
        print("  X まで届いていない。署名以前の問題。")
        print("  → ネット接続、社内プロキシ・ファイアウォール、セキュリティソフトの遮断を疑う")
    elif status == 401:
        print("  401 は署名が通っていない。上から順に疑う。")
        print("  → 4つの値の取り違え（API Key と Access Token、Secret 同士）")
        print("  → Portal で再発行したのに、古い値が .env に残っている")
        if skew is not None and abs(skew) > 300:
            print(f"  → 手元の時計が {skew:+.0f} 秒ずれている。時刻同期を直す（これが原因の可能性が高い）")
        else:
            print("  → 手元の時計のずれ（Windows の設定 > 時刻と言語 > 今すぐ同期）")
    elif status == 403:
        print("  403 は認証は通ったが使わせてもらえない状態。")
        print("  → App が Project に紐づいていない（v2 API は Project 配下の App が必要）")
        print("  → プラン・権限の不足。Developer Portal の表示で確認する")
    elif status == 402:
        print("  402 はクレジット・利用枠の不足。署名は通っている。")
        print("  → Developer Portal で残高と利用状況を確認する")
    elif status == 429:
        print("  429 はレート制限。署名は通っている。時間を置いて再実行する。")
    else:
        print(f"  想定外のステータス {status}。レスポンス本文を貼ってくれれば切り分ける。")


def run(cfg: Config) -> int:
    print()
    print("=== users/me を1回叩く（OAuth 1.0a 署名）===")
    status, headers, body = call_me(cfg)
    skew = clock_skew(headers)
    print(f"GET /2/users/me -> HTTP {status}")
    if skew is not None:
        print(f"手元の時計とサーバーの差: {skew:+.1f} 秒")

    if status == 200:
        try:
            data = json.loads(body).get("data", {})
        except json.JSONDecodeError:
            data = {}
        print("[OK] OAuth 1.0a で接続できた")
        print(f"  id       : {data.get('id', '')}")
        print(f"  username : @{data.get('username', '')}")
        level = headers.get("x-access-level") or headers.get("X-Access-Level")
        if level:
            print(f"  権限     : {level}")
            if level == "read":
                print("  [注意] 読み取り専用。投稿させるなら Portal の App permissions を")
                print("         Read and write にしてから Access Token を再発行する。")
        else:
            print("  権限     : 応答からは判定できない。Portal の App permissions と、")
            print("             Access Token 発行時の権限表示（Read and Write か）を目で確認する。")
        return 0

    print(f"レスポンス: {body[:800]}")
    diagnose(status, body, skew)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="X OAuth 1.0a 接続確認ツール")
    parser.add_argument("--check-config", action="store_true", help="静的チェックのみ")
    parser.add_argument("--env", default=".env", help=".env のパス")
    args = parser.parse_args()

    load_dotenv(args.env)
    cfg = Config()

    rc = check_config(cfg)
    if args.check_config or rc != 0:
        if rc != 0 and not args.check_config:
            print("静的チェックで NG。直してから実走する。")
        return rc
    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
