"""流式聊天客户端：仅负责网络传输与增量解析，不包含任何业务编排。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from core.config import LLMConfig
from core.llm.protocol import iter_sse_payloads


class LLMError(RuntimeError):
    """模型服务调用失败。"""


@dataclass(frozen=True, slots=True)
class StreamDelta:
    content: str = ""
    tool_calls: tuple[dict, ...] = ()
    usage: dict | None = None
    """仅在流结束时的最后一条 chunk 里有值；中途为 None。"""


def _build_payload(config: LLMConfig, messages: list[dict], tools: list[dict], stream: bool) -> dict:
    payload: dict = {
        "model": config.model_name,
        "messages": messages,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    return payload


def _build_headers(config: LLMConfig) -> dict:
    return {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }


class LLMClient:
    def __init__(self, config: LLMConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(config.timeout, connect=20.0))
        self._owned = client is None

    async def aclose(self) -> None:
        if self._owned:
            await self._client.aclose()

    async def chat_stream(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[StreamDelta]:
        headers = _build_headers(self.config)
        payload = _build_payload(self.config, messages, tools or [], stream=True)

        try:
            async with self._client.stream(
                "POST", self.config.chat_url, headers=headers, json=payload
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise LLMError(f"模型请求失败（HTTP {response.status_code}）：{_error_message(body)}")

                async for data in iter_sse_payloads(response.aiter_lines()):
                    choices = data.get("choices") or []
                    delta = choices[0].get("delta") or {} if choices else {}
                    content = delta.get("content") or ""
                    tool_calls = tuple(delta.get("tool_calls") or ())
                    usage = data.get("usage")
                    if content or tool_calls or usage:
                        yield StreamDelta(content=content, tool_calls=tool_calls, usage=usage)
        except httpx.HTTPError as exc:
            raise LLMError(f"网络请求异常：{exc}") from exc

    async def chat_text(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> tuple[str, dict | None]:
        """非流式调用：返回完整文本 + usage 字典（若模型提供）。"""
        headers = _build_headers(self.config)
        payload = _build_payload(self.config, messages, tools or [], stream=False)

        try:
            response = await self._client.post(self.config.chat_url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"网络请求异常：{exc}") from exc

        if response.status_code >= 400:
            raise LLMError(
                f"模型请求失败（HTTP {response.status_code}）：{_error_message(response.text)}"
            )

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise LLMError(f"响应不是合法 JSON：{exc}") from exc

        choices = data.get("choices") or []
        content = ""
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content") or ""
        return content, data.get("usage")


def _error_message(body: str) -> str:
    """尽量从错误响应中提取可读信息。"""
    try:
        data = json.loads(body)
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)
        return str(error or body)
    except Exception:
        return body[:500] or "未知错误"
