"""MCP Client：自实现 streamable_http JSON-RPC，避开官方 SDK 在 Windows 上的 task-group 兼容问题。

仅支持 streamable_http（POST 单端点）；stdio 暂未实现。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from core.tools.base import ToolRegistry, ToolSpec


class _MCPConnection:
    """单个 MCP Server 的连接（无状态，每次新建 session）。"""

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        self.name = name
        self.url: str = cfg["url"]
        self._tools_cache: list[dict[str, Any]] | None = None

    def _headers(self, sid: str | None = None) -> dict[str, str]:
        h = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if sid:
            h["Mcp-Session-Id"] = sid
        return h

    def _parse_response(self, resp: httpx.Response) -> dict[str, Any]:
        """从响应解析 JSON-RPC payload（兼容 application/json 和 text/event-stream）。"""
        ct = (resp.headers.get("content-type") or "").lower()
        text = resp.text
        if "text/event-stream" in ct or text.lstrip().startswith("event:") or "data:" in text[:200]:
            for line in text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            raise RuntimeError(f"SSE 流中未找到 data: 字段：{text[:200]}")
        return resp.json()

    def _rpc(self, method: str, params: dict[str, Any] | None, sid: str | None = None) -> tuple[dict[str, Any], str | None]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            payload["params"] = params
        resp = httpx.post(self.url, headers=self._headers(sid), json=payload, timeout=30)
        resp.raise_for_status()
        new_sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id") or sid
        return self._parse_response(resp), new_sid

    def _open_session(self) -> str | None:
        """initialize + initialized 通知，返回 session_id（如果服务端发了的话）。"""
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "lagent", "version": "0.1"},
        }
        _, sid = self._rpc("initialize", init_params)
        # initialized 是 notification，无 id
        try:
            httpx.post(
                self.url,
                headers=self._headers(sid),
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                timeout=15,
            )
        except Exception:
            pass
        return sid

    def list_tools(self) -> list[dict[str, Any]]:
        if self._tools_cache is not None:
            return self._tools_cache
        sid = self._open_session()
        data, _ = self._rpc("tools/list", {}, sid)
        tools = (data.get("result") or {}).get("tools") or []
        out = []
        for t in tools:
            out.append(
                {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
                }
            )
        self._tools_cache = out
        return out

    def call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        sid = self._open_session()
        data, _ = self._rpc("tools/call", {"name": tool_name, "arguments": arguments}, sid)
        if "error" in data:
            return f"MCP 错误: {data['error']}"
        result = data.get("result") or {}
        if result.get("isError"):
            content = result.get("content") or []
            return "MCP 错误: " + " | ".join(str(c.get("text", c)) for c in content)
        parts: list[str] = []
        for c in result.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
            else:
                parts.append(str(c))
        if result.get("structuredContent") is not None:
            parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
        return "\n".join(p for p in parts if p) or "(无输出)"


def build_mcp_registry(config_path: Path) -> ToolRegistry:
    """读 .mcp.json，把每个 server 的工具注册成 ToolSpec（前缀 server__tool 防冲突）。"""
    registry = ToolRegistry()
    try:
        if not config_path.is_file():
            return registry
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return registry

    servers: dict[str, Any] = data.get("mcpServers") or {}
    for server_name, cfg in servers.items():
        conn = _MCPConnection(server_name, cfg)
        try:
            tools = conn.list_tools()
        except Exception as exc:
            registry.add(
                ToolSpec(
                    f"{server_name}__unavailable",
                    f"[{server_name}] 连接失败：{exc}",
                    {"type": "object", "properties": {}},
                    lambda _exc=str(exc): f"MCP Server {server_name} 不可用：{_exc}",
                )
            )
            continue

        for t in tools:
            exposed = f"{server_name}__{t['name']}"

            def _make_handler(c: _MCPConnection, tn: str):
                def _h(**kwargs: Any) -> str:
                    return c.call(tn, kwargs)

                return _h

            registry.add(
                ToolSpec(
                    exposed,
                    f"[MCP:{server_name}] {t['description']}",
                    t["parameters"],
                    _make_handler(conn, t["name"]),
                )
            )
    return registry
