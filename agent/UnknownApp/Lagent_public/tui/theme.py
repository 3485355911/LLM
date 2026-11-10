"""TUI 主题：深色 / 浅色调色板，同时作为 Textual 主题变量来源。

CSS 中通过 ``$变量名`` 引用调色板，Rich markup 中通过 ``Palette`` 取十六进制值，
两者共用同一份定义，避免颜色散落在各处。

设计原则：
- 深色：暖色系 accent（蓝紫）、多层级灰度、panel 与 bg 拉开层次
- 浅色：高对比度文本、柔和卡片边框、统一圆角风格
- 所有颜色值在两个主题里一一镜像，保证 /theme 切换时体验连续
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from textual.theme import Theme


@dataclass(frozen=True, slots=True)
class Palette:
    # —— 背景层级（由深到浅 / 由浅到深统一 4 级）
    bg: str
    panel: str
    panel_alt: str
    card: str
    card_alt: str
    border: str
    border_soft: str
    border_strong: str
    # —— 文字层级（由强调到淡化 4 级）
    text: str
    text_dim: str
    text_faint: str
    text_strong: str
    # —— 功能色
    accent: str
    accent_soft: str
    purple: str
    green: str
    green_soft: str
    red: str
    red_soft: str
    yellow: str
    # —— 对话卡片
    user_bg: str
    user_border: str
    assistant_bg: str
    assistant_border: str
    # —— 输入区
    input_bg: str
    input_focus_bg: str

    def css_variables(self) -> dict[str, str]:
        return {key.replace("_", "-"): value for key, value in asdict(self).items()}


# ---------------------------------------------------------------------------
# 深色主题 —— "午夜珊瑚" Midnight Coral
# 背景 #0a0c10 比原来更深一点但不是纯黑（避免 CRT 刺眼）
# accent 用柔和的青蓝 #6cb6ff（比原来的 #7aa2f7 更不刺眼）
# ---------------------------------------------------------------------------

DARK = Palette(
    bg="#0a0c10",
    panel="#10141b",
    panel_alt="#141a24",
    card="#121621",
    card_alt="#151a26",
    border="#1e2532",
    border_soft="#252d3d",
    border_strong="#3a4560",
    text="#cdd5e0",
    text_dim="#8b97ab",
    text_faint="#5e6a80",
    text_strong="#f0f4ff",
    accent="#6cb6ff",
    accent_soft="#9cccff",
    purple="#b79aff",
    green="#8ee08e",
    green_soft="#20402a",
    red="#ff7b8a",
    red_soft="#3a2030",
    yellow="#ffcf70",
    user_bg="#1a2332",
    user_border="#3c5278",
    assistant_bg="#141922",
    assistant_border="#2a3242",
    input_bg="#0e131b",
    input_focus_bg="#121824",
)

# ---------------------------------------------------------------------------
# 浅色主题 —— "晨雾" Morning Mist
# 背景 #f7f9fc 比原来更白一点、更通透
# accent 用更鲜明的蓝 #2e6be6
# ---------------------------------------------------------------------------

LIGHT = Palette(
    bg="#f7f9fc",
    panel="#eef1f7",
    panel_alt="#ffffff",
    card="#ffffff",
    card_alt="#f5f7fb",
    border="#d4dbe8",
    border_soft="#e2e7f2",
    border_strong="#b9c3d5",
    text="#242c3a",
    text_dim="#5c6a80",
    text_faint="#9aa5b8",
    text_strong="#101828",
    accent="#2e6be6",
    accent_soft="#4a82ee",
    purple="#6d56c9",
    green="#2a8a5a",
    green_soft="#d8ecd9",
    red="#cc3a55",
    red_soft="#f2ccd4",
    yellow="#c2720e",
    user_bg="#e4edfd",
    user_border="#b4c7ec",
    assistant_bg="#ffffff",
    assistant_border="#e3e8f2",
    input_bg="#ffffff",
    input_focus_bg="#ffffff",
)

PALETTES = {"dark": DARK, "light": LIGHT}
THEME_NAMES = {"dark": "lagent-dark", "light": "lagent-light"}


def build_themes() -> list[Theme]:
    """生成深色与浅色两套 Textual 主题。"""
    return [
        _theme("dark", DARK, dark=True),
        _theme("light", LIGHT, dark=False),
    ]


def _theme(name: str, palette: Palette, *, dark: bool) -> Theme:
    return Theme(
        name=THEME_NAMES[name],
        dark=dark,
        primary=palette.accent,
        secondary=palette.purple,
        accent=palette.accent_soft,
        background=palette.bg,
        surface=palette.card,
        panel=palette.panel,
        foreground=palette.text,
        success=palette.green,
        warning=palette.yellow,
        error=palette.red,
        variables=palette.css_variables(),
    )
