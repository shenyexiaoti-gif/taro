"""x_mcp_server.py の JSON-RPC 処理とツール本体を検証する。実通信なし。"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import x_mcp_server as srv  # noqa: E402

CFG = mock.MagicMock()


class JsonRpcTest(unittest.TestCase):
    def test_initialize_returns_protocol_and_serverinfo(self) -> None:
        r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, CFG)
        self.assertEqual(r["id"], 1)
        self.assertEqual(r["result"]["protocolVersion"], srv.PROTOCOL_VERSION)
        self.assertIn("serverInfo", r["result"])

    def test_initialized_notification_no_reply(self) -> None:
        self.assertIsNone(srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, CFG))

    def test_tools_list_has_three_tools(self) -> None:
        r = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, CFG)
        names = {t["name"] for t in r["result"]["tools"]}
        self.assertEqual(names, {"x_get_me", "x_search_recent", "x_post_tweet", "x_delete_tweet"})

    def test_unknown_method_errors(self) -> None:
        r = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"}, CFG)
        self.assertEqual(r["error"]["code"], -32601)

    def test_unknown_notification_no_reply(self) -> None:
        self.assertIsNone(srv.handle({"jsonrpc": "2.0", "method": "nope"}, CFG))

    def test_call_unknown_tool_errors(self) -> None:
        r = srv.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": "ghost", "arguments": {}}}, CFG)
        self.assertEqual(r["error"]["code"], -32602)

    def test_call_wraps_result_as_content(self) -> None:
        with mock.patch.dict(srv.DISPATCH, {"x_get_me": lambda c, a: "hi"}):
            r = srv.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                            "params": {"name": "x_get_me", "arguments": {}}}, CFG)
        self.assertEqual(r["result"]["content"][0]["text"], "hi")

    def test_call_tool_exception_is_reported_not_raised(self) -> None:
        def boom(_c, _a):
            raise RuntimeError("x")
        with mock.patch.dict(srv.DISPATCH, {"x_get_me": boom}):
            r = srv.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                            "params": {"name": "x_get_me", "arguments": {}}}, CFG)
        self.assertTrue(r["result"]["isError"])


class ToolTest(unittest.TestCase):
    def test_get_me_success(self) -> None:
        body = '{"data":{"id":"1","username":"taro"}}'
        with mock.patch.object(srv, "_request", return_value=(200, body)):
            out = srv.tool_get_me(CFG, {})
        self.assertIn("taro", out)

    def test_get_me_failure_gives_hint(self) -> None:
        with mock.patch.object(srv, "_request", return_value=(401, "{}")):
            out = srv.tool_get_me(CFG, {})
        self.assertIn("401", out)
        self.assertIn("署名", out)

    def test_post_tweet_rejects_empty(self) -> None:
        self.assertIn("空", srv.tool_post_tweet(CFG, {"text": "  "}))

    def test_post_tweet_rejects_too_long(self) -> None:
        out = srv.tool_post_tweet(CFG, {"text": "あ" * (srv.TWEET_MAX + 1)})
        self.assertIn("長い", out)
        self.assertIn("投稿しない", out)

    def test_post_tweet_success_uses_json_body_not_signed(self) -> None:
        captured = {}

        def fake_request(cfg, method, url, oauth_params, body, content_type):
            captured.update(method=method, url=url, oauth_params=oauth_params,
                            body=body, content_type=content_type)
            return 201, '{"data":{"id":"999","text":"やあ"}}'

        with mock.patch.object(srv, "_request", side_effect=fake_request):
            out = srv.tool_post_tweet(CFG, {"text": "やあ"})
        self.assertIn("999", out)
        self.assertEqual(captured["method"], "POST")
        self.assertIsNone(captured["oauth_params"])  # JSON ボディは署名に含めない
        self.assertEqual(captured["content_type"], "application/json")
        self.assertEqual(json.loads(captured["body"]), {"text": "やあ"})

    def test_search_requires_query(self) -> None:
        self.assertIn("空", srv.tool_search_recent(CFG, {"query": " "}))

    def test_delete_rejects_empty_id(self) -> None:
        self.assertIn("空", srv.tool_delete_tweet(CFG, {"id": " "}))

    def test_delete_success(self) -> None:
        with mock.patch.object(srv, "_request", return_value=(200, '{"data":{"deleted":true}}')) as m:
            out = srv.tool_delete_tweet(CFG, {"id": "999"})
        self.assertIn("deleted=True", out)
        self.assertEqual(m.call_args[0][1], "DELETE")

    def test_search_success(self) -> None:
        with mock.patch.object(srv, "_request_with_query", return_value=(200, '{"data":[]}')):
            out = srv.tool_search_recent(CFG, {"query": "python"})
        self.assertIn("data", out)


if __name__ == "__main__":
    unittest.main()
