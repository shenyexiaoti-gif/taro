#!/usr/bin/env python3
"""check_hook.sh の Windows 版。jq も bash も要らず、Python だけで動く。

Claude Code の PostToolUse フック（matcher: Write|Edit）として登録する。
outputs/x_articles/ 直下の .md が保存された瞬間に
post_article.py <記事> --check を走らせ、指摘があれば Claude Code に差し戻す。

置き場所: skills/x_article_workflow/check_hook.py（post_article.py と同じフォルダ）

終了コードの意味（Claude Code の約束事）
  0 … 何もしない（対象外のファイル、または指摘なし）
  2 … 指摘あり。stderr の中身が Claude Code に返り、その場で直させる
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # skills/x_article_workflow
POST_ARTICLE = HERE / "post_article.py"
WORKSPACE = HERE.parent.parent                    # claude-code
TARGET_DIR = WORKSPACE / "outputs" / "x_articles"
TIMEOUT_SEC = 120


def say(msg: str) -> None:
    # Windows の既定コードページで日本語が化けないよう、UTF-8 で直接書く
    sys.stderr.buffer.write((msg.rstrip() + "\n").encode("utf-8", "replace"))
    sys.stderr.flush()


def edited_path(payload: dict) -> Path | None:
    tool_input = payload.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("path")
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        base = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or WORKSPACE
        p = Path(base) / p
    return p.resolve()


def is_article(p: Path) -> bool:
    # outputs/x_articles/*.md だけが対象。_factcheck/ の主張台帳などサブフォルダは見ない
    return p.suffix.lower() == ".md" and p.parent == TARGET_DIR.resolve()


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        return 0

    p = edited_path(payload)
    if p is None or not is_article(p):
        return 0

    if not POST_ARTICLE.exists():
        # 本体が無いときに執筆まで止めると困るので、警告だけ出して通す
        say(f"[check_hook] post_article.py が見つからないので --check を飛ばした: {POST_ARTICLE}")
        return 0

    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run(
            [sys.executable, str(POST_ARTICLE), str(p), "--check"],
            cwd=str(WORKSPACE),
            env=env,
            capture_output=True,
            timeout=TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        say(f"[check_hook] --check が {TIMEOUT_SEC} 秒で終わらなかった: {p.name}")
        return 2

    out = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    if r.returncode != 0:
        say(f"[check_hook] {p.name} の --check で指摘あり（終了コード {r.returncode}）。直してから次へ進むこと。")
        if out:
            say(out)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
