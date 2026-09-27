"""PKCE の code_verifier / code_challenge を検証する。

実通信なし。標準ライブラリの unittest のみを使う。
"""

from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import x_oauth2_pkce_check as pkce_check  # noqa: E402

# RFC 7636 Appendix B の例。
# https://www.rfc-editor.org/rfc/rfc7636 の S256 の例と一致するかを確認する。
RFC7636_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC7636_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

# unreserved characters（RFC 3986）。code_verifier はこの文字集合に収まる必要がある。
UNRESERVED_RE = re.compile(r"^[A-Za-z0-9\-._~]+$")


class ChallengeFromVerifierTest(unittest.TestCase):
    def test_matches_rfc7636_appendix_b_vector(self) -> None:
        challenge = pkce_check.challenge_from_verifier(RFC7636_VERIFIER, "S256")
        self.assertEqual(challenge, RFC7636_CHALLENGE)

    def test_plain_method_returns_verifier_as_is(self) -> None:
        challenge = pkce_check.challenge_from_verifier(RFC7636_VERIFIER, "plain")
        self.assertEqual(challenge, RFC7636_VERIFIER)

    def test_challenge_has_no_padding(self) -> None:
        challenge = pkce_check.challenge_from_verifier(RFC7636_VERIFIER, "S256")
        self.assertNotIn("=", challenge)


class MakePkceTest(unittest.TestCase):
    def test_verifier_length_is_in_rfc7636_range(self) -> None:
        # RFC 7636: code_verifier は 43〜128 文字。
        verifier, _ = pkce_check.make_pkce("S256")
        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)

    def test_verifier_uses_unreserved_charset(self) -> None:
        verifier, _ = pkce_check.make_pkce("S256")
        self.assertRegex(verifier, UNRESERVED_RE)

    def test_verifier_has_no_padding(self) -> None:
        verifier, _ = pkce_check.make_pkce("S256")
        self.assertNotIn("=", verifier)

    def test_s256_challenge_is_consistent_with_verifier(self) -> None:
        verifier, challenge = pkce_check.make_pkce("S256")
        self.assertEqual(challenge, pkce_check.challenge_from_verifier(verifier, "S256"))

    def test_two_calls_produce_different_verifiers(self) -> None:
        verifier_a, _ = pkce_check.make_pkce("S256")
        verifier_b, _ = pkce_check.make_pkce("S256")
        self.assertNotEqual(verifier_a, verifier_b)


if __name__ == "__main__":
    unittest.main()
