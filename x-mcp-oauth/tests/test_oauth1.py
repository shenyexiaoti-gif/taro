"""x_oauth1_check.py の署名・設定チェック・判定を検証する。実通信なし。

署名は X（旧 Twitter）公式ドキュメント「Creating a signature」の例で確かめる。
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import x_oauth1_check as o1  # noqa: E402

DOC_PARAMS = {
    "status": "Hello Ladies + Gentlemen, a signed OAuth request!",
    "include_entities": "true",
    "oauth_consumer_key": "xvz1evFS4wEEPTGEFPHBog",
    "oauth_nonce": "kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
    "oauth_signature_method": "HMAC-SHA1",
    "oauth_timestamp": "1318622958",
    "oauth_token": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
    "oauth_version": "1.0",
}
DOC_URL = "https://api.twitter.com/1.1/statuses/update.json"
DOC_CONSUMER_SECRET = "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw"
DOC_TOKEN_SECRET = "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE"
DOC_SIGNATURE = "hCtSmYh+iHYCEqBWrE7C7hYmtUk="

GOOD_ENV = {
    "X_API_KEY": "xvz1evFS4wEEPTGEFPHBog",
    "X_API_SECRET": DOC_CONSUMER_SECRET,
    "X_ACCESS_TOKEN": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
    "X_ACCESS_TOKEN_SECRET": DOC_TOKEN_SECRET,
}


def quiet(fn, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*args)
    return rc, buf.getvalue()


class PercentEncodeTest(unittest.TestCase):
    def test_space_and_plus(self) -> None:
        self.assertEqual(o1.percent_encode("Ladies + Gentlemen"), "Ladies%20%2B%20Gentlemen")

    def test_unreserved_kept_reserved_encoded(self) -> None:
        self.assertEqual(o1.percent_encode("a~b-c._!*"), "a~b-c._%21%2A")


class SignatureTest(unittest.TestCase):
    def test_matches_documented_example(self) -> None:
        base = o1.signature_base_string("POST", DOC_URL, DOC_PARAMS)
        sig = o1.hmac_sha1_signature(base, DOC_CONSUMER_SECRET, DOC_TOKEN_SECRET)
        self.assertEqual(sig, DOC_SIGNATURE)

    def test_base_string_starts_with_method_and_url(self) -> None:
        base = o1.signature_base_string("post", DOC_URL, DOC_PARAMS)
        self.assertTrue(base.startswith("POST&https%3A%2F%2Fapi.twitter.com%2F1.1%2Fstatuses%2Fupdate.json&"))

    def test_authorization_header_matches_documented_example(self) -> None:
        with mock.patch.dict(os.environ, GOOD_ENV, clear=True):
            cfg = o1.Config()
        header = o1.authorization_header(
            cfg,
            "POST",
            DOC_URL,
            {"status": DOC_PARAMS["status"], "include_entities": "true"},
            nonce=DOC_PARAMS["oauth_nonce"],
            timestamp=DOC_PARAMS["oauth_timestamp"],
        )
        self.assertTrue(header.startswith("OAuth "))
        self.assertIn('oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"', header)
        self.assertNotIn("status=", header)  # ボディのパラメータはヘッダに載せない


class CheckConfigTest(unittest.TestCase):
    def run_check(self, env: dict[str, str]) -> tuple[int, str]:
        with mock.patch.dict(os.environ, env, clear=True):
            return quiet(o1.check_config, o1.Config())

    def test_good_config_passes_and_masks_secrets(self) -> None:
        rc, out = self.run_check(GOOD_ENV)
        self.assertEqual(rc, 0)
        for secret in (DOC_CONSUMER_SECRET, DOC_TOKEN_SECRET, GOOD_ENV["X_ACCESS_TOKEN"]):
            self.assertNotIn(secret, out)

    def test_missing_key(self) -> None:
        env = dict(GOOD_ENV)
        del env["X_ACCESS_TOKEN_SECRET"]
        rc, out = self.run_check(env)
        self.assertEqual(rc, 1)
        self.assertIn("X_ACCESS_TOKEN_SECRET", out)

    def test_surrounding_whitespace_is_ng(self) -> None:
        rc, out = self.run_check({**GOOD_ENV, "X_API_SECRET": DOC_CONSUMER_SECRET + " "})
        self.assertEqual(rc, 1)
        self.assertIn("空白", out)

    def test_fullwidth_char_is_ng(self) -> None:
        rc, _ = self.run_check({**GOOD_ENV, "X_API_KEY": "xvz1evFS4wEEPTGEFPHBog　"})
        self.assertEqual(rc, 1)

    def test_swapped_values_are_ng(self) -> None:
        rc, out = self.run_check({**GOOD_ENV, "X_ACCESS_TOKEN": GOOD_ENV["X_API_KEY"]})
        self.assertEqual(rc, 1)
        self.assertIn("取り違え", out)

    def test_access_token_shape_warning(self) -> None:
        rc, out = self.run_check({**GOOD_ENV, "X_ACCESS_TOKEN": "AAAAAAAAAAAAAAAAAAAAAbearerlike"})
        self.assertEqual(rc, 0)
        self.assertIn("[注意]", out)


class RunTest(unittest.TestCase):
    def cfg(self) -> o1.Config:
        with mock.patch.dict(os.environ, GOOD_ENV, clear=True):
            return o1.Config()

    def test_success(self) -> None:
        body = '{"data":{"id":"123","name":"t","username":"taro"}}'
        with mock.patch.object(o1, "call_me", return_value=(200, {"x-access-level": "read-write"}, body)):
            rc, out = quiet(o1.run, self.cfg())
        self.assertEqual(rc, 0)
        self.assertIn("@taro", out)
        self.assertIn("read-write", out)

    def test_read_only_warns(self) -> None:
        body = '{"data":{"id":"123","username":"taro"}}'
        with mock.patch.object(o1, "call_me", return_value=(200, {"x-access-level": "read"}, body)):
            _, out = quiet(o1.run, self.cfg())
        self.assertIn("Read and write", out)

    def test_401_with_clock_skew(self) -> None:
        headers = {"Date": "Mon, 01 Jan 2024 00:00:00 GMT"}
        with mock.patch.object(o1, "call_me", return_value=(401, headers, '{"title":"Unauthorized"}')):
            rc, out = quiet(o1.run, self.cfg())
        self.assertEqual(rc, 1)
        self.assertIn("時計", out)

    def test_network_unreachable(self) -> None:
        with mock.patch.object(o1, "call_me", return_value=(0, {}, "Tunnel connection failed")):
            rc, out = quiet(o1.run, self.cfg())
        self.assertEqual(rc, 1)
        self.assertIn("届いていない", out)

    def test_call_me_turns_url_error_into_status_zero(self) -> None:
        err = o1.urllib.error.URLError("blocked")
        with mock.patch.object(o1.urllib.request, "urlopen", side_effect=err):
            status, headers, body = o1.call_me(self.cfg())
        self.assertEqual((status, headers, body), (0, {}, "blocked"))


if __name__ == "__main__":
    unittest.main()
