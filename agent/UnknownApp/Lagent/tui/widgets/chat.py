"""聊天区域与各类消息卡片。"""

from __future__ import annotations

from rich.markup import escape
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Markdown, Static

from tui.theme import Palette

COMMANDS = "/help  /tools  /model  /theme  /context  /compact  /resume  /save  /clear  /quit"


class Welcome(Static):
    def __init__(self, palette: Palette) -> None:
        self._palette = palette
        super().__init__(self._body(), classes="welcome")

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update(self._body())

    def _body(self) -> str:
        p = self._palette
        return (
            f"[bold {p.accent}]◆ LAGENT[/]  [{p.text_faint}]v1.1 · modular agent console[/]\n"
            f"[{p.text_dim}]直接用自然语言描述需求，我会调用文件工具完成操作。[/]\n"
            f"[{p.text_dim}]支持上下文压缩、会话持久化、MCP 扩展、AGENTS.md 注入。[/]\n\n"
            f"[bold {p.purple}]命令[/]   [{p.text_dim}]{COMMANDS}[/]\n"
            f"[bold {p.purple}]操作[/]   "
            f"[{p.text_dim}]Enter 发送 · ↑↓ 历史 · Esc 中断 · Ctrl+Q 退出 · Ctrl+T 主题 · F1 帮助[/]"
        )


class UserMessage(Static):
    def __init__(self, text: str) -> None:
        super().__init__(escape(text), classes="message user")
        self.border_title = "你"


class AssistantMessage(Vertical):
    """增量渲染的助手消息：先累积文本，再由调用方按节奏刷新。"""

    def __init__(self) -> None:
        super().__init__(classes="message assistant")
        self.border_title = "◈ Lagent"
        self._buffer = ""
        self._markdown: Markdown | None = None

    def compose(self):
        yield Markdown("", open_links=False)

    def on_mount(self) -> None:
        self._markdown = self.query_one(Markdown)

    def write(self, text: str) -> None:
        self._buffer += text

    async def flush(self) -> None:
        if self._markdown is not None:
            await self._markdown.update(self._buffer)


class Notice(Static):
    """系统通知：info / warn / error 三种 severity，前缀图标根据 severity 自动选。"""

    ICONS = {"info": "›", "warn": "⚠", "error": "✗"}

    def __init__(self, message: str, severity: str, palette: Palette) -> None:
        self._message = message
        self._severity = severity
        self._palette = palette
        super().__init__(self._body(), classes=f"notice {severity}")

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update(self._body())

    def _body(self) -> str:
        icon = self.ICONS.get(self._severity, "›")
        return f"[bold]{icon}[/] [{self._palette.text_dim}]{escape(self._message)}[/]"


class ChatView(VerticalScroll):
    """消息容器，负责挂载、滚动与清空。"""

    can_focus = False

    def __init__(self, palette: Palette, **kwargs) -> None:
        super().__init__(**kwargs)
        self.palette = palette

    def apply_palette(self, palette: Palette) -> None:
        self.palette = palette
        widgets = [*self.query(Welcome), *self.query(Notice)]
        for widget in widgets:
            widget.apply_palette(palette)

    def show_welcome(self, force: bool = False) -> None:
        if not force and self.query(Welcome):
            return
        self.mount(Welcome(self.palette))
        self.call_after_refresh(self.scroll_end, animate=False, immediate=True)

    def add_notice(self, message: str, severity: str = "info") -> None:
        self.mount(Notice(message, severity, self.palette))
        self.call_after_refresh(self.scroll_end, animate=False, immediate=True)

    def add_help(self) -> None:
        self.add_notice(
            "命令：/help 帮助 · /tools 工具清单 · /model 当前模型 · "
            "/theme dark|light 切换主题 · /clear 清空会话 · /quit 退出",
            "info",
        )

    async def add_user(self, text: str) -> None:
        for welcome in self.query(Welcome):
            welcome.remove()
        await self.mount(UserMessage(text))
        self.scroll_end(animate=False, immediate=True)

    async def add_assistant(self) -> AssistantMessage:
        message = AssistantMessage()
        await self.mount(message)
        self.scroll_end(animate=False)
        return message

    def clear_messages(self) -> None:
        for child in list(self.children):
            child.remove()
