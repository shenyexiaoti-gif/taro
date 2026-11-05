"""send_draft.py の変換と送信の流れを検証する。実通信なし。"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import send_draft as sd  # noqa: E402

SAMPLE = """# 残業ゼロは30点の叩き台から

冒頭の一文である。
2行目も段落になる。

## 見出し2
- 箇条その1
- 箇条その2
1. 手順その1
2. 手順その2
> 引用の一文
**太字**は外す


（ここからコード）
print("hi")
（ここまでコード）

手入力が必要な箇所：コード1箇所
- 丸カッコのマーカーが残っていないか
"""


class ParseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.a = sd.parse_article(SAMPLE)

    def test_title_from_first_line_without_hash(self) -> None:
        self.assertEqual(self.a["title"], "残業ゼロは30点の叩き台から")

    def test_block_types(self) -> None:
        kinds = [(b["type"], b["text"]) for b in self.a["blocks"] if b["text"]]
        self.assertIn(("unstyled", "冒頭の一文である。"), kinds)
        self.assertIn(("header-two", "見出し2"), kinds)
        self.assertIn(("unordered-list-item", "箇条その1"), kinds)
        self.assertIn(("ordered-list-item", "手順その2"), kinds)
        self.assertIn(("blockquote", "引用の一文"), kinds)

    def test_each_line_is_its_own_block(self) -> None:
        texts = [b["text"] for b in self.a["blocks"]]
        self.assertIn("2行目も段落になる。", texts)

    def test_bold_marks_removed(self) -> None:
        self.assertIn("太字は外す", [b["text"] for b in self.a["blocks"]])

    def test_trailer_is_cut(self) -> None:
        texts = " ".join(b["text"] for b in self.a["blocks"])
        self.assertNotIn("手入力", texts)
        self.assertNotIn("マーカーが残っていないか", texts)
        self.assertTrue(any("本文ではない" in w for w in self.a["warnings"]))

    def test_blank_runs_collapse_to_one(self) -> None:
        blocks = self.a["blocks"]
        for x, y in zip(blocks, blocks[1:]):
            self.assertFalse(x["text"] == "" and y["text"] == "")
        self.assertNotEqual(blocks[0]["text"], "")
        self.assertNotEqual(blocks[-1]["text"], "")

    def test_marker_warning(self) -> None:
        self.assertTrue(any("マーカーが2箇所" in w for w in self.a["warnings"]))

    def test_blocks_have_only_text_and_type(self) -> None:
        for b in self.a["blocks"] + self.a["plain_blocks"]:
            self.assertEqual(set(b), {"text", "type"})

    def test_plain_blocks_keep_original_line(self) -> None:
        self.assertIn("- 箇条その1", [b["text"] for b in self.a["plain_blocks"]])
        self.assertTrue(all(b["type"] == "unstyled" for b in self.a["plain_blocks"]))

    def test_title_prefix_and_explicit_title(self) -> None:
        self.assertEqual(sd.parse_article("タイトル：題\n本文")["title"], "題")
        a = sd.parse_article("本文1\n本文2", title="別題")
        self.assertEqual(a["title"], "別題")
        self.assertEqual(a["blocks"][0]["text"], "本文1")

    def test_drop_blank(self) -> None:
        a = sd.parse_article("題\n一\n\n二", keep_blank=False)
        self.assertEqual([b["text"] for b in a["blocks"]], ["一", "二"])

    def test_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            sd.parse_article("\n\n")
        with self.assertRaises(ValueError):
            sd.parse_article("題だけ\n\n")

    def test_numbers_in_sentence_are_not_list(self) -> None:
        a = sd.parse_article("題\n1.5倍になった\n3、4人で回す")
        self.assertEqual([b["type"] for b in a["blocks"]], ["unstyled", "unstyled"])

    def test_crlf(self) -> None:
        a = sd.parse_article("題\r\n一\r\n二")
        self.assertEqual([b["text"] for b in a["blocks"]], ["一", "二"])


class SendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.article = sd.parse_article(SAMPLE)
        self.cfg = mock.MagicMock()

    def test_success(self) -> None:
        with mock.patch.object(sd, "_request", return_value=(201, '{"data":{"id":"d1"}}')) as m, \
             mock.patch("builtins.print"):
            self.assertEqual(sd.send(self.cfg, self.article), 0)
        sent = json.loads(m.call_args[0][4])
        self.assertEqual(sent["title"], self.article["title"])
        self.assertEqual(m.call_args[0][2], sd.ARTICLES_DRAFT_URL)

    def test_type_rejected_falls_back_to_plain(self) -> None:
        err = '{"errors":[{"message":"$.content_state.blocks[2].type: does not have a value in the enumeration"}]}'
        responses = [(400, err), (201, '{"data":{"id":"d2"}}')]
        with mock.patch.object(sd, "_request", side_effect=responses) as m, \
             mock.patch("builtins.print"):
            self.assertEqual(sd.send(self.cfg, self.article), 0)
        second = json.loads(m.call_args_list[1][0][4])
        self.assertTrue(all(b["type"] == "unstyled" for b in second["content_state"]["blocks"]))

    def test_other_400_is_reported_without_retry(self) -> None:
        with mock.patch.object(sd, "_request", return_value=(400, '{"errors":[{"message":"title too long"}]}')) as m, \
             mock.patch("builtins.print"):
            self.assertEqual(sd.send(self.cfg, self.article), 1)
        self.assertEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main()
