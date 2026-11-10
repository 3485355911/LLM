"""Slash 命令注册表：集中维护所有 /命令 的元数据。

TUI 的 _handle_command 从本模块查表，Composer 的自动补全面板也用同一份数据。
新增命令只需加一个 Command 实例并注册，不用改 UI。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True, slots=True)
class Command:
    name: str             # "/compact"
    description: str      # 简短描述（补全面板用）
    category: str = "其他"  # "会话" / "上下文" / "界面" / "调试" / "其他"
    args_hint: str = ""   # 用法提示（如 " [title]"）


# ---------------------------------------------------------------------------
# 注册表 & 辅助
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Command] = {}


def register(cmd: Command) -> Command:
    _REGISTRY[cmd.name] = cmd
    return cmd


def get(name: str) -> Command | None:
    return _REGISTRY.get(name)


def all_commands() -> list[Command]:
    """按 category 分组返回所有已注册命令。"""
    return sorted(_REGISTRY.values(), key=lambda c: (c.category, c.name))


def search(prefix: str) -> list[Command]:
    """按前缀模糊匹配（忽略大小写）。"""
    key = prefix.lower().lstrip("/")
    results = []
    for cmd in _REGISTRY.values():
        if key in cmd.name.lower().lstrip("/") or (key and cmd.description.lower().startswith(key)):
            results.append(cmd)
    return sorted(results, key=lambda c: c.name)


# ---------------------------------------------------------------------------
# 一次性注册所有命令（保持按 category 分组）
# ---------------------------------------------------------------------------


def _register_all() -> None:
    if _REGISTRY:
        return  # 只注册一次

    # ── 会话 ─────────────────────────────────────
    register(Command("/new",     "开启全新会话，自动保存当前会话",         "会话"))
    register(Command("/resume",  "列出已保存会话并选择恢复",                "会话"))
    register(Command("/save",   "保存当前会话（可带标题，如 /save 周报）",  "会话", args_hint=" [标题]"))
    register(Command("/sessions", "查看所有已保存会话列表",                "会话"))
    register(Command("/delete", "删除一个已保存会话",                      "会话", args_hint=" <session_id>"))

    # ── 上下文 ──────────────────────────────────
    register(Command("/compact",  "压缩上下文历史，释放 token", "上下文"))
    register(Command("/context",  "查看当前上下文占用、归档、会话数", "上下文"))

    # ── 界面 ────────────────────────────────────
    register(Command("/help",    "显示所有可用命令",                         "界面"))
    register(Command("/tools",   "列出当前已注册的所有工具",                 "界面"))
    register(Command("/model",   "显示当前模型 / API / 上下文窗口",          "界面"))
    register(Command("/theme",   "切换主题（dark / light）",                 "界面", args_hint=" [dark|light]"))
    register(Command("/clear",   "清空当前对话（不保存）",                    "界面"))
    register(Command("/config",  "打开 / 显示 config.ini 路径",             "界面"))
    register(Command("/about",   "显示版本与版权",                          "界面"))

    # ── 调试 ────────────────────────────────────
    register(Command("/reset",   "重置会话（同 /clear 的别名）",            "调试"))
    register(Command("/export",  "把当前对话导出为 Markdown 文件",           "调试", args_hint=" [filename.md]"))
    register(Command("/debug",   "显示诊断信息（token / 工具 / MCP）",       "调试"))
    register(Command("/status",  "查看当前 agent 内部状态",                  "调试"))

    # ── 控制 ────────────────────────────────────
    register(Command("/quit",    "退出 Lagent",                             "控制"))
    register(Command("/exit",    "退出 Lagent（/quit 别名）",                "控制"))


_register_all()
