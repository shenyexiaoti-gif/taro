"""x_keys_file.py（md から鍵を読む処理）と、サーバーへの組み込みを検証する。実通信なし。

鍵の値はすべてテスト用のダミー。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import x_keys_file as kf  # noqa: E402
import x_mcp_server as srv  # noqa: E402
from x_oauth1_check import Config  # noqa: E402

DUMMY = {
    "X_API_KEY": "dummyApiKey123",
    "X_API_SECRET": "dummyApiSecret456",
    "X_ACCESS_TOKEN": "1111111111-dummyAccessToken789",
    "X_ACCESS_TOKEN_SECRET": "dummyAccessSecret000",
}


def _write(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".md")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class ParseTest(unittest.TestCase):
    def test_env_style_lines(self) -> None:
        text = "\n".join(f"{k}={v}" for k, v in DUMMY.items())
        self.assertEqual(kf.parse_keys_text(text), DUMMY)

    def test_colon_bullets_and_backticks(self) -> None:
        text = "\n".join(f"- {k}: `{v}`" for k, v in DUMMY.items())
        self.assertEqual(kf.parse_keys_text(text), DUMMY)

    def test_bold_and_fullwidth_colon(self) -> None:
        text = "\n".join(f"**{k}**：{v}" for k, v in DUMMY.items())
        self.assertEqual(kf.parse_keys_text(text), DUMMY)

    def test_markdown_table(self) -> None:
        text = "| 名前 | 値 |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in DUMMY.items())
        self.assertEqual(kf.parse_keys_text(text), DUMMY)

    def test_code_fence(self) -> None:
        body = "\n".join(f"{k}={v}" for k, v in DUMMY.items())
        self.assertEqual(kf.parse_keys_text(f"# X の鍵\n\n```\n{body}\n```\n"), DUMMY)

    def test_access_token_is_not_confused_with_its_secret(self) -> None:
        got = kf.parse_keys_text("X_ACCESS_TOKEN_SECRET=onlySecret\n")
        self.assertEqual(got, {"X_ACCESS_TOKEN_SECRET": "onlySecret"})

    def test_placeholder_is_not_taken_as_value(self) -> None:
        self.assertEqual(kf.parse_keys_text("X_API_KEY: <ここに貼る>\n"), {})

    def test_missing_keys_are_simply_absent(self) -> None:
        self.assertEqual(kf.parse_keys_text("X_API_KEY=a\n"), {"X_API_KEY": "a"})


class LoadTest(unittest.TestCase):
    def test_load_fills_env_from_file(self) -> None:
        path = _write("\n".join(f"{k}={v}" for k, v in DUMMY.items()))
        try:
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(kf.load_keys_file(path), [])
                self.assertEqual(os.environ["X_API_KEY"], DUMMY["X_API_KEY"])
        finally:
            os.remove(path)

    def test_existing_env_is_not_overwritten(self) -> None:
        path = _write("X_API_KEY=fromFile\n")
        try:
            with mock.patch.dict(os.environ, {"X_API_KEY": "fromEnv"}, clear=True):
                kf.load_keys_file(path)
                self.assertEqual(os.environ["X_API_KEY"], "fromEnv")
        finally:
            os.remove(path)

    def test_missing_file_returns_all_missing(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(kf.load_keys_file("/no/such/file.md"), list(kf.KEYS))

    def test_default_path_follows_env_var(self) -> None:
        with mock.patch.dict(os.environ, {kf.KEYS_FILE_ENV: "/tmp/x.md"}, clear=True):
            self.assertTrue(kf.keys_file_path().replace("\\", "/").endswith("/tmp/x.md"))

    def test_message_never_contains_values(self) -> None:
        msg = kf.missing_message(["X_API_KEY"])
        for v in DUMMY.values():
            self.assertNotIn(v, msg)


class ServerIntegrationTest(unittest.TestCase):
    def _call(self, cfg: Config) -> dict:
        msg = {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
               "params": {"name": "x_get_me", "arguments": {}}}
        return srv.handle(msg, cfg)

    def test_tool_call_without_keys_returns_guidance_not_a_signed_request(self) -> None:
        with mock.patch.dict(os.environ, {kf.KEYS_FILE_ENV: "/no/such/file.md"}, clear=True):
            cfg = Config()
            with mock.patch.object(srv, "_request") as req:
                r = self._call(cfg)
            req.assert_not_called()
        self.assertTrue(r["result"]["isError"])
        self.assertIn("Drive", r["result"]["content"][0]["text"])

    def test_tool_call_loads_keys_from_file_and_proceeds(self) -> None:
        path = _write("\n".join(f"{k}={v}" for k, v in DUMMY.items()))
        try:
            with mock.patch.dict(os.environ, {kf.KEYS_FILE_ENV: path}, clear=True):
                cfg = Config()
                self.assertEqual(cfg.api_key, "")
                with mock.patch.object(srv, "_request", return_value=(200, '{"data":{"id":"1","name":"n","username":"u"}}')):
                    r = self._call(cfg)
                self.assertEqual(cfg.api_key, DUMMY["X_API_KEY"])
                self.assertEqual(cfg.access_token_secret, DUMMY["X_ACCESS_TOKEN_SECRET"])
        finally:
            os.remove(path)
        self.assertNotIn("isError", r["result"])


class MainSelftestTest(unittest.TestCase):
    def test_selftest_reads_keys_file_when_env_is_empty(self) -> None:
        path = _write(chr(10).join(f"{k}={v}" for k, v in DUMMY.items()))
        argv = ["x_mcp_server.py", "--selftest", "--env", "/no/such/.env"]
        try:
            with mock.patch.dict(os.environ, {kf.KEYS_FILE_ENV: path}, clear=True):
                with mock.patch.object(sys, "argv", argv):
                    with mock.patch.object(srv, "tool_get_me", return_value="ok") as me:
                        code = srv.main()
        finally:
            os.remove(path)
        self.assertEqual(code, 0)
        me.assert_called_once()


if __name__ == "__main__":
    unittest.main()
