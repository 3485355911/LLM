"""Lagent 入口：装配 core 与前端，本身不承载任何业务逻辑。

目录约定：
    core/    业务核心，零界面依赖
    tui/     终端前端；未来可并列新增 web/ desktop/ mobile/ 目录
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

# Windows 上默认 ProactorEventLoop 的 socketpair 会被安全软件拦截（WinError 10013），
# 换成 SelectorEventLoop 彻底规避，textual httpx 都能正常跑
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# frozen exe（PyInstaller）用 sys.executable 的目录作为 ROOT，源码运行用 __file__
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent import Agent
from core.config import LLMConfig, ensure_config, load_config
from core.llm.client import LLMClient
from core.session import load_agents_md_content
from core.skills import discover_skills, render_catalog
from core.tools.context import build_context_registry
from core.tools.filesystem import build_filesystem_registry
from core.tools.fetchweb import build_fetch_registry
from core.tools.runcli import build_runcli_registry
from core.tools.search import build_search_registry
from core.tools.skills import build_skill_registry

# 以 main.py 所在目录为项目根目录扫描技能和 MCP 配置
DEFAULT_SKILLS_DIR = ROOT / ".agents" / "skills"
DEFAULT_CONTEXT_DIR = ROOT / ".agents" / "context"
DEFAULT_SESSIONS_DIR = ROOT / ".agents" / "sessions"

# 前端注册表：新增前端时只在这里登记「模块:启动函数」，core 无需改动
FRONTENDS = {
    "tui": "tui.app:run_tui",
    # "web": "web.app:run_web",
    # "desktop": "desktop.app:run_desktop",
    # "mobile": "mobile.app:run_mobile",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="lagent", description="Lagent · 模块化 AI 文件助手")
    parser.add_argument("--ui", default="tui", help="前端类型：tui（默认）")
    parser.add_argument("--config", help="config.ini 路径，默认自动查找")
    parser.add_argument("--max-rounds", type=int, default=None, help="单次提问的最大推理轮次")
    parser.add_argument("--skills", help="技能目录，默认为 <启动目录>\\.agents\\skills")
    return parser.parse_args(argv)


def build_agent(args: argparse.Namespace) -> tuple[Agent, LLMConfig, Path]:
    """构建 Agent，返回 (agent, config, mcp_config_path)。

    MCP 工具不在此处同步加载（避免阻塞 TUI 启动），路径交给 TUI 层异步处理。
    """
    # 1. 确保 config.ini 存在 + 读配置
    config_path, _was_missing = ensure_config(args.config)
    config = load_config(args.config)
    # 如果 CLI 传了 --max-rounds 覆盖 ini 值
    if args.max_rounds is not None:
        config = LLMConfig(
            base_url=config.base_url,
            api_key=config.api_key,
            model_name=config.model_name,
            timeout=config.timeout,
            temperature=config.temperature,
            qianfan_key=config.qianfan_key,
            context_window=config.context_window,
            max_rounds=args.max_rounds,
            is_mock=config.is_mock,
        )

    skills_root = Path(args.skills) if args.skills else DEFAULT_SKILLS_DIR

    # 2. 动态 prompt builder（每次请求时重新扫描 skills 目录）
    #    mcp_tool_infos 是一个可追加的 list，MCP 异步加载完后会往里塞
    mcp_tool_infos: list[tuple[str, str]] = []

    def _prompt_builder() -> str:
        latest_skills = discover_skills(skills_root)
        prompt = render_catalog(latest_skills)
        if mcp_tool_infos:
            prompt += "\n\n## 可用 MCP 工具\n"
            prompt += "\n".join(f"- `{name}`: {desc}" for name, desc in mcp_tool_infos)
        return prompt

    # 3. 同步加载内置工具（必须有，TUI 启动即可用）
    tools = build_filesystem_registry()
    tools.add(*build_search_registry(config.qianfan_key).all())
    tools.add(*build_fetch_registry().all())
    tools.add(*build_runcli_registry().all())
    tools.add(*build_skill_registry(skills_root).all())
    tools.add(*build_context_registry(DEFAULT_CONTEXT_DIR).all())

    # 4. 找 AGENTS.md
    agents_md_content, agents_md_path = load_agents_md_content(ROOT)

    # 5. 组装 Agent
    agent = Agent(
        llm=LLMClient(config),
        tools=tools,
        max_rounds=config.max_rounds,
        system_prompt=_prompt_builder(),
        system_prompt_builder=_prompt_builder,
        context_window=config.context_window,
        session_dir=DEFAULT_CONTEXT_DIR,
        sessions_dir=DEFAULT_SESSIONS_DIR,
        agents_md_content=agents_md_content,
        agents_md_path=agents_md_path,
        mcp_tool_infos=mcp_tool_infos,
    )

    # 6. MCP 配置路径（交给 TUI 异步加载）
    mcp_config = ROOT / ".mcp.json"
    if not mcp_config.is_file():
        mcp_config = Path.cwd() / ".mcp.json"

    return agent, config, mcp_config


def launch(ui: str, agent: Agent, config: LLMConfig, mcp_config_path: Path) -> None:
    target = FRONTENDS.get(ui)
    if target is None:
        raise SystemExit(f"未知前端：{ui}（当前可用：{' / '.join(FRONTENDS)}）")
    module_name, func_name = target.split(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise SystemExit(f"前端 {ui} 依赖缺失：{exc}") from exc

    # run_tui 现在多接收 mcp_config_path 用于异步加载
    func = getattr(module, func_name)
    func(agent, config, mcp_config_path=mcp_config_path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        agent, config, mcp_config_path = build_agent(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        if getattr(sys, "frozen", False):
            input("按回车键退出...")
        return 1

    try:
        launch(args.ui, agent, config, mcp_config_path)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
