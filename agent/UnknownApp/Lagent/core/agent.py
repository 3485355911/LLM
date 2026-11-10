"""Agent 编排层：把 LLM 与工具串成可观测的事件流，不依赖任何 UI。

上下文压缩 / 归档 / 检索 相关的实现全部委托给 core.context 模块，
会话持久化委托给 core.session 模块，agent 只负责编排与状态切换。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import AsyncIterator

from core import context as ctx
from core import messages
from core import session as sess
from core.events import (
    AgentError,
    AgentEvent,
    CompactFinished,
    CompactStarted,
    ContextFull,
    ContextWarning,
    RoundStarted,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
    TurnFinished,
)
from core.llm.client import LLMClient
from core.llm.protocol import ToolCallAccumulator
from core.tools.base import ToolRegistry, ToolResult

DEFAULT_THRESHOLD = 0.80  # 达到窗口 80% 时警告 + 暂停


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        max_rounds: int = 12,
        system_prompt: str = "",
        system_prompt_builder=None,
        context_window: int = 128_000,
        session_dir: Path | None = None,
        sessions_dir: Path | None = None,
        agents_md_content: str = "",
        agents_md_path: str | None = None,
        mcp_tool_infos: list | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.max_rounds = max_rounds
        self._system_prompt = system_prompt
        self._system_prompt_builder = system_prompt_builder

        # 对话历史
        self.messages: list[dict] = []

        # AGENTS.md：独立存储，永远在 _request_messages 时拼在最前面
        # 这样它不会被 compact 丢掉，也不会有 __agents_md__ 字段污染 API payload
        self._agents_md_content = agents_md_content or ""
        self._agents_md_path = agents_md_path
        self._agents_md_message: dict | None = self._make_agents_md_message()

        # 上下文窗口与归档（compact 用）
        self.context_window = context_window
        self._archive = (
            ctx.ContextArchive(session_dir) if session_dir is not None else None
        )

        # 会话持久化（/save /resume /new 用）
        self._session_store = (
            sess.SessionStore(sessions_dir) if sessions_dir is not None else None
        )
        self.current_session_id: str | None = None

        # MCP 工具清单引用（让 main.py 的闭包能追加）
        self._mcp_tool_infos = mcp_tool_infos if mcp_tool_infos is not None else []

        # --- 上下文状态 ---
        self._last_usage: dict | None = None
        self._compacting = False
        self._threshold_pct = DEFAULT_THRESHOLD

    # ------------------------------------------------------------------
    # 基本属性
    # ------------------------------------------------------------------

    def _make_agents_md_message(self) -> dict | None:
        if not self._agents_md_content.strip():
            return None
        src = f"（来源：{self._agents_md_path}）" if self._agents_md_path else ""
        return {
            "role": "system",
            "content": (
                f"# AGENTS.md / PROJECT INSTRUCTIONS {src}\n\n"
                f"以下是当前项目根目录的 AGENTS.md 文件，它包含了针对本项目的指导原则、"
                f"技术栈说明、代码风格和开发约定。请在本会话中始终遵守这些规则：\n\n"
                f"---\n{self._agents_md_content}\n---"
            ),
        }

    @property
    def system_prompt(self) -> str:
        if self._system_prompt_builder is not None:
            try:
                self._system_prompt = self._system_prompt_builder()
            except Exception:
                pass
        return self._system_prompt

    @property
    def compacting(self) -> bool:
        return self._compacting

    @property
    def has_agents_md(self) -> bool:
        return self._agents_md_message is not None

    def reset(self) -> None:
        """清空当前对话历史。AGENTS.md 保留。"""
        self.messages.clear()
        self._last_usage = None

    def _request_messages(self) -> list[dict]:
        """请求时拼上 system prompt + AGENTS.md + 对话历史。"""
        out: list[dict] = []
        if self.system_prompt:
            out.append(messages.system(self.system_prompt))
        if self._agents_md_message is not None:
            out.append(self._agents_md_message)
        out.extend(self.messages)
        return out

    async def aclose(self) -> None:
        await self.llm.aclose()

    # ------------------------------------------------------------------
    # Token / 上下文估算
    # ------------------------------------------------------------------

    def estimate_context_tokens(self) -> int:
        """估算当前完整请求的 token 数（system + AGENTS.md + messages + 工具定义）。"""
        total = 0
        if self.system_prompt:
            total += ctx.estimate_tokens([messages.system(self.system_prompt)])
        if self._agents_md_message is not None:
            total += ctx.estimate_tokens([self._agents_md_message])
        total += ctx.estimate_tokens(self.messages)
        # 工具定义 schema 的估算
        tool_schemas = self.tools.schemas()
        for schema in tool_schemas:
            desc = schema.get("function", {}).get("description", "")
            params = schema.get("function", {}).get("parameters", {})
            total += max(30, int((len(desc) + len(json.dumps(params, ensure_ascii=False))) / 3.5))
        return total

    @property
    def last_usage(self) -> dict | None:
        return self._last_usage

    def _pick_prompt_tokens(self, usage: dict | None) -> int | None:
        if not usage:
            return None
        return usage.get("prompt_tokens") or usage.get("input_tokens") or None

    # ------------------------------------------------------------------
    # MCP 工具异步合并入口
    # ------------------------------------------------------------------

    def merge_mcp_tools(self, mcp_registry: ToolRegistry, infos: list[tuple[str, str]]) -> None:
        """异步加载完 MCP 后把工具合并进来，并刷新 system prompt。"""
        self.tools.add(*mcp_registry.all())
        # 追加 MCP 工具清单引用（system_prompt_builder 闭包里用同一个 list）
        for info in infos:
            if info not in self._mcp_tool_infos:
                self._mcp_tool_infos.append(info)

    # ------------------------------------------------------------------
    # 主对话流
    # ------------------------------------------------------------------

    async def stream_reply(self, user_input: str) -> AsyncIterator[AgentEvent]:
        """处理一次用户输入，按事件流逐步产出结果。"""
        if self._compacting:
            yield AgentError("正在执行上下文压缩，请稍候…")
            return

        current = self.estimate_context_tokens()
        if current >= int(self.context_window * self._threshold_pct):
            yield ContextFull(used_tokens=current, window_tokens=self.context_window)
            yield AgentError(
                f"上下文已用 {current} / {self.context_window} tokens，"
                "请先执行 /compact 压缩"
            )
            return

        self.messages.append(messages.user(user_input))

        for round_index in range(1, self.max_rounds + 1):
            yield RoundStarted(round_index)

            accumulator = ToolCallAccumulator()
            content_parts: list[str] = []
            final_usage: dict | None = None
            try:
                async for delta in self.llm.chat_stream(
                    self._request_messages(), self.tools.schemas()
                ):
                    if delta.content:
                        content_parts.append(delta.content)
                        yield TextDelta(delta.content)
                    for chunk in delta.tool_calls:
                        accumulator.add(chunk)
                    if delta.usage:
                        final_usage = delta.usage
            except Exception as exc:
                yield AgentError(str(exc))
                return

            content = "".join(content_parts)
            calls = accumulator.build()
            if not calls:
                self.messages.append(messages.assistant(content))
                if final_usage:
                    self._last_usage = final_usage
                yield TurnFinished(content)
                return

            for position, call in enumerate(calls):
                if not call.get("id"):
                    call["id"] = f"call_{round_index}_{position}"
            self.messages.append(messages.assistant(content, calls))

            for call in calls:
                call_id = call["id"]
                name = call["function"].get("name") or ""
                arguments, parse_error = _parse_arguments(call["function"].get("arguments", ""))

                yield ToolCallStarted(call_id, name, arguments)
                if parse_error:
                    result = ToolResult(False, parse_error)
                else:
                    result = await self.tools.execute(name, arguments)

                self.messages.append(messages.tool_result(call_id, result.output))
                yield ToolCallFinished(call_id, name, result.ok, result.output)

        yield AgentError(f"已达到最大推理轮次（{self.max_rounds}），本次对话中止")

    # ------------------------------------------------------------------
    # 上下文压缩
    # ------------------------------------------------------------------

    async def compact(self) -> AsyncIterator[AgentEvent]:
        """手动触发压缩：备份 → 归档 → LLM 生成摘要 → 替换历史。

        AGENTS.md 不会丢失，它始终独立于 self.messages。
        失败时保留原始 messages。
        """
        if self._compacting:
            yield AgentError("上下文压缩已在进行中")
            return

        if not self.messages:
            yield AgentError("当前没有可压缩的历史记录")
            return

        if self._archive is None:
            yield AgentError("未配置会话目录，无法执行 /compact")
            return

        self._compacting = True
        archive_id = self._archive.next_id()
        yield CompactStarted(archive_id=archive_id)

        backup: list[dict] | None = None
        before_count = len(self.messages)

        try:
            backup = copy.deepcopy(self.messages)

            try:
                self._archive.save(archive_id, backup)
            except Exception as exc:
                yield AgentError(f"归档失败：{exc}")
                self._compacting = False
                return

            history_text = ctx.messages_to_text(backup)
            compact_messages = [
                messages.system(ctx.COMPACT_SYSTEM_PROMPT),
                messages.user(ctx.build_compact_user_prompt(history_text)),
            ]
            summary_text, summary_usage = await self.llm.chat_text(compact_messages)

            if not summary_text.strip():
                yield AgentError("压缩摘要为空，已保留原始上下文")
                self._compacting = False
                return

            note = ctx.archive_note(archive_id)
            # 只替换 self.messages，AGENTS.md 始终在 _request_messages 时单独拼
            self.messages = [
                messages.assistant(
                    "（上下文已压缩，以下是摘要）\n\n" + summary_text + note
                )
            ]

            after_count = len(self.messages)
            summary_tokens = (
                summary_usage.get("completion_tokens")
                if summary_usage
                else int(len(summary_text) / 3.5)
            )

            yield CompactFinished(
                archive_id=archive_id,
                before_messages=before_count,
                after_messages=after_count,
                summary_tokens=int(summary_tokens or 0),
            )
            self._last_usage = None

        except Exception as exc:
            yield AgentError(f"压缩失败：{exc}")
            if backup is not None:
                self.messages = backup
        finally:
            self._compacting = False

    # ------------------------------------------------------------------
    # 上下文阈值检查
    # ------------------------------------------------------------------

    def check_context(self) -> AgentEvent | None:
        current = self.estimate_context_tokens()
        if current >= self.context_window:
            return ContextFull(used_tokens=current, window_tokens=self.context_window)
        if current >= int(self.context_window * self._threshold_pct):
            return ContextWarning(
                used_tokens=current,
                window_tokens=self.context_window,
                percent=current / self.context_window,
            )
        return None

    # ------------------------------------------------------------------
    # 归档与检索（不经过 LLM）
    # ------------------------------------------------------------------

    def archive_list(self) -> list[tuple[str, int, str]]:
        if self._archive is None:
            return []
        return self._archive.list()

    # ------------------------------------------------------------------
    # 会话管理（SessionStore 代理）
    # ------------------------------------------------------------------

    def can_save_session(self) -> bool:
        return self._session_store is not None

    def list_sessions(self) -> list[dict]:
        if self._session_store is None:
            return []
        return self._session_store.list_sessions()

    def save_session(
        self,
        session_id: str | None = None,
        title: str | None = None,
    ) -> str | None:
        """把当前 messages 落盘。返回 session_id；未配置 SessionStore 返回 None。"""
        if self._session_store is None:
            return None

        # 把 AGENTS.md 也序列化进 messages（放在最前面），便于恢复时识别
        to_save: list[dict] = []
        if self._agents_md_message is not None:
            to_save.append({**self._agents_md_message, "__agents_md__": True})
        to_save.extend(self.messages)

        if session_id is None:
            if self.current_session_id is None:
                session_id = self._session_store.create(title or "")
            else:
                session_id = self.current_session_id
        else:
            # 确保会话目录存在
            if self._session_store.get_metadata(session_id) is None:
                self._session_store.create(session_id)

        self._session_store.save(session_id, to_save, title=title)
        self.current_session_id = session_id
        return session_id

    def load_session(self, session_id: str) -> bool:
        """加载一个已保存的会话。成功返回 True。"""
        if self._session_store is None:
            return False
        data = self._session_store.load(session_id)
        if data is None:
            return False

        # 分离 AGENTS.md 消息（如果有）和普通消息
        agents_msg: dict | None = None
        normal_messages: list[dict] = []
        for msg in data:
            if msg.get("__agents_md__"):
                agents_msg = {k: v for k, v in msg.items() if k != "__agents_md__"}
            else:
                normal_messages.append(msg)

        self.messages = normal_messages

        # 恢复 AGENTS.md 状态
        if agents_msg is not None:
            self._agents_md_message = agents_msg
            self._agents_md_content = agents_msg.get("content", "")
        else:
            # 加载的旧会话没有 AGENTS.md 标记 → 如果当前项目有 AGENTS.md 就补注入
            if self._agents_md_content.strip():
                self._agents_md_message = self._make_agents_md_message()

        self.current_session_id = session_id
        self._last_usage = None
        return True

    def new_session(self) -> None:
        """开启一个全新的对话（清空历史，AGENTS.md 保留）。"""
        self.reset()
        self.current_session_id = None

    def delete_session(self, session_id: str) -> bool:
        if self._session_store is None:
            return False
        ok = self._session_store.delete(session_id)
        if ok and self.current_session_id == session_id:
            self.current_session_id = None
        return ok


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _parse_arguments(raw: str) -> tuple[dict, str | None]:
    if not raw.strip():
        return {}, None
    try:
        arguments = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"工具参数不是合法 JSON：{exc}"
    if not isinstance(arguments, dict):
        return {}, "工具参数必须是 JSON 对象"
    return arguments, None
