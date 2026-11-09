"""工具抽象与注册表：新增工具只需注册 ToolSpec，core 与 UI 均无需改动。"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable

ToolHandler = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def api_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    output: str


class ToolRegistry:
    def __init__(self, *specs: ToolSpec) -> None:
        self._specs: dict[str, ToolSpec] = {spec.name: spec for spec in specs}

    def add(self, *specs: ToolSpec) -> None:
        for spec in specs:
            self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def all(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def schemas(self) -> list[dict]:
        return [spec.api_schema() for spec in self._specs.values()]

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            return ToolResult(False, f"未知工具：{name}")
        try:
            if inspect.iscoroutinefunction(spec.handler):
                output = await spec.handler(**arguments)
            else:
                output = await asyncio.to_thread(spec.handler, **arguments)
        except TypeError as exc:
            return ToolResult(False, f"工具参数错误：{exc}")
        except Exception as exc:  # 工具异常不中断对话，交由模型自行纠正
            return ToolResult(False, f"工具执行失败：{exc}")
        return ToolResult(True, str(output))
