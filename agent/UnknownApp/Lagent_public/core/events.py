"""Agent 事件流：core 对外唯一的输出契约，所有 UI 都消费同一套事件。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RoundStarted:
    """开始一轮模型推理。"""

    index: int


@dataclass(frozen=True, slots=True)
class TextDelta:
    """模型输出的增量文本。"""

    text: str


@dataclass(frozen=True, slots=True)
class ToolCallStarted:
    """开始执行工具调用。"""

    call_id: str
    name: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class ToolCallFinished:
    """工具调用结束。"""

    call_id: str
    name: str
    ok: bool
    output: str


@dataclass(frozen=True, slots=True)
class TurnFinished:
    """一轮用户输入处理完成。"""

    content: str


@dataclass(frozen=True, slots=True)
class AgentError:
    """可展示给用户的错误。"""

    message: str


@dataclass(frozen=True, slots=True)
class ContextWarning:
    """上下文使用量达到 80%，UI 应提示用户执行 /compact。"""

    used_tokens: int
    window_tokens: int
    percent: float


@dataclass(frozen=True, slots=True)
class ContextFull:
    """上下文超过阈值，暂停接受新普通输入，等待压缩完成。"""

    used_tokens: int
    window_tokens: int


@dataclass(frozen=True, slots=True)
class CompactStarted:
    """开始执行压缩。"""

    archive_id: str


@dataclass(frozen=True, slots=True)
class CompactFinished:
    """压缩完成。"""

    archive_id: str
    before_messages: int
    after_messages: int
    summary_tokens: int


AgentEvent = (
    RoundStarted
    | TextDelta
    | ToolCallStarted
    | ToolCallFinished
    | TurnFinished
    | AgentError
    | ContextWarning
    | ContextFull
    | CompactStarted
    | CompactFinished
)
