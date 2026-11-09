"""输入栏：多行输入，Enter 提交、Shift+Enter 换行，支持 /命令 自动补全。"""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static, TextArea

IDLE_PLACEHOLDER = "向 Lagent 提问，Enter 发送 / Shift+Enter 换行 / 输入 /help 查看命令…"
BUSY_PLACEHOLDER = "Lagent 正在处理…（Esc 中断）"


class PromptInput(TextArea):
    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class SlashChanged(Message):
        """当用户输入以 / 开头且可能是命令时发出，App 可据此弹出补全面板。"""
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class SlashComplete(Message):
        """用户选定了补全项，PromptInput 用它回填。"""
        def __init__(self, replacement: str) -> None:
            super().__init__()
            self.replacement = replacement

    BINDINGS = [
        Binding("enter", "submit", "发送", show=False, priority=True),
        Binding("shift+enter", "insert_newline", "换行", show=False, priority=True),
        Binding("ctrl+up", "history_prev", "上一条", show=False),
        Binding("ctrl+down", "history_next", "下一条", show=False),
    ]

    def __init__(self) -> None:
        super().__init__(placeholder=IDLE_PLACEHOLDER, id="input", soft_wrap=True)
        self._history: list[str] = []
        self._cursor: int | None = None
        self._slash_emitted = ""  # 上次发出 SlashChanged 时的 text，避免重复

    # ── 监听输入，自动触发补全面板 ──────────────────────────

    def action_insert_character(self, character: str) -> None:
        super().action_insert_character(character)
        self._maybe_emit_slash()

    def action_delete_before_cursor(self) -> None:
        super().action_delete_before_cursor()
        self._maybe_emit_slash()

    def action_delete_word_before_cursor(self) -> None:
        super().action_delete_word_before_cursor()
        self._maybe_emit_slash()

    def _maybe_emit_slash(self) -> None:
        raw = self.text
        stripped = raw.strip()
        # 触发条件：第一行就是 "/" 开头，且光标在第一个词内（还没空格）
        first_line = stripped.split("\n", 1)[0]
        if first_line.startswith("/") and " " not in first_line:
            if raw != self._slash_emitted:
                self._slash_emitted = raw
                self.post_message(self.SlashChanged(first_line))
        else:
            self._slash_emitted = ""

    # ── 外部回填 ───────────────────────────────────────────

    def on_slash_complete(self, event: "PromptInput.SlashComplete") -> None:
        """选中补全项后，把 /xxx 替换成 /xxx 并在后面留一个空格 + 光标。"""
        self.text = event.replacement + " "
        self.cursor_location = self.document.end
        self._slash_emitted = self.text

    # ── 原有逻辑 ────────────────────────────────────────────

    def remember(self, text: str) -> None:
        if not text or (self._history and self._history[-1] == text):
            return
        self._history.append(text)
        self._cursor = None

    def action_submit(self) -> None:
        text = self.text.strip()
        if text:
            self.post_message(self.Submitted(text))
        self.text = ""
        self._cursor = None
        self._slash_emitted = ""

    def action_insert_newline(self) -> None:
        self.insert("\n")

    def action_history_prev(self) -> None:
        if not self._history:
            return
        if self._cursor is None:
            self._cursor = len(self._history)
        self._cursor = max(0, self._cursor - 1)
        self.text = self._history[self._cursor]
        self.cursor_location = self.document.end

    def action_history_next(self) -> None:
        if self._cursor is None:
            return
        self._cursor += 1
        if self._cursor >= len(self._history):
            self._cursor = None
            self.text = ""
        else:
            self.text = self._history[self._cursor]
        self.cursor_location = self.document.end


class Composer(Horizontal):
    def compose(self):
        yield Static("❯", id="prompt")
        yield PromptInput()

    @property
    def input(self) -> PromptInput:
        return self.query_one(PromptInput)

    def focus_input(self) -> None:
        self.input.focus()

    def remember(self, text: str) -> None:
        self.input.remember(text)

    def set_busy(self, busy: bool) -> None:
        self.set_class(busy, "busy")
        self.input.disabled = busy
        self.input.placeholder = BUSY_PLACEHOLDER if busy else IDLE_PLACEHOLDER
        if not busy:
            self.call_after_refresh(self.input.focus)
