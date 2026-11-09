"""配置加载：集中 defaults + ini 读取 + 缺失时自动生成模板。"""

from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "config.ini"

# ---------------------------------------------------------------------------
# 集中默认值：所有 "原本硬编码在代码里" 的参数都在这里，
# 方便用户通过 config.ini 覆盖，也方便未来在 UI 里调整
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 120.0
DEFAULT_TEMPERATURE: float | None = None
DEFAULT_CONTEXT_WINDOW = 128_000
DEFAULT_MAX_ROUNDS = 12

# MCP 异步加载的超时（秒）—— 启动后最多等这么久就先显示"加载中"，
# 即使超时也不阻塞 TUI 主界面
DEFAULT_MCP_LOAD_TIMEOUT = 10.0


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """LLM 连接配置。is_mock=True 表示走的是自动生成的模板。"""

    base_url: str
    api_key: str
    model_name: str
    timeout: float = DEFAULT_TIMEOUT
    temperature: float | None = DEFAULT_TEMPERATURE
    qianfan_key: str = ""
    context_window: int = DEFAULT_CONTEXT_WINDOW
    max_rounds: int = DEFAULT_MAX_ROUNDS
    is_mock: bool = False

    @property
    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


# ---------------------------------------------------------------------------
# Mock 模板：ensure_config 找不到时写入，含注释说明每个字段用途
# ---------------------------------------------------------------------------

CONFIG_TEMPLATE = """# ======================================================================
#  Lagent 配置文件
#  启动时在当前目录自动生成。请填写 API Key 后重新启动。
# ======================================================================

[llm]
# 模型 API Key（必填）
api_key = sk-请替换为你的APIKey

# 模型提供商地址
#   DeepSeek:  https://api.deepseek.com/v1
#   OpenAI:    https://api.openai.com/v1
#   硅基流动:  https://api.siliconflow.cn/v1
base_url = https://api.deepseek.com/v1

# 模型名称
#   deepseek-chat / deepseek-reasoner / gpt-4o / qwen-plus / ...
model_name = deepseek-chat

# API 请求超时（秒）
timeout = 120

# 可选：温度 0~2，注释掉即使用模型默认值
; temperature = 0.3

# 可选：上下文窗口大小（tokens），deepseek-chat 为 128000
; context_window = 128000

# 可选：单次提问最多推理轮次
; max_rounds = 12

# 可选：千帆 apikey（百度 Qianfan 搜索工具用）
; baidu_qianfan_apikey =
"""


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def ensure_config(explicit_path: str | Path | None = None) -> tuple[Path, bool]:
    """确保 config.ini 存在。

    返回 (config_path, was_missing)。
    如果文件不存在，在 cwd 创建一份带注释的模板并返回 (Path, True)。
    """
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    candidates.append(Path.cwd() / CONFIG_NAME)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / CONFIG_NAME)
    candidates.append(Path(__file__).resolve().parent.parent / CONFIG_NAME)

    config_file = next((p for p in candidates if p.is_file()), None)
    if config_file is not None:
        return config_file, False

    # 都没有 → 在 cwd 生成模板
    config_file = Path.cwd() / CONFIG_NAME
    config_file.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return config_file, True


def load_config(path: str | Path | None = None) -> LLMConfig:
    """按 显式路径 → 当前目录 → 项目根目录 的顺序查找配置文件。

    找不到时会在 cwd 自动生成模板并返回 is_mock=True 的配置，
    让上层可以正常启动并提示用户修改，而不是直接退出。
    """
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    candidates.append(Path.cwd() / CONFIG_NAME)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / CONFIG_NAME)
    candidates.append(Path(__file__).resolve().parent.parent / CONFIG_NAME)

    config_file = next((p for p in candidates if p.is_file()), None)
    if config_file is None:
        # 兜底：在 cwd 生成模板
        config_file = Path.cwd() / CONFIG_NAME
        config_file.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        is_mock = True
    else:
        is_mock = config_file == (Path.cwd() / CONFIG_NAME) and "请替换" in config_file.read_text(
            encoding="utf-8"
        )

    parser = configparser.ConfigParser()
    parser.read(config_file, encoding="utf-8")

    if not parser.has_section("llm"):
        # 模板通常有 [llm]，这里兜底
        section = {}
        is_mock = True
    else:
        section = parser["llm"]

    api_key = os.getenv("LAGENT_API_KEY") or section.get("api_key", "") or "sk-请替换为你的APIKey"
    base_url = os.getenv("LAGENT_BASE_URL") or section.get("base_url", "") or "https://api.deepseek.com/v1"
    model_name = os.getenv("LAGENT_MODEL") or section.get("model_name", "") or "deepseek-chat"

    # 检查占位符 → 视为 mock
    if api_key.startswith("sk-请") or "请替换" in api_key:
        is_mock = True

    timeout = _read_float(section, "timeout", DEFAULT_TIMEOUT)
    temperature = _read_float(section, "temperature", None)
    qianfan_key = os.getenv("BAIDU_QIANFAN_APIKEY") or section.get("baidu_qianfan_apikey", "")
    context_window = _read_int(section, "context_window", DEFAULT_CONTEXT_WINDOW)
    max_rounds = _read_int(section, "max_rounds", DEFAULT_MAX_ROUNDS)

    return LLMConfig(
        base_url=base_url,
        api_key=api_key,
        model_name=model_name,
        timeout=timeout,
        temperature=temperature,
        qianfan_key=qianfan_key,
        context_window=context_window,
        max_rounds=max_rounds,
        is_mock=is_mock,
    )


def _read_float(section, key: str, default: float | None) -> float | None:
    raw = section.get(key, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _read_int(section, key: str, default: int) -> int:
    raw = section.get(key, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
