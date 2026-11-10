"""OpenAI 兼容消息构造，隔离聊天协议的字段细节。"""

from __future__ import annotations


def system(text: str) -> dict:
    return {"role": "system", "content": text}


def user(text: str) -> dict:
    return {"role": "user", "content": text}


def assistant(content: str, tool_calls: list[dict] | None = None) -> dict:
    message: dict = {"role": "assistant", "content": content or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def tool_result(call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}
