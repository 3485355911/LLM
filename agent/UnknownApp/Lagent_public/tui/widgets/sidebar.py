"""左侧边栏：上半 MCP 服务器状态 + 下半会话列表。"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from tui.theme import Palette


# ---------------------------------------------------------------------------
# MCP 服务器区
# ---------------------------------------------------------------------------


def _fmt_relative(ts: float) -> str:
    """把 last_used 时间戳格式化为相对时间（3天前、今天 10:23、…）。"""
    dt = datetime.fromtimestamp(ts)
    now = datetime.now()
    if dt.date() == now.date():
        return f"今天 {dt:%H:%M}"
    diff = (now.date() - dt.date()).days
    if diff == 1:
        return f"昨天 {dt:%H:%M}"
    if diff < 7:
        return f"{diff} 天前"
    if diff < 30:
        return f"{diff // 7} 周前"
    return dt.strftime("%m-%d")


class MCPPanel(Vertical):
    """上半：MCP 服务器状态面板。"""

    def __init__(self, palette: Palette) -> None:
        super().__init__(classes="sidebar-panel")
        self._palette = palette
        self._status_widget: Static | None = None
        self._servers_widget: Static | None = None

    def compose(self):
        yield Static("🔌 MCP 服务器", classes="sidebar-header")
        yield Static("⏳ 启动后异步加载中…", id="mcp-status", classes="sidebar-body")

    def on_mount(self) -> None:
        self._status_widget = self.query_one("#mcp-status", Static)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette

    def set_loading(self) -> None:
        if self._status_widget:
            self._status_widget.update("⏳ 异步加载中…")

    def set_ready(self, servers: list[tuple[str, int, bool]], duration_ms: float) -> None:
        """servers: [(name, tool_count, ok), ...]"""
        lines: list[str] = [f"[dim]✅ 已加载 {len(servers)} 个服务器  [faint]({duration_ms:.0f}ms)[/]"]
        for name, count, ok in servers:
            icon = "🟢" if ok else "🔴"
            tone = "green" if ok else "red"
            lines.append(f"  [bold]{icon}[/] [accent_soft]{name}[/]  [faint]{count} 工具[/]")
        body = "\n".join(lines)
        if self._status_widget:
            self._status_widget.update(body)

    def set_empty(self) -> None:
        if self._status_widget:
            self._status_widget.update(
                "[faint]未配置 .mcp.json[/]\n"
                "[faint]在项目根目录创建后重启即可[/]"
            )

    def set_error(self, msg: str) -> None:
        if self._status_widget:
            self._status_widget.update(f"[red]❌ {msg}[/]")


# ---------------------------------------------------------------------------
# 会话列表区
# ---------------------------------------------------------------------------


class SessionList(Vertical):
    """下半：会话列表。"""

    def __init__(self, palette: Palette) -> None:
        super().__init__(classes="sidebar-panel")
        self._palette = palette

    def compose(self):
        yield Static("💬 历史会话", classes="sidebar-header")
        yield Static("[faint]暂无会话[/]", id="sessions-body", classes="sidebar-body")

    def refresh_sessions(
        self,
        sessions: list[dict],
        current_session_id: str | None,
    ) -> None:
        body = self.query_one("#sessions-body", Static)
        if not sessions:
            body.update("[faint]保存会话后会出现在这里[/]\n[faint]（/save 当前  /resume 恢复）[/]")
            return
        lines: list[str] = []
        for meta in sessions[:20]:  # 最多显示 20 条
            sid = meta.get("id", "")
            title = meta.get("title", sid)
            last_used = meta.get("last_used", 0)
            rel = _fmt_relative(last_used) if last_used else ""
            count = meta.get("message_count", 0)
            marker = " ●" if sid == current_session_id else "  "
            tone = "accent" if sid == current_session_id else "text_dim"
            lines.append(
                f"[{tone}]{marker}[/]  [text_strong]{title}[/]\n"
                f"    [faint]{sid} · {count} 条 · {rel}[/]"
            )
        body.update("\n".join(lines))


# ---------------------------------------------------------------------------
# 整体 Sidebar（左 Dock）
# ---------------------------------------------------------------------------


class Sidebar(Vertical):
    def __init__(self, palette: Palette, **kwargs) -> None:
        super().__init__(id="sidebar", **kwargs)
        self._palette = palette
        self.mcp_panel = MCPPanel(palette)
        self.session_list = SessionList(palette)

    def compose(self):
        yield self.mcp_panel
        yield self.session_list

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.mcp_panel.set_palette(palette)
