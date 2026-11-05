"""X の4つの鍵を、md（またはテキスト）ファイルから環境変数へ読み込む。標準ライブラリのみ。

クラウドのセッションには .env も環境変数も置かない運用のための入口。
Drive にある鍵の md を、セッション側（Claude）が Drive コネクタで読み、
このファイルの既定の置き場所へ保存する。サーバーはツールが呼ばれるたびに
鍵が揃っているかを見て、足りなければここから読み足す。

鍵の値は、戻り値以外のどこにも出さない（ログ・例外メッセージに含めない）。
"""

from __future__ import annotations

import os
import re

KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")

KEYS_FILE_ENV = "X_KEYS_FILE"
DEFAULT_KEYS_FILE = "~/.x_keys.md"

# 値に使う文字。Access Token は「数字-英数字」、他は英数字と一部記号
_VALUE = r"([A-Za-z0-9_\-%.~+/=]+)"
# 鍵名と値のあいだに入りうるもの（= : 全角コロン 表の縦線 強調・引用符・空白）
_SEP = r"[\s`*'\"]*[=:：|][\s`*'\"|]*"


def parse_keys_text(text: str) -> dict[str, str]:
    """md／テキストから4つの鍵を拾う。見つかったものだけを返す。

    対応する書き方の例:
        X_API_KEY=abc          X_API_KEY: abc        - X_API_KEY: `abc`
        **X_API_KEY**: abc     | X_API_KEY | abc |
    プレースホルダ（<ここに貼る> など）は値として拾わない。
    """
    found: dict[str, str] = {}
    for key in KEYS:
        # X_ACCESS_TOKEN が X_ACCESS_TOKEN_SECRET の前半に当たらないよう、直後は区切りに限る
        pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(key) + _SEP + _VALUE)
        m = pattern.search(text)
        if m:
            found[key] = m.group(1)
    return found


def keys_file_path() -> str:
    return os.path.expanduser(os.environ.get(KEYS_FILE_ENV) or DEFAULT_KEYS_FILE)


def missing_keys() -> list[str]:
    return [k for k in KEYS if not os.environ.get(k, "")]


def load_keys_file(path: str | None = None) -> list[str]:
    """環境変数に足りない鍵を、ファイルから補う。既にある値は上書きしない。

    戻り値は、この呼び出しのあとでも足りない鍵の名前（値ではない）。
    """
    if not missing_keys():
        return []
    target = path or keys_file_path()
    try:
        with open(target, encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError:
        return missing_keys()
    for key, value in parse_keys_text(text).items():
        os.environ.setdefault(key, value)
    return missing_keys()


def missing_message(missing: list[str]) -> str:
    """鍵が揃わなかったときに、ツールの結果として返す案内。値は含めない。"""
    return (
        "X の鍵が揃っていない（足りない: " + ", ".join(missing) + "）。\n"
        "Google Drive にある鍵の md を Drive コネクタで読み、"
        f"その全文を {keys_file_path()} に保存してから、もう一度このツールを呼ぶ。\n"
        "鍵の値をチャットに書き出さない。保存したら、ファイルの権限は本人だけにする。"
    )
