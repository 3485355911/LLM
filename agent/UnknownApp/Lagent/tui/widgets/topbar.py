"""顶部品牌栏：显示模型、cwd、上下文占用（含可视化进度）。"""

from __future__ import annotations

from rich.markup import escape
from textual.containers import Horizontal
from textual.widgets import Static

from core.agent import Agent
from core.config import LLMConfig
from tui.theme import Palette


def _fmt_tokens(n: int) -> str:
    if n < 1_000:
        return f"{n}"
    if n < 10_000:
        return f"{n / 1_000:.1f}k"
    return f"{n / 1_000:.0f}k"


def _make_bar(pct: float, width: int) -> str:
    """做一个 ANSI 进度条，width 个字符宽，pct 0.0~1.0。"""
    filled = int(round(pct * width))
    return "█" * filled + "░" * (width - filled)


class TopBar(Horizontal):
    def __init__(self, config: LLMConfig, cwd: str, palette: Palette, agent: Agent | None = None) -> None:
        super().__init__(id="topbar")
        self._config = config
        self._cwd = cwd
        self._palette = palette
        self._agent = agent

    def set_agent(self, agent: Agent) -> None:
        self._agent = agent

    def compose(self):
        yield Static(self._brand(), id="brand")
        yield Static(self._meta(), id="meta")

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.query_one("#brand", Static).update(self._brand())
        self.query_one("#meta", Static).update(self._meta())

    def refresh_meta(self) -> None:
        try:
            self.query_one("#meta", Static).update(self._meta())
        except Exception:
            pass

    def _brand(self) -> str:
        p = self._palette
        return (
            f"[bold {p.accent}]◆ LAGENT[/]"
            f"  [{p.text_faint}]modular agent console[/]"
        )

    def _meta(self) -> str:
        p = self._palette
        sep = f"[{p.border_soft}] │ [/]"
        parts = []

        # 模型
        model_flag = " [italic]" + p.yellow + "●模板[/]" if self._config.is_mock else ""
        parts.append(f"[{p.accent_soft}]{escape(self._config.model_name)}[/]{model_flag}")

        # cwd（缩短）
        cwd_display = escape(self._cwd)
        parts.append(f"[{p.text_dim}]{cwd_display}[/]")

        # 上下文进度条（有 agent 时才显示）
        if self._agent is not None:
            used = self._agent.estimate_context_tokens()
            window = self._config.context_window
            used_k = _fmt_tokens(used)
            window_k = _fmt_tokens(window)
            pct = used / window if window > 0 else 0.0

            if pct >= 1.0:
                tone = p.red
                bar_tone = p.red
            elif pct >= self._agent._threshold_pct:
                tone = p.yellow
                bar_tone = p.yellow
            else:
                tone = p.green
                bar_tone = p.accent

            bar = _make_bar(min(pct, 1.0), 8)
            parts.append(f"[{p.text_faint}]ctx[/] [{bar_tone}]{bar}[/] [{tone}]{pct*100:.0f}%[/]")

        return sep.join(parts)
