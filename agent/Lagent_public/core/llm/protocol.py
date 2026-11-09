"""SSE 协议解析与流式工具调用聚合。"""

from __future__ import annotations

import json
from typing import AsyncIterator


async def iter_sse_payloads(lines: AsyncIterator[str]) -> AsyncIterator[dict]:
    """从 SSE 行流中产出增量 JSON。"""
    async for line in lines:
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue


class ToolCallAccumulator:
    """把分散在多个 delta 中的工具调用片段拼装成完整调用。"""

    def __init__(self) -> None:
        self._calls: dict[int, dict] = {}

    def add(self, chunk: dict) -> None:
        index = chunk.get("index", 0)
        call = self._calls.setdefault(
            index,
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        if chunk.get("id"):
            call["id"] = chunk["id"]
        function = chunk.get("function") or {}
        if function.get("name"):
            call["function"]["name"] += function["name"]
        if function.get("arguments"):
            call["function"]["arguments"] += function["arguments"]

    def build(self) -> list[dict]:
        return [self._calls[index] for index in sorted(self._calls)]
