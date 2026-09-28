"""local_env_report.py の伏字処理を検証する。

秘密の値がレポートに生で出ないか、また redirect_uri / scope のような
判定に必要な値はそのまま出るかを確認する。実通信なし。
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import local_env_report as report  # noqa: E402


class MaskTest(unittest.TestCase):
    def test_secret_value_is_not_shown_raw(self) -> None:
        secret = "sk-verysecretclientsecretvalue1234567890"
        masked = report.mask(secret)
        self.assertNotIn(secret, masked)
        self.assertIn("*", masked)

    def test_short_value_is_fully_masked(self) -> None:
        masked = report.mask("ab")
        self.assertEqual(masked, "**")
        self.assertNotIn("a", masked)

    def test_empty_value(self) -> None:
        self.assertEqual(report.mask(""), "(空)")


class ShowTest(unittest.TestCase):
    def test_secret_key_is_masked(self) -> None:
        line = report.show("X_CLIENT_SECRET", "topsecretvalue1234")
        self.assertNotIn("topsecretvalue1234", line)
        self.assertIn("*", line)

    def test_redirect_uri_is_shown_in_full(self) -> None:
        value = "http://127.0.0.1:8765/callback"
        line = report.show("X_REDIRECT_URI", value)
        self.assertIn(value, line)

    def test_scope_is_shown_in_full(self) -> None:
        value = "tweet.read tweet.write users.read offline.access"
        line = report.show("X_SCOPES", value)
        self.assertIn(value, line)

    def test_client_id_is_masked_but_marked_as_identifier(self) -> None:
        line = report.show("X_CLIENT_ID", "abcdEFGH12345678")
        self.assertNotIn("abcdEFGH12345678", line)
        self.assertIn("設定あり", line)


class CheckRedirectTest(unittest.TestCase):
    def test_trailing_slash_is_flagged(self) -> None:
        out = "\n".join(report.check_redirect("http://127.0.0.1:8765/callback/"))
        self.assertIn("末尾が /", out)

    def test_http_on_non_local_host_is_ng(self) -> None:
        out = "\n".join(report.check_redirect("http://example.com/callback"))
        self.assertIn("[NG]", out)

    def test_https_on_remote_host_is_clean(self) -> None:
        out = "\n".join(report.check_redirect("https://example.com/callback"))
        self.assertNotIn("[NG]", out)


class CheckScopeTest(unittest.TestCase):
    def test_comma_separated_scope_is_ng(self) -> None:
        out = "\n".join(report.check_scope("tweet.read,tweet.write"))
        self.assertIn("[NG]", out)
        self.assertIn("カンマ区切り", out)

    def test_missing_offline_access_is_warning(self) -> None:
        out = "\n".join(report.check_scope("tweet.read tweet.write users.read"))
        self.assertIn("offline.access", out)
        self.assertIn("[警告]", out)

    def test_space_separated_full_scope_has_no_warning_lines_beyond_header(self) -> None:
        lines = report.check_scope(
            "tweet.read tweet.write users.read offline.access"
        )
        # 1行目は scope の表示行そのもの。それ以外に警告/NG が無いことを確認する。
        self.assertEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
