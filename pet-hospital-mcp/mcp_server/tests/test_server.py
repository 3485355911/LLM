"""宠物医院 MCP server 单元测试（离线，不依赖真实后端）。

运行：
    cd D:\\LLm\\pet-hospital-mcp
    python -m unittest discover -s mcp_server/tests -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_server import build_server  # noqa: E402
from mcp_server.backend import BackendError, CallLog  # noqa: E402


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"code": 0, "message": "ok", "data": None}
        self.text = text or json.dumps(self._payload, ensure_ascii=False)

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeClient:
    """按预设脚本返回响应，并记录每次请求，用来断言参数映射与重试。"""

    def __init__(self, script: list[FakeResponse]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, params=None, json=None):  # noqa: A002
        self.calls.append({"method": method, "url": url, "params": params, "json": json})
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]


def envelope(data: Any, code: int = 0, message: str = "ok") -> FakeResponse:
    return FakeResponse(200, {"code": code, "message": message, "data": data})


def text_of(result: Any) -> str:
    """兼容 SDK 的 CallToolResult / (content, structured) / 纯字符串三种返回形态。"""
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, str):
        return result
    content = getattr(result, "content", result)
    if isinstance(content, str):
        return content
    parts = []
    for item in content or []:
        parts.append(getattr(item, "text", "") or "")
    return "".join(parts)


def payload_of(result: Any) -> dict:
    raw = text_of(result)
    return json.loads(raw)


class SchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.mcp = build_server(http=FakeClient([envelope({"items": [], "total": 0})]), log_stream=None)

    async def test_ten_tools_registered_with_descriptions(self) -> None:
        tools = await self.mcp.list_tools()
        names = [t.name for t in tools]
        self.assertEqual(len(names), 10, f"工具数量应为 10，实际 {names}")
        for tool in tools:
            self.assertTrue(tool.description and len(tool.description) > 8, f"{tool.name} 缺少清晰描述")
            schema = tool.input_schema
            self.assertEqual(schema.get("type"), "object")
            for prop_name, prop in (schema.get("properties") or {}).items():
                self.assertIn("description", prop, f"{tool.name}.{prop_name} 缺少参数说明")

    async def test_constraints_are_encoded(self) -> None:
        tools = {t.name: t for t in await self.mcp.list_tools()}
        page_size = tools["list_pets"].input_schema["properties"]["page_size"]
        self.assertEqual((page_size["minimum"], page_size["maximum"]), (1, 100))

        species = tools["list_pets"].input_schema["properties"]["species"]
        branch = species.get("anyOf", [species])[0]
        self.assertIn("犬", branch["enum"])

        amount = tools["add_charge"].input_schema["properties"]["amount"]
        self.assertEqual(amount["exclusiveMinimum"] if "exclusiveMinimum" in amount else amount["minimum"], 0)


class BehaviourTests(unittest.IsolatedAsyncioTestCase):
    def make(self, script: list[FakeResponse]):
        self.log = CallLog(stream=None)
        client = FakeClient(script)
        mcp = build_server(http=client, retries=2, log_stream=None)
        # 用外部 log 观测调用：build_server 内部会自己建，改为直接断言 client.calls
        return mcp, client

    async def test_list_pets_maps_params_and_unwraps_data(self) -> None:
        mcp, client = self.make([envelope({"items": [{"petId": "PET-000001"}], "total": 1, "page": 2})])
        result = await mcp.call_tool("list_pets", {"page": 2, "page_size": 5, "species": "犬", "order": "asc"})
        body = payload_of(result)
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["total"], 1)
        call = client.calls[0]
        self.assertEqual(call["method"], "GET")
        self.assertTrue(call["url"].endswith("/api/v1/pets"))
        self.assertEqual(
            call["params"],
            {"page": 2, "pageSize": 5, "species": "犬", "order": "asc"},
            "可选参数为 None 时不应传给后端",
        )

    async def test_not_found_maps_to_structured_code(self) -> None:
        mcp, _ = self.make([FakeResponse(404, {"code": 404, "message": "宠物档案不存在", "data": None})])
        body = payload_of(await mcp.call_tool("get_pet", {"pet_id": "PET-999999"}))
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "UPSTREAM_NOT_FOUND")
        self.assertIn("不存在", body["message"])
        self.assertTrue(body["hint"])

    async def test_retry_then_success_on_5xx(self) -> None:
        script = [
            FakeResponse(503, {"code": 503, "message": "busy"}),
            FakeResponse(503, {"code": 503, "message": "busy"}),
            envelope({"total": 0, "items": []}),
        ]
        mcp, client = self.make(script)
        body = payload_of(await mcp.call_tool("list_pets", {}))
        self.assertTrue(body["ok"])
        self.assertEqual(len(client.calls), 3, "5xx 应重试 2 次后成功")

    async def test_non_json_upstream_is_rejected(self) -> None:
        mcp, _ = self.make([FakeResponse(200, Exception("not json"), text="<html>login</html>")])
        body = payload_of(await mcp.call_tool("hospital_stats", {"top": 3}))
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "BAD_UPSTREAM")

    async def test_business_error_code_from_envelope(self) -> None:
        mcp, _ = self.make([FakeResponse(400, {"code": 1002, "message": "amount 必须大于 0"})])
        body = payload_of(await mcp.call_tool("add_charge", {"pet_id": "PET-000001", "item": "血常规", "category": "检查", "amount": 1}))
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "UPSTREAM_REJECTED")
        self.assertIn("amount", body["message"])

    async def test_local_validation_before_network(self) -> None:
        mcp, client = self.make([envelope(None)])
        body = payload_of(await mcp.call_tool("find_pets_by_owner", {}))
        self.assertEqual(body["code"], "VALIDATION_ERROR")
        self.assertEqual(client.calls, [], "参数校验失败时不应发起网络请求")

    async def test_call_log_written(self) -> None:
        log = CallLog(stream=None)
        client = FakeClient([envelope({"items": []})])
        mcp = build_server(http=client, log=log)
        await mcp.call_tool("list_pets", {})
        records = [r for r in log.records if r["event"] == "tool_call"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["tool"], "list_pets")
        self.assertTrue(records[0]["ok"])
        self.assertEqual(records[0]["code"], "OK")
        self.assertIn("elapsed_ms", records[0])

    async def test_failed_call_also_logged_with_error_code(self) -> None:
        log = CallLog(stream=None)
        client = FakeClient([FakeResponse(404, {"code": 404, "message": "宠物档案不存在"})])
        mcp = build_server(http=client, log=log)
        await mcp.call_tool("get_pet", {"pet_id": "PET-999999"})
        records = [r for r in log.records if r["event"] == "tool_call"]
        self.assertEqual(records[0]["code"], "UPSTREAM_NOT_FOUND")
        self.assertFalse(records[0]["ok"])

    async def test_timeout_is_retried_and_reported(self) -> None:
        class Boom(Exception):
            pass

        calls = {"n": 0}

        class TimeoutClient(FakeClient):
            def request(self, method, url, params=None, json=None):  # noqa: A002
                calls["n"] += 1
                raise TimeoutError("read timed out")

        mcp = build_server(http=TimeoutClient([envelope(None)]), retries=1, log_stream=None)
        body = payload_of(await mcp.call_tool("hospital_stats", {"top": 3}))
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "UPSTREAM_TIMEOUT")
        self.assertEqual(calls["n"], 2, "超时应重试 retries+1 次")


if __name__ == "__main__":
    unittest.main()
