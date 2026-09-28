"""mcp_register.py の登録処理を検証する。既存の設定を壊さないことが主眼。"""

from __future__ import annotations

import glob
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mcp_register as reg  # noqa: E402


class RegisterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, ".claude.json")
        self.entry = reg.build_entry("C:/py/python.exe", ["C:/x/x_mcp_server.py", "--env", "C:/x/.env"], True)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def load(self) -> dict:
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_new_file_is_created(self) -> None:
        rc, _ = reg.register(self.path, "x-oauth1", self.entry)
        self.assertEqual(rc, 0)
        self.assertEqual(self.load()["mcpServers"]["x-oauth1"]["type"], "stdio")

    def test_existing_keys_and_deep_nesting_are_preserved(self) -> None:
        deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": [1, 2, {"j": "深い"}]}}}}}}}}}
        original = {"numStartups": 42, "projects": deep, "mcpServers": {"other": {"command": "x"}}}
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(original, fh, ensure_ascii=False)
        rc, msg = reg.register(self.path, "x-oauth1", self.entry)
        self.assertEqual(rc, 0)
        data = self.load()
        self.assertEqual(data["projects"], deep)
        self.assertEqual(data["numStartups"], 42)
        self.assertIn("other", data["mcpServers"])
        self.assertIn("x-oauth1", data["mcpServers"])
        self.assertIn("バックアップ", msg)
        self.assertEqual(len(glob.glob(self.path + ".bak-*")), 1)

    def test_existing_entry_is_overwritten(self) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"mcpServers": {"x-oauth1": {"command": "old"}}}, fh)
        rc, msg = reg.register(self.path, "x-oauth1", self.entry)
        self.assertEqual(rc, 0)
        self.assertIn("上書き", msg)
        self.assertEqual(self.load()["mcpServers"]["x-oauth1"]["command"], "C:/py/python.exe")

    def test_broken_json_is_left_untouched(self) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ broken")
        rc, msg = reg.register(self.path, "x-oauth1", self.entry)
        self.assertEqual(rc, 1)
        self.assertIn("中止", msg)
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{ broken")

    def test_bom_file_is_read(self) -> None:
        with open(self.path, "w", encoding="utf-8-sig") as fh:
            json.dump({"x": 1}, fh)
        rc, _ = reg.register(self.path, "x-oauth1", self.entry)
        self.assertEqual(rc, 0)
        self.assertEqual(self.load()["x"], 1)

    def test_desktop_entry_has_no_type(self) -> None:
        entry = reg.build_entry("py", ["s.py"], False)
        self.assertNotIn("type", entry)


class MainArgsTest(unittest.TestCase):
    def test_arg_values_starting_with_dashes_are_accepted(self) -> None:
        # setup_mcp.ps1 と同じ渡し方。--env をサーバーへの引数として受け取れること
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".claude.json")
            argv = ["mcp_register.py", "--config", path, "--command", "C:/py/python.exe",
                    "--arg=C:/x/x_mcp_server.py", "--arg=--env", "--arg=C:/x/.env", "--code"]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                rc = reg.main()
            self.assertEqual(rc, 0)
            with open(path, encoding="utf-8") as fh:
                entry = json.load(fh)["mcpServers"]["x-oauth1"]
            self.assertEqual(entry["args"], ["C:/x/x_mcp_server.py", "--env", "C:/x/.env"])


if __name__ == "__main__":
    unittest.main()
