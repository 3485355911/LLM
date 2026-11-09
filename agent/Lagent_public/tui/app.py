"""Textual 应用：负责事件渲染与交互，业务全部委托给 core.Agent。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Static

from core.agent import Agent
from core.config import LLMConfig
from core.events import (
    AgentError,
    CompactFinished,
    CompactStarted,
    RoundStarted,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
    TurnFinished,
    ContextWarning,
    ContextFull,
)
from core.mcp import build_mcp_registry
from core.tools.base import ToolRegistry
from tui import commands
from tui.theme import PALETTES, THEME_NAMES, Palette, build_themes
from tui.widgets.chat import ChatView
from tui.widgets.composer import Composer, PromptInput
from tui.widgets.sidebar import Sidebar
from tui.widgets.status import StatusBar
from tui.widgets.topbar import TopBar


# ---------------------------------------------------------------------------
# 命令补全面板（覆盖在 Composer 之上）
# ---------------------------------------------------------------------------


class CommandPalette(Static):
    """输入 / 开头时弹出的命令选择面板。"""

    SELECTED = "text_strong"
    UNSELECTED = "text_dim"

    class Picked(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, matches: list[commands.Command], query: str) -> None:
        super().__init__(classes="command-palette")
        self._matches = matches
        self._query = query
        self._index = 0

    @property
    def current_value(self) -> str:
        if self._matches:
            return self._matches[self._index].name
        return self._query

    def compose(self) -> ComposeResult:
        yield Static(self._render(), id="palette-body", classes="palette-body")

    def _render(self) -> str:
        if not self._matches:
            return f"[faint]无匹配命令: {self._query}[/]"
        lines = []
        for i, cmd in enumerate(self._matches[:10]):
            marker = "▶" if i == self._index else " "
            tone = "bold accent" if i == self._index else "text_dim"
            lines.append(
                f"[{tone}]{marker}[/]  [bold]{cmd.name}[/]{cmd.args_hint}  "
                f"[faint]{cmd.description}[/]"
            )
        if len(self._matches) > 10:
            lines.append(f"[faint]… 还有 {len(self._matches) - 10} 条[/]")
        return "\n".join(lines)

    def refresh_view(self, matches: list[commands.Command], query: str) -> None:
        self._matches = matches
        self._query = query
        self._index = 0
        self.query_one("#palette-body", Static).update(self._render())

    def _move(self, delta: int) -> None:
        if not self._matches:
            return
        self._index = max(0, min(len(self._matches) - 1, self._index + delta))
        self.query_one("#palette-body", Static).update(self._render())

    def action_cursor_up(self) -> None:
        self._move(-1)

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_submit(self) -> None:
        self.post_message(self.Picked(self.current_value))

    def action_cancel(self) -> None:
        self.remove()


# ---------------------------------------------------------------------------
# ResumePicker：会话恢复选择面板
# ---------------------------------------------------------------------------


class ResumePicker(Static):
    """/resume 弹出的会话列表选择器：上下键移动，回车确认，Esc 取消。"""

    class Picked(Message):
        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    class Cancelled(Message):
        pass

    def __init__(self, sessions: list[dict], current_id: str | None) -> None:
        super().__init__(classes="command-palette resume-picker")
        self._sessions = sessions[:20]
        self._current_id = current_id
        self._index = 0

    def compose(self) -> ComposeResult:
        yield Static(self._render(), id="palette-body", classes="palette-body")

    def _render(self) -> str:
        lines = ["[bold]📂 选择要恢复的会话（上下键 · Enter · Esc 取消）[/]"]
        for i, meta in enumerate(self._sessions):
            marker = "▶" if i == self._index else " "
            sid = meta.get("id", "")
            title = meta.get("title", sid)
            count = meta.get("message_count", 0)
            is_current = sid == self._current_id
            cur_marker = " ● 当前" if is_current else ""
            tone = "bold accent" if i == self._index else "text_dim"
            lines.append(
                f"[{tone}]{marker}[/]  [bold]{title}[/]  [faint]{sid} · {count} 条[/]"
                f"{cur_marker}"
            )
        return "\n".join(lines)

    def _move(self, delta: int) -> None:
        if not self._sessions:
            return
        self._index = max(0, min(len(self._sessions) - 1, self._index + delta))
        self.query_one("#palette-body", Static).update(self._render())

    def action_cursor_up(self) -> None:
        self._move(-1)

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_submit(self) -> None:
        sid = self._sessions[self._index].get("id", "")
        if sid:
            self.post_message(self.Picked(sid))
        else:
            self.post_message(self.Cancelled())

    def action_cancel(self) -> None:
        self.post_message(self.Cancelled())


# ---------------------------------------------------------------------------
# 主应用
# ---------------------------------------------------------------------------


class LagentApp(App[None]):
    CSS_PATH = "app.tcss"
    TITLE = "Lagent"
    SUB_TITLE = "modular agent console"

    BINDINGS = [
        Binding("escape", "interrupt_or_cancel", "中断 / 取消", show=False),
        Binding("ctrl+q", "quit", "退出", show=False),
        Binding("ctrl+t", "toggle_theme", "切换主题", show=False),
        Binding("ctrl+l", "clear", "清空", show=False),
        Binding("f1", "help", "帮助", show=False),
    ]

    def __init__(
        self,
        agent: Agent,
        config: LLMConfig,
        cwd: str | None = None,
        mcp_config_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.config = config
        self.cwd = cwd or os.getcwd()
        self.mcp_config_path = mcp_config_path
        self._busy = False
        self._compacting = False
        self._worker = None
        self._palette: CommandPalette | None = None
        self._resume_picker: ResumePicker | None = None

        for theme in build_themes():
            self.register_theme(theme)
        self.theme = THEME_NAMES["dark"]

    @property
    def palette(self) -> Palette:
        key = "light" if self.theme == THEME_NAMES["light"] else "dark"
        return PALETTES[key]

    def compose(self) -> ComposeResult:
        yield TopBar(self.config, self.cwd, self.palette, agent=self.agent)
        with Horizontal(id="main-body"):
            yield Sidebar(self.palette, classes="sidebar")
            with Vertical(id="chat-col"):
                yield ChatView(self.palette, id="chat")
                yield Composer(id="composer")
        yield StatusBar(self.palette)

    async def on_mount(self) -> None:
        # 1. welcome 面板
        self.query_one(ChatView).show_welcome()
        composer = self.query_one(Composer)
        composer.focus_input()

        # 2. 如果 config 是 mock，弹窗提示
        if self.config.is_mock:
            self._notify_config_mock()

        # 3. 显示 AGENTS.md 状态
        if self.agent.has_agents_md:
            self.query_one(ChatView).add_notice(
                "📖 已检测到项目级 AGENTS.md 并注入会话，所有后续轮次自动遵循其规则",
                "info",
            )

        # 4. 异步加载 MCP（不阻塞界面）
        self._load_mcp_async()

        # 5. 刷新会话列表
        self._refresh_sessions()

    # ------------------------------------------------------------------
    # Mock 配置提示
    # ------------------------------------------------------------------

    def _notify_config_mock(self) -> None:
        self.query_one(ChatView).add_notice(
            "⚠️  当前 config.ini 是首次启动自动生成的模板，请编辑后重启才能正常对话。\n"
            f"   路径：{Path.cwd() / 'config.ini'}",
            "warn",
        )

    # ------------------------------------------------------------------
    # MCP 异步加载
    # ------------------------------------------------------------------

    @work(exclusive=False)
    async def _load_mcp_async(self) -> None:
        """后台加载 MCP，加载完动态刷新 Sidebar + TopBar。"""
        sidebar = self.query_one(Sidebar)
        sidebar.mcp_panel.set_loading()
        start = time.monotonic()

        if self.mcp_config_path is None or not self.mcp_config_path.is_file():
            sidebar.mcp_panel.set_empty()
            return

        try:
            # build_mcp_registry 内部用同步 httpx，放到线程里避免阻塞事件循环
            new_registry: ToolRegistry = await asyncio.to_thread(
                build_mcp_registry, self.mcp_config_path
            )

            # 列出成功加载的 server（new_registry 里所有带 server__ 前缀的）
            server_tools: dict[str, int] = {}
            for spec in new_registry.all():
                if "__" in spec.name:
                    server = spec.name.split("__", 1)[0]
                    server_tools[server] = server_tools.get(server, 0) + 1

            duration = (time.monotonic() - start) * 1000

            # 合并进 agent
            infos = [
                (spec.name, spec.description) for spec in new_registry.all()
            ]
            self.agent.merge_mcp_tools(new_registry, infos)

            sidebar.mcp_panel.set_ready(
                [(name, count, True) for name, count in server_tools.items()],
                duration,
            )
            self.query_one(TopBar).refresh_meta()

        except Exception as exc:
            sidebar.mcp_panel.set_error(str(exc)[:80])

    # ------------------------------------------------------------------
    # 会话列表刷新（Sidebar）
    # ------------------------------------------------------------------

    def _refresh_sessions(self) -> None:
        sidebar = self.query_one(Sidebar)
        if self.agent.can_save_session():
            sidebar.session_list.refresh_sessions(
                self.agent.list_sessions(),
                self.agent.current_session_id,
            )
        else:
            sidebar.session_list.refresh_sessions([], None)

    # ------------------------------------------------------------------
    # 输入入口
    # ------------------------------------------------------------------

    def on_prompt_input_slash_changed(self, event: PromptInput.SlashChanged) -> None:
        """用户输入 / 开头 → 弹出命令补全面板。"""
        matches = commands.search(event.text)
        if self._palette is None:
            self._palette = CommandPalette(matches, event.text)
            # 挂在 Screen overlay 上，保持在 Composer 正上方
            self.mount(self._palette, after="#composer")
        else:
            self._palette.refresh_view(matches, event.text)

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        self._dismiss_palette()
        text = event.text
        if text.startswith("/"):
            self._handle_command(text)
            return
        if self.config.is_mock:
            self.notify("⚠️  请先填写 config.ini 的 api_key 后重启", severity="warning")
            return
        if self.agent.compacting:
            self.notify("正在执行上下文压缩，请稍候", severity="warning")
            return
        if self._busy:
            self.notify("当前回复尚未结束，按 Esc 可中断", severity="warning")
            return
        self.query_one(Composer).remember(text)
        self._worker = self._run_turn(text)

    def on_command_palette_picked(self, event: CommandPalette.Picked) -> None:
        self._dismiss_palette()
        self.query_one(PromptInput).post_message(PromptInput.SlashComplete(event.value))

    def action_interrupt_or_cancel(self) -> None:
        if self._resume_picker is not None:
            self._dismiss_resume_picker()
            return
        if self._palette is not None:
            self._dismiss_palette()
            return
        if self._busy and self._worker is not None:
            self._worker.cancel()
            self.notify("已中断当前回复")

    def _dismiss_palette(self) -> None:
        if self._palette is not None:
            try:
                self._palette.remove()
            except Exception:
                pass
            self._palette = None

    # ------------------------------------------------------------------
    # 普通对话轮
    # ------------------------------------------------------------------

    @work(exclusive=True)
    async def _run_turn(self, text: str) -> None:
        chat = self.query_one(ChatView)
        status = self.query_one(StatusBar)
        composer = self.query_one(Composer)

        self._busy = True
        composer.set_busy(True)
        status.start_busy("思考中")

        assistant = None
        failed = False
        last_flush = time.monotonic()
        try:
            await chat.add_user(text)
            assistant = await chat.add_assistant()

            async for event in self.agent.stream_reply(text):
                if isinstance(event, TextDelta):
                    assistant.write(event.text)
                    now = time.monotonic()
                    if now - last_flush >= 0.06:
                        await self._flush_markdown(chat, assistant)
                        last_flush = now
                elif isinstance(event, RoundStarted):
                    status.set_label("思考中" if event.index == 1 else f"第 {event.index} 轮推理")
                elif isinstance(event, ToolCallStarted):
                    await self._flush_markdown(chat, assistant)
                    status.set_label(f"执行 {event.name}")
                elif isinstance(event, ToolCallFinished):
                    status.set_label("整理结果中")
                elif isinstance(event, TurnFinished):
                    await self._flush_markdown(chat, assistant)
                    if not event.content.strip():
                        chat.add_notice(
                            "模型没有返回内容，请重试；若反复出现请检查网络或模型配置", "warn"
                        )
                    status.set_label("完成")
                elif isinstance(event, AgentError):
                    failed = True
                    await self._flush_markdown(chat, assistant)
                    chat.add_notice(event.message, "error")
                elif isinstance(event, ContextFull):
                    chat.add_notice(
                        f"⚠️ 上下文已满（{event.used_tokens}/{event.window_tokens}），"
                        "请先执行 /compact",
                        "error",
                    )
        except asyncio.CancelledError:
            chat.add_notice("已中断本次回复", "warn")
            raise
        except Exception as exc:
            failed = True
            chat.add_notice(f"运行异常：{exc}", "error")
        finally:
            if assistant is not None:
                await self._flush_markdown(chat, assistant)
            self._busy = False
            composer.set_busy(False)
            if failed:
                status.set_error("运行出错")
            else:
                status.set_idle("就绪 · 等待输入")

            self.query_one(TopBar).refresh_meta()
            alert = self.agent.check_context()
            if alert is not None:
                self._emit_context_alert(alert, chat)

    async def _flush_markdown(self, chat: ChatView, assistant) -> None:
        follow = chat.is_vertical_scroll_end
        await assistant.flush()
        if follow:
            chat.scroll_end(animate=False)

    # ------------------------------------------------------------------
    # 上下文压缩（/compact）
    # ------------------------------------------------------------------

    @work(exclusive=True)
    async def _run_compact(self) -> None:
        chat = self.query_one(ChatView)
        status = self.query_one(StatusBar)
        composer = self.query_one(Composer)

        self._compacting = True
        composer.set_busy(True)
        status.start_busy("上下文压缩中")
        chat.add_notice(
            "⚙️ 开始执行上下文压缩：备份 → 归档 → 调用 LLM 生成摘要 → 替换当前历史",
            "info",
        )

        try:
            async for event in self.agent.compact():
                if isinstance(event, CompactStarted):
                    chat.add_notice(
                        f"📦 归档编号 {event.archive_id}，正在压缩历史…"
                    )
                elif isinstance(event, CompactFinished):
                    chat.add_notice(
                        f"✅ 压缩完成：{event.before_messages} → {event.after_messages} 条，"
                        f"摘要约 {event.summary_tokens} tokens，归档 {event.archive_id}"
                    )
                    status.set_idle("压缩完成")
                elif isinstance(event, AgentError):
                    chat.add_notice(f"❌ {event.message}", "error")
                    status.set_error("压缩失败")
        except Exception as exc:
            import traceback
            traceback.print_exc()
            chat.add_notice(f"❌ 压缩异常：{exc}", "error")
            status.set_error("压缩异常")
        finally:
            self._compacting = False
            composer.set_busy(False)
            self.query_one(TopBar).refresh_meta()

    # ------------------------------------------------------------------
    # 上下文警告处理
    # ------------------------------------------------------------------

    def _emit_context_alert(self, alert, chat: ChatView) -> None:
        if isinstance(alert, ContextWarning):
            chat.add_notice(
                f"⚠️ 上下文已使用 {alert.used_tokens} / {alert.window_tokens} "
                f"（{alert.percent*100:.0f}%），建议执行 /compact",
                "warn",
            )
        elif isinstance(alert, ContextFull):
            chat.add_notice(
                f"⛔ 上下文已满（{alert.used_tokens}/{alert.window_tokens}），"
                "请先执行 /compact",
                "error",
            )

    # ------------------------------------------------------------------
    # 命令分发（统一入口，新命令在 tui.commands 注册即可）
    # ------------------------------------------------------------------

    def _handle_command(self, command: str) -> None:
        chat = self.query_one(ChatView)
        name, _, args = command.partition(" ")
        name = name.strip().lower()
        args = args.strip()

        cmd_def = commands.get(name)

        # 通用 "busy" 守卫
        if name not in {"/new", "/help", "/tools", "/model", "/theme", "/context",
                       "/sessions", "/config", "/about", "/debug", "/status", "/quit", "/exit"}:
            if self._busy or self._compacting:
                chat.add_notice("已有任务在执行中，请稍候", "warn")
                return

        handlers = {
            # ── 会话 ──
            "/new": self._cmd_new,
            "/resume": self._cmd_resume,
            "/save": self._cmd_save,
            "/sessions": self._cmd_sessions,
            "/delete": self._cmd_delete,

            # ── 上下文 ──
            "/compact": self._cmd_compact,
            "/context": self._cmd_context,

            # ── 界面 ──
            "/help": self._cmd_help,
            "/tools": self._cmd_tools,
            "/model": self._cmd_model,
            "/theme": self._cmd_theme,
            "/clear": self._cmd_clear,
            "/config": self._cmd_config,
            "/about": self._cmd_about,

            # ── 调试 ──
            "/reset": self._cmd_clear,
            "/export": self._cmd_export,
            "/debug": self._cmd_debug,
            "/status": self._cmd_status,

            # ── 控制 ──
            "/quit": self._cmd_quit,
            "/exit": self._cmd_quit,
        }

        handler = handlers.get(name)
        if handler is None:
            chat.add_notice(f"未知命令：{name}，输入 /help 查看可用命令", "warn")
            return
        handler(args)

    # ------------------------------------------------------------------
    # 各命令实现
    # ------------------------------------------------------------------

    def _cmd_new(self, _args: str = "") -> None:
        chat = self.query_one(ChatView)
        if self._busy or self._compacting:
            chat.add_notice("已有任务在执行中，请稍候", "warn")
            return
        # 先保存当前会话（如果有内容）
        if self.agent.messages and self.agent.can_save_session():
            sid = self.agent.save_session(title="自动保存")
            if sid:
                chat.add_notice(f"💾 当前会话已自动保存 → {sid}", "info")
        self.agent.new_session()
        chat.clear_messages()
        chat.show_welcome(force=True)
        self.query_one(StatusBar).set_idle("已开启新会话")
        self.query_one(TopBar).refresh_meta()
        self._refresh_sessions()

    def _cmd_save(self, args: str = "") -> None:
        chat = self.query_one(ChatView)
        if not self.agent.can_save_session():
            chat.add_notice("当前未配置会话存储目录", "error")
            return
        if not self.agent.messages:
            chat.add_notice("当前没有对话可保存", "warn")
            return
        sid = self.agent.save_session(title=args or None)
        chat.add_notice(f"💾 会话已保存 → {sid}", "info")
        self._refresh_sessions()

    def _cmd_sessions(self, _args: str = "") -> None:
        chat = self.query_one(ChatView)
        sessions = self.agent.list_sessions()
        if not sessions:
            chat.add_notice("暂无已保存的会话。可用 /save 保存当前会话。")
            return
        lines = [f"📂 共 {len(sessions)} 个已保存会话："]
        for meta in sessions[:20]:
            sid = meta.get("id", "")
            title = meta.get("title", sid)
            count = meta.get("message_count", 0)
            last = meta.get("last_used", 0)
            rel = datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M") if last else ""
            marker = " ●" if sid == self.agent.current_session_id else "  "
            lines.append(f"{marker}  {title}  [{sid}]  {count} 条  {rel}")
        chat.add_notice("\n".join(lines))
        chat.add_notice("💡 使用 /resume <session_id> 恢复，或直接打开左侧会话列表点击", "info")

    def _cmd_delete(self, args: str = "") -> None:
        chat = self.query_one(ChatView)
        sid = args.strip()
        if not sid:
            chat.add_notice("用法：/delete <session_id>（可用 /sessions 查看）", "warn")
            return
        ok = self.agent.delete_session(sid)
        if ok:
            chat.add_notice(f"🗑️  会话 {sid} 已删除")
        else:
            chat.add_notice(f"删除失败（会话不存在或无权限）", "error")
        self._refresh_sessions()

    # ── ResumePicker：会话选择面板（挂在 ChatView overlay 上） ──

    def _cmd_resume(self, args: str = "") -> None:
        chat = self.query_one(ChatView)
        sessions = self.agent.list_sessions()
        if not sessions:
            chat.add_notice("暂无已保存的会话。可用 /save 保存当前会话后再恢复。")
            return
        # 如果给了参数（session_id），直接加载
        sid = args.strip()
        if sid:
            self._do_resume(sid)
            return
        # 否则弹出选择面板
        if self._resume_picker is not None:
            self._resume_picker.remove()
        self._resume_picker = ResumePicker(sessions, self.agent.current_session_id)
        self.mount(self._resume_picker, after="#composer")

    def _do_resume(self, session_id: str) -> None:
        chat = self.query_one(ChatView)
        if not self.agent.load_session(session_id):
            chat.add_notice(f"恢复失败：会话 {session_id} 不存在", "error")
            return
        chat.clear_messages()
        chat.show_welcome(force=True)
        chat.add_notice(f"✅ 已恢复会话 {session_id}（{len(self.agent.messages)} 条历史）", "info")
        self.query_one(TopBar).refresh_meta()
        self._refresh_sessions()

    def _dismiss_resume_picker(self) -> None:
        if self._resume_picker is not None:
            try:
                self._resume_picker.remove()
            except Exception:
                pass
            self._resume_picker = None

    def on_resume_picker_picked(self, event: "ResumePicker.Picked") -> None:
        self._dismiss_resume_picker()
        self._do_resume(event.session_id)

    def on_resume_picker_cancelled(self, _event: "ResumePicker.Cancelled") -> None:
        self._dismiss_resume_picker()

    def _cmd_compact(self, _args: str = "") -> None:
        if self._busy or self._compacting:
            self.query_one(ChatView).add_notice("已有任务在执行中，请稍候", "warn")
            return
        self._worker = self._run_compact()

    def _cmd_context(self, _args: str = "") -> None:
        chat = self.query_one(ChatView)
        used = self.agent.estimate_context_tokens()
        window = self.config.context_window
        pct = used / window * 100 if window else 0
        session_info = f"当前会话: {self.agent.current_session_id or '(未保存)'}"
        archive_count = len(self.agent.archive_list())
        sessions_count = len(self.agent.list_sessions())
        agents_md = "✅ 已注入" if self.agent.has_agents_md else "（未使用）"
        msg_count = len(self.agent.messages)
        tools_count = len(self.agent.tools.all())
        chat.add_notice(
            f"📊 上下文 {used} / {window} tokens  ({pct:.0f}%)\n"
            f"   消息: {msg_count} 条  工具: {tools_count} 个  MCP: {len([1 for t in self.agent.tools.all() if '__' in t.name])}\n"
            f"   AGENTS.md: {agents_md}\n"
            f"   {session_info}  已归档: {archive_count}  已保存会话: {sessions_count}"
        )

    def _cmd_help(self, _args: str = "") -> None:
        # 按 category 分组展示
        from collections import defaultdict
        by_cat: dict[str, list[commands.Command]] = defaultdict(list)
        for cmd in commands.all_commands():
            by_cat[cmd.category].append(cmd)

        chat = self.query_one(ChatView)
        lines: list[str] = ["📖 Lagent 命令参考："]
        for cat, cmds in by_cat.items():
            lines.append(f"\n[bold purple]── {cat} ──[/]")
            for c in cmds:
                lines.append(f"  [bold]{c.name}{c.args_hint}[/]  [faint]{c.description}[/]")
        lines.append(
            "\n[faint]Enter 发送 · Shift+Enter 换行 · ↑↓ 历史 · Esc 中断\n"
            "Ctrl+Q 退出 · Ctrl+T 主题 · Ctrl+L 清空 · F1 帮助[/]"
        )
        chat.add_notice("\n".join(lines))

    def _cmd_tools(self, _args: str = "") -> None:
        chat = self.query_one(ChatView)
        specs = self.agent.tools.all()
        tools_by_src: dict[str, list[str]] = {}
        for spec in specs:
            if "__" in spec.name:
                src = "MCP"
            elif spec.name in {"listContextArchives", "recallContext"}:
                src = "上下文"
            elif spec.name.startswith(("createFile", "writeFile", "readFile")):
                src = "文件系统"
            elif spec.name in {"searchweb", "fetchweb"}:
                src = "网络"
            elif spec.name == "runcli":
                src = "CLI"
            elif spec.name in {"loadSkill", "createSkill"}:
                src = "技能"
            else:
                src = "内置"
            tools_by_src.setdefault(src, []).append(spec.name)
        lines = [f"🛠️  已注册 {len(specs)} 个工具："]
        for src in sorted(tools_by_src):
            names = tools_by_src[src]
            lines.append(f"  [bold]{src}[/] ({len(names)}): {', '.join(names)}")
        chat.add_notice("\n".join(lines))

    def _cmd_model(self, _args: str = "") -> None:
        chat = self.query_one(ChatView)
        mode_flag = "（模板）" if self.config.is_mock else ""
        chat.add_notice(
            f"📡 模型 {self.config.model_name} {mode_flag}\n"
            f"   API:   {self.config.base_url}\n"
            f"   窗口:  {self.config.context_window} tokens  超时: {self.config.timeout}s\n"
            f"   温度:  {self.config.temperature or '(模型默认)'}"
        )

    def _cmd_theme(self, args: str = "") -> None:
        chat = self.query_one(ChatView)
        argument = args.strip().lower()
        if argument in PALETTES:
            self._apply_theme(argument)
        elif argument:
            chat.add_notice(f"未知主题：{argument}，可选 dark / light，或按 Ctrl+T 切换", "warn")
        else:
            chat.add_notice(f"当前主题：{self._theme_key()}（可选 dark / light，或按 Ctrl+T 切换）")

    def _cmd_clear(self, _args: str = "") -> None:
        chat = self.query_one(ChatView)
        if self._busy or self._compacting:
            chat.add_notice("请先等待当前回复结束，或按 Esc 中断", "warn")
            return
        self.agent.reset()
        chat.clear_messages()
        chat.show_welcome(force=True)
        self.query_one(StatusBar).set_idle("会话已清空")
        self.query_one(TopBar).refresh_meta()
        self._refresh_sessions()

    def _cmd_config(self, _args: str = "") -> None:
        chat = self.query_one(ChatView)
        # 找实际生效的 config.ini 路径
        from core.config import CONFIG_NAME
        candidates = [Path.cwd() / CONFIG_NAME]
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / CONFIG_NAME)
        candidates.append(Path(__file__).resolve().parent.parent / CONFIG_NAME)
        found = next((p for p in candidates if p.is_file()), None)
        if found:
            flag = "（首次启动自动生成的模板，请替换 api_key 后重启）" if self.config.is_mock else ""
            chat.add_notice(f"📄 config.ini 路径：{found}  {flag}")
        else:
            chat.add_notice(f"未找到 config.ini，请在项目根目录创建", "error")

    def _cmd_about(self, _args: str = "") -> None:
        chat = self.query_one(ChatView)
        chat.add_notice(
            "◆ Lagent v1.1 — 模块化 AI 终端助手\n"
            "  基于 Textual 打造，支持流式对话、工具调用、上下文压缩、会话管理、MCP 扩展\n"
            "  AGENTS.md：一次注入，全程复用\n"
            "  配置文件：config.ini ·  会话存储：.agents/sessions/ ·  压缩归档：.agents/context/"
        )

    def _cmd_export(self, args: str = "") -> None:
        chat = self.query_one(ChatView)
        if not self.agent.messages:
            chat.add_notice("当前没有对话可导出", "warn")
            return
        out_path = Path(args.strip() or f"lagent-session-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md")
        lines = [f"# Lagent 会话导出 · {datetime.now().isoformat()}\n"]
        for msg in self.agent.messages:
            role = msg.get("role", "?")
            content = msg.get("content") or ""
            if role == "user":
                lines.append(f"\n## 🧑 用户\n\n{content}\n")
            elif role == "assistant":
                lines.append(f"\n## 🤖 Lagent\n\n{content}\n")
                if msg.get("tool_calls"):
                    lines.append(f"\n*工具调用 {len(msg['tool_calls'])} 次*\n")
            elif role == "tool":
                lines.append(f"\n*工具返回*\n\n```\n{content}\n```\n")
        try:
            out_path.write_text("\n".join(lines), encoding="utf-8")
            chat.add_notice(f"📤 已导出 → {out_path.resolve()}")
        except OSError as exc:
            chat.add_notice(f"导出失败：{exc}", "error")

    def _cmd_debug(self, _args: str = "") -> None:
        chat = self.query_one(ChatView)
        import platform
        info = (
            f"🔍 Lagent 诊断信息\n"
            f"  Python:  {sys.version.split()[0]}  平台: {platform.platform()}\n"
            f"  frozen:  {getattr(sys, 'frozen', False)}  ROOT: {Path.cwd()}\n"
            f"  消息数:  {len(self.agent.messages)}  工具数: {len(self.agent.tools.all())}\n"
            f"  _busy:   {self._busy}  _compacting: {self._compacting}\n"
            f"  会话:    {self.agent.current_session_id or '(未保存)'}\n"
            f"  AGENTS.md: {self.agent.has_agents_md}\n"
            f"  Config is_mock: {self.config.is_mock}"
        )
        chat.add_notice(info)

    def _cmd_status(self, _args: str = "") -> None:
        self._cmd_context()

    def _cmd_quit(self, _args: str = "") -> None:
        self.exit()

    # ------------------------------------------------------------------
    # 主题 & 其他 action
    # ------------------------------------------------------------------

    def action_interrupt(self) -> None:
        # 已改成 action_interrupt_or_cancel
        pass

    def action_clear(self) -> None:
        self._handle_command("/clear")

    def action_help(self) -> None:
        self._handle_command("/help")

    def _theme_key(self) -> str:
        return "light" if self.theme == THEME_NAMES["light"] else "dark"

    def _apply_theme(self, key: str) -> None:
        self.theme = THEME_NAMES[key]
        palette = PALETTES[key]
        self.query_one(TopBar).apply_palette(palette)
        self.query_one(ChatView).apply_palette(palette)
        self.query_one(Sidebar).apply_palette(palette)
        status = self.query_one(StatusBar)
        status.apply_palette(palette)
        status.set_idle(f"{'深色' if key == 'dark' else '浅色'}主题 · 就绪")

    def action_toggle_theme(self) -> None:
        self._apply_theme("light" if self._theme_key() == "dark" else "dark")


# ---------------------------------------------------------------------------
# Textual run 入口（main.py 调这个）
# ---------------------------------------------------------------------------


def run_tui(agent: Agent, config: LLMConfig, mcp_config_path: Path | None = None) -> None:
    LagentApp(agent, config, mcp_config_path=mcp_config_path).run()
