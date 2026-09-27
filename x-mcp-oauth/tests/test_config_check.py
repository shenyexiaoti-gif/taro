"""設定チェック（末尾スラッシュ、http/https、カンマ区切り scope）を検証する。

check_config は標準出力に人間向けの文言を書くだけの関数なので、
出力を捕捉した上で返り値（0=問題なし, 1=NG あり）と代表的な文言を確認する。
実通信なし。
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import x_oauth2_pkce_check as pkce_check  # noqa: E402

X_ENV_KEYS = (
    "X_CLIENT_ID",
    "X_CLIENT_SECRET",
    "X_REDIRECT_URI",
    "X_SCOPES",
    "X_CODE_CHALLENGE_METHOD",
)


class _ConfigEnvTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in X_ENV_KEYS}
        for k in X_ENV_KEYS:
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def make_config(self, **overrides: str) -> pkce_check.Config:
        os.environ["X_CLIENT_ID"] = overrides.get("client_id", "test-client-id")
        os.environ["X_REDIRECT_URI"] = overrides.get(
            "redirect_uri", "http://127.0.0.1:8765/callback"
        )
        os.environ["X_SCOPES"] = overrides.get(
            "scopes", "tweet.read tweet.write users.read offline.access"
        )
        if "client_secret" in overrides:
            os.environ["X_CLIENT_SECRET"] = overrides["client_secret"]
        if "challenge_method" in overrides:
            os.environ["X_CODE_CHALLENGE_METHOD"] = overrides["challenge_method"]
        return pkce_check.Config()

    def run_check_config(self, cfg: pkce_check.Config) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = pkce_check.check_config(cfg)
        return rc, buf.getvalue()


class ConfigMissingTest(_ConfigEnvTestCase):
    def test_missing_client_id_and_redirect_uri(self) -> None:
        cfg = pkce_check.Config()
        self.assertEqual(sorted(cfg.missing()), ["X_CLIENT_ID", "X_REDIRECT_URI"])

    def test_nothing_missing_when_both_set(self) -> None:
        cfg = self.make_config()
        self.assertEqual(cfg.missing(), [])


class CheckConfigTest(_ConfigEnvTestCase):
    def test_valid_config_has_no_ng(self) -> None:
        cfg = self.make_config()
        rc, output = self.run_check_config(cfg)
        self.assertEqual(rc, 0)
        self.assertNotIn("[NG]", output)

    def test_trailing_slash_is_warning_only(self) -> None:
        cfg = self.make_config(redirect_uri="http://127.0.0.1:8765/callback/")
        rc, output = self.run_check_config(cfg)
        self.assertEqual(rc, 0)
        self.assertIn("[警告]", output)
        self.assertIn("/ で終わっている", output)

    def test_http_on_non_local_host_is_ng(self) -> None:
        cfg = self.make_config(redirect_uri="http://example.com/callback")
        rc, output = self.run_check_config(cfg)
        self.assertEqual(rc, 1)
        self.assertIn("[NG]", output)

    def test_comma_separated_scope_is_ng(self) -> None:
        cfg = self.make_config(scopes="tweet.read,tweet.write,users.read")
        rc, output = self.run_check_config(cfg)
        self.assertEqual(rc, 1)
        self.assertIn("カンマ", output)

    def test_missing_offline_access_is_warning(self) -> None:
        cfg = self.make_config(scopes="tweet.read tweet.write users.read")
        rc, output = self.run_check_config(cfg)
        self.assertEqual(rc, 0)
        self.assertIn("offline.access", output)
        self.assertIn("[警告]", output)


if __name__ == "__main__":
    unittest.main()
