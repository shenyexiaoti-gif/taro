#!/usr/bin/env python3
"""書き上げた X 記事を、X の記事の下書きに送る。標準ライブラリのみ。

x-article-mobile スキルの出力（見出し・箇条書き・番号付きリスト・引用はそのまま、
コードと表は全角の丸カッコのマーカー）を、そのままファイルかクリップボードから受け取る。

    py -3 send_draft.py 記事.txt                  # ファイルから
    py -3 send_draft.py --clipboard               # ブラウザでコピーした本文から
    py -3 send_draft.py 記事.txt --title "題名"   # タイトルを別に指定
    py -3 send_draft.py 記事.txt --dry-run        # 送らず、変換結果だけ見る

タイトルは --title が無ければ、本文の最初の行（「# 」や「タイトル：」は外す）を使う。
1行が1ブロックになる。X の記事エディタで Enter を押したのと同じ区切り方。
公開はしない。下書きに入れるだけ。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from x_mcp_server import ARTICLES_DRAFT_URL, _request, x_error_lines
from x_oauth1_check import Config, load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))

# スキル出力の末尾に付く「手入力の件数」と「公開前チェック」は本文ではないので切り落とす
TRAILER = re.compile(r"^(手入力が必要|手入力|公開前チェック)")
MARKER = re.compile(r"（(ここからコード|ここまでコード|表プロンプト)）")
TITLE_PREFIX = re.compile(r"^(#\s+|タイトル\s*[：:]\s*)")

LINE_TYPES = [
    (re.compile(r"^#\s+(.*)$"), "header-one"),
    (re.compile(r"^#{2,6}\s+(.*)$"), "header-two"),
    (re.compile(r"^[-*・]\s+(.*)$"), "unordered-list-item"),
    # 「1.5倍」「3、4人」を番号付きにしないよう、番号の後ろに空白があるときだけ
    (re.compile(r"^\d+[.．)]\s+(.*)$"), "ordered-list-item"),
    (re.compile(r"^>\s?(.*)$"), "blockquote"),
]


def classify(line: str) -> tuple[str, str]:
    """1行を (ブロック種別, 表示テキスト) にする。"""
    for pattern, kind in LINE_TYPES:
        m = pattern.match(line)
        if m:
            return kind, m.group(1).strip()
    return "unstyled", line


def parse_article(text: str, title: str | None = None, keep_blank: bool = True) -> dict:
    """本文を title / blocks / plain_blocks / warnings に分ける。

    plain_blocks は全ブロックを unstyled にした控え。X が見出しや箇条書きの種別を
    受け付けなかったときに、こちらで送り直す。
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [ln.rstrip() for ln in lines]
    warnings: list[str] = []

    # 末尾の件数・チェック欄を落とす
    for i, ln in enumerate(lines):
        if TRAILER.match(ln.strip()):
            warnings.append(f"{i + 1}行目以降（{ln.strip()[:20]}…）は本文ではないので送らない")
            lines = lines[:i]
            break

    # 太字記号は発信ルール上使わないので外す
    lines = [ln.replace("**", "") for ln in lines]

    if title is None:
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines:
            raise ValueError("本文が空")
        title = TITLE_PREFIX.sub("", lines.pop(0).strip())
    title = title.strip()
    if not title:
        raise ValueError("タイトルが空")

    # 前後の空行を落とし、連続する空行は1つにまとめる
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    blocks: list[dict] = []
    plain: list[dict] = []
    prev_blank = False
    for ln in lines:
        if not ln.strip():
            if keep_blank and not prev_blank:
                blocks.append({"text": "", "type": "unstyled"})
                plain.append({"text": "", "type": "unstyled"})
            prev_blank = True
            continue
        prev_blank = False
        kind, shown = classify(ln.strip())
        blocks.append({"text": shown, "type": kind})
        plain.append({"text": ln.strip(), "type": "unstyled"})
    if not blocks:
        raise ValueError("本文が空")

    markers = sum(len(MARKER.findall(b["text"])) for b in blocks)
    if markers:
        warnings.append(f"丸カッコのマーカーが{markers}箇所ある。コードと表は下書きを開いて手で入れる")
    return {"title": title, "blocks": blocks, "plain_blocks": plain, "warnings": warnings}


def read_clipboard() -> str:
    try:
        import tkinter
    except ImportError as e:  # pragma: no cover - 環境依存
        raise RuntimeError("クリップボードを読めない（tkinter が無い）。ファイルで渡す") from e
    root = tkinter.Tk()
    root.withdraw()
    try:
        return root.clipboard_get()
    finally:
        root.destroy()


def post_draft(cfg: Config, title: str, blocks: list[dict]) -> tuple[int, str]:
    payload = {"title": title, "content_state": {"blocks": blocks, "entities": []}}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return _request(cfg, "POST", ARTICLES_DRAFT_URL, None, body, "application/json")


def send(cfg: Config, article: dict) -> int:
    status, resp = post_draft(cfg, article["title"], article["blocks"])
    used_plain = False
    rich = any(b["type"] != "unstyled" for b in article["blocks"])
    if status == 400 and rich and any("type" in m for m in x_error_lines(resp)):
        # 見出しや箇条書きの種別を X が受け付けなかった。全部ふつうの段落で送り直す
        print("[..] X が見出し・箇条書きの種別を受け付けなかった。ふつうの段落で送り直す")
        for m in x_error_lines(resp):
            print(f"     - {m}")
        status, resp = post_draft(cfg, article["title"], article["plain_blocks"])
        used_plain = True

    if status in (200, 201):
        draft_id = json.loads(resp).get("data", {}).get("id", "")
        print(f"[OK] 下書きに入れた。id={draft_id}")
        print(f"     タイトル: {article['title']}")
        print(f"     ブロック: {len(article['blocks'])}")
        if used_plain:
            print("     見出し・箇条書きは段落として入った。下書きを開いて書式を付け直す")
        return 0

    print(f"[NG] HTTP {status}。X の指摘:")
    for m in x_error_lines(resp):
        print(f"     - {m}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="X 記事を下書きに送る")
    parser.add_argument("file", nargs="?", help="記事のテキストファイル（UTF-8）")
    parser.add_argument("--clipboard", action="store_true", help="クリップボードの本文を使う")
    parser.add_argument("--title", help="タイトル（省略時は本文の1行目）")
    parser.add_argument("--drop-blank", action="store_true", help="空行を送らない")
    parser.add_argument("--dry-run", action="store_true", help="送らず、変換結果だけ表示する")
    parser.add_argument("--env", default=os.path.join(HERE, ".env"), help=".env のパス")
    args = parser.parse_args()

    if args.clipboard:
        text = read_clipboard()
    elif args.file:
        with open(args.file, encoding="utf-8-sig") as fh:
            text = fh.read()
    else:
        parser.error("ファイルを指定するか --clipboard を付ける")

    try:
        article = parse_article(text, args.title, keep_blank=not args.drop_blank)
    except ValueError as e:
        print(f"[NG] {e}")
        return 1

    for w in article["warnings"]:
        print(f"[注意] {w}")

    if args.dry_run:
        print(f"タイトル: {article['title']}")
        for b in article["blocks"]:
            print(f"  [{b['type']}] {b['text']}")
        print("[..] --dry-run のため送らない")
        return 0

    load_dotenv(args.env)
    cfg = Config()
    missing = cfg.missing()
    if missing:
        print(f"[NG] .env に値が足りない: {', '.join(missing)}")
        return 1
    return send(cfg, article)


if __name__ == "__main__":
    sys.exit(main())
