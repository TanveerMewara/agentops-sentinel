import io
import json
import unittest
from uuid import uuid4
from sentinel.client import SentinelError
from sentinel.mcp_stdio import MCPBridge, MAX_MESSAGE_BYTES, PROTOCOL_VERSION, serve


def request(method, params=None, request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


INITIALIZE = request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "1"}})


class Client:
    def __init__(self):
        self.calls = []
        self.fail = False

    def identity(self):
        self.calls.append("identity")
        if self.fail:
            raise SentinelError(401)
        return {"role": "reviewer", "organization_id": "fixture"}

    def request(self, path):
        self.calls.append(path)
        if self.fail:
            raise SentinelError(401)
        return [{"run_id": "fixture", "status": "succeeded"}]

    def timeline(self, run_id):
        self.calls.append(run_id)
        if self.fail:
            raise SentinelError(404)
        return {"run": {"run_id": run_id}, "timeline": [], "metrics": {"model_calls": 0}}


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.bridge = MCPBridge(self.client)

    def ready(self):
        response = self.bridge.handle(INITIALIZE)
        self.assertEqual(response["result"]["protocolVersion"], PROTOCOL_VERSION)
        self.assertIsNone(self.bridge.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_lifecycle_and_declared_read_only_capabilities(self):
        self.assertEqual(self.bridge.handle(request("tools/list"))["error"]["code"], -32000)
        self.assertEqual(self.bridge.handle(request("ping"))["result"], {})
        self.ready()
        tools = self.bridge.handle(request("tools/list"))["result"]["tools"]
        self.assertEqual(len(tools), 3)
        self.assertTrue(all(item["annotations"]["readOnlyHint"] for item in tools))
        self.assertEqual(self.bridge.handle(INITIALIZE)["error"]["code"], -32602)

    def test_invalid_arguments_and_unknown_tools_never_reach_api(self):
        self.ready()
        calls = len(self.client.calls)
        for name, arguments in (("approve", {}), ("sentinel_list_runs", {"limit": 101}),
                                ("sentinel_list_runs", {"limit": True}),
                                ("sentinel_identity", {"secret": "private"}),
                                ("sentinel_run_timeline", {"run_id": "../../access/keys"})):
            result = self.bridge.handle(request("tools/call", {"name": name, "arguments": arguments}))
            self.assertEqual(result["error"]["code"], -32602)
            self.assertNotIn("private", json.dumps(result))
        self.assertEqual(len(self.client.calls), calls)

    def test_data_calls_are_fresh_and_revocation_is_not_cached(self):
        self.ready()
        self.assertFalse(self.bridge.handle(request("tools/call", {"name": "sentinel_identity"}))["result"]["isError"])
        self.client.fail = True
        response = self.bridge.handle(request("tools/call", {"name": "sentinel_identity"}))
        self.assertTrue(response["result"]["isError"])
        self.assertIn("401", response["result"]["content"][0]["text"])
        self.assertEqual(self.client.calls.count("identity"), 3)

    def test_results_preserve_structure_and_use_validated_paths(self):
        self.ready()
        listed = self.bridge.handle(request("tools/call", {"name": "sentinel_list_runs", "arguments": {"limit": 5}}))["result"]
        self.assertEqual(json.loads(listed["content"][0]["text"]), listed["structuredContent"])
        self.assertEqual(self.client.calls[-1], "/v1/run-summaries?limit=5")
        run_id = str(uuid4())
        self.bridge.handle(request("tools/call", {"name": "sentinel_run_timeline", "arguments": {"run_id": run_id}}))
        self.assertEqual(self.client.calls[-1], run_id)

    def test_notifications_have_no_response_or_side_effects(self):
        self.ready()
        count = len(self.client.calls)
        self.assertIsNone(self.bridge.handle({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "sentinel_identity"}}))
        self.assertEqual(len(self.client.calls), count)
        self.assertEqual(self.bridge.handle([])["error"]["code"], -32600)
        self.assertEqual(self.bridge.handle(request("ping", request_id=True))["error"]["code"], -32600)

    def test_stream_parse_errors_and_size_limits_are_value_free(self):
        output = io.BytesIO()
        self.assertEqual(serve(self.bridge, io.BytesIO(b'private-invalid-json\n' + json.dumps(request("ping")).encode() + b'\n'), output), 0)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertNotIn("private", output.getvalue().decode())
        self.assertEqual(responses[1]["result"], {})
        output = io.BytesIO()
        self.assertEqual(serve(self.bridge, io.BytesIO(b"x" * (MAX_MESSAGE_BYTES + 1)), output), 1)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], -32600)
