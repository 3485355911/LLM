"""本地 CLI 执行工具：以当前用户权限运行任意命令行程序（shell=False）。

教学用途：无白名单/审批机制，仅限受控实验环境。
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import Final

from core.tools.base import ToolRegistry, ToolSpec

TIMEOUT: Final[int] = 60          # 单条命令最长执行秒数
MAX_CHARS: Final[int] = 6_000     # stdout/stderr 各自截断阈值


def _truncate(text: str) -> str:
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + f"\n…（截断：原文 {len(text)} 字符，仅显示前 {MAX_CHARS}）"
    return text


async def run_cli(command: str, args: list[str] | None = None) -> str:
    argv = [command, *(args or [])]  # 列表形式拼装，杜绝 shell 注入
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
    except FileNotFoundError:
        return f"执行失败：找不到程序 {command!r}"
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"执行失败：命令超时（>{TIMEOUT}s），进程已被终止"
    except Exception as exc:
        return f"执行异常：{exc}"

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    return (
        f"exit_code: {proc.returncode}\n"
        f"--- stdout ---\n{_truncate(out) or '(空)'}\n"
        f"--- stderr ---\n{_truncate(err) or '(空)'}"
    )


def build_runcli_registry() -> ToolRegistry:
    return ToolRegistry(ToolSpec(
        name="runcli",
        description="执行本机已安装的命令行程序。以 [command, *args] 列表形式、shell=False 安全执行，返回 stdout/stderr/exit_code 供判断结果。",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "程序名或可执行文件路径，如 python、git、ffmpeg"},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "参数列表，每个参数独立成项，如 [\"-V\", \"--quiet\"]",
                },
            },
            "required": ["command"],
        },
        handler=run_cli,
    ))
