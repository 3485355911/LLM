"""底部状态栏：空闲 / 忙碌动画 / 错误提示。"""

from __future__ import annotations

from rich.markup import escape
from textual.containers import Horizontal
from textual.widgets import Static

from tui.theme import Palette

# 专业的 ASCII spinner（4 帧）
SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
DOTS = [".", "..", "...", ""]
HINT = "Enter 发送 · Shift+Enter 换行 · ↑↓ 历史 · Esc 中断 · Ctrl+Q 退出 · Ctrl+T 主题 · Ctrl+L 清空 · F1 帮助"


class StatusBar(Horizontal):
    def __init__(self, palette: Palette) -> None:
        super().__init__(id="statusbar")
        self._palette = palette
        self._busy = False
        self._label = "就绪"
        self._base_label = ""
        self._state = "idle"
        self._frame = 0
        self._timer = None

    def compose(self):
        yield Static("", id="status-main")
        yield Static(HINT, id="status-hint")

    def on_mount(self) -> None:
        self.set_idle("就绪 · 等待输入")

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._repaint()

    def set_idle(self, label: str = "就绪") -> None:
        self._stop()
        self._label = label
        self._state = "idle"
        self._repaint()

    def set_error(self, label: str) -> None:
        self._stop()
        self._label = label
        self._state = "error"
        self._repaint()

    def start_busy(self, label: str = "思考中") -> None:
        self._base_label = label
        if self._busy:
            self._tick()
            return
        self._busy = True
        self._state = "busy"
        self._frame = 0
        self._timer = self.set_interval(0.08, self._tick)
        self._tick()

    def set_label(self, label: str) -> None:
        self._base_label = label
        if self._busy:
            self._tick()
        else:
            self._label = label
            self._repaint()

    def _repaint(self) -> None:
        p = self._palette
        if self._state == "error":
            self._paint("●", p.red, self._label, p.red)
        elif self._state == "busy":
            self._tick()
        else:
            self._paint("●", p.green, self._label, p.text_dim)

    def _tick(self) -> None:
        p = self._palette
        frame = SPINNER[self._frame % len(SPINNER)]
        dots = DOTS[self._frame % len(DOTS)]
        self._frame += 1
        self._label = f"{self._base_label}{dots}"
        self._paint(frame, p.accent, self._label, p.text_dim)

    def _paint(self, marker: str, marker_color: str, label: str, label_color: str) -> None:
        content = f"[{marker_color}]{marker}[/]  [{label_color}]{escape(label)}[/]"
        self.query_one("#status-main", Static).update(content)

    def _stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._busy = False

    def on_unmount(self) -> None:
        self._stop()
