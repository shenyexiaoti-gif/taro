"""認可URLの組み立てを検証する。

scope がスペース区切りでエンコードされるか、redirect_uri が正しくエンコードされるかを見る。
実通信なし。
"""

from __future__ import annotations

import os
import sys
import unittest
import urllib.parse

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
    """Config は os.environ を読むので、テスト間で汚染しないよう退避・復元する。"""

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


class BuildAuthorizeUrlTest(_ConfigEnvTestCase):
    def test_scope_is_space_separated_and_percent_encoded(self) -> None:
        cfg = self.make_config(scopes="tweet.read tweet.write users.read offline.access")
        url = pkce_check.build_authorize_url(cfg, "dummy-challenge", "dummy-state")
        query = urllib.parse.urlparse(url).query
        params = dict(urllib.parse.parse_qsl(query))
        # parse_qsl はデコード済みの値を返すので、元の空白区切りがそのまま復元できるかを見る。
        self.assertEqual(params["scope"], "tweet.read tweet.write users.read offline.access")
        # クエリ文字列の生の形では、空白が %20 でエンコードされている必要がある
        # （build_authorize_url は quote_via=urllib.parse.quote を使うため、+ ではない）。
        self.assertIn("scope=tweet.read%20tweet.write%20users.read%20offline.access", query)

    def test_redirect_uri_is_percent_encoded_and_round_trips(self) -> None:
        redirect_uri = "http://127.0.0.1:8765/callback"
        cfg = self.make_config(redirect_uri=redirect_uri)
        url = pkce_check.build_authorize_url(cfg, "dummy-challenge", "dummy-state")
        query = urllib.parse.urlparse(url).query
        # コロンが生のまま残っていないこと（%3A にエンコードされていること）。
        self.assertIn("redirect_uri=http%3A%2F%2F127.0.0.1%3A8765%2Fcallback", query)
        params = dict(urllib.parse.parse_qsl(query))
        self.assertEqual(params["redirect_uri"], redirect_uri)

    def test_client_id_and_state_and_challenge_are_included(self) -> None:
        cfg = self.make_config(client_id="abc123")
        url = pkce_check.build_authorize_url(cfg, "the-challenge", "the-state")
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        self.assertEqual(params["client_id"], "abc123")
        self.assertEqual(params["state"], "the-state")
        self.assertEqual(params["code_challenge"], "the-challenge")
        self.assertEqual(params["response_type"], "code")

    def test_url_targets_authorize_endpoint(self) -> None:
        cfg = self.make_config()
        url = pkce_check.build_authorize_url(cfg, "c", "s")
        self.assertTrue(url.startswith(pkce_check.AUTHORIZE_URL + "?"))


if __name__ == "__main__":
    unittest.main()
