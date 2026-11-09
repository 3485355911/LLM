"""网页抓取：curl 拉 HTML → trafilatura 提正文（自动处理中文编码）。"""

from __future__ import annotations

import asyncio
import re
import subprocess
from typing import Final

from core.tools.base import ToolRegistry, ToolSpec

MAX_CHARS: Final[int] = 15_000  # 平衡完整度与 token
MIN_CONTENT: Final[int] = 100

# 搜索引擎/跳转域名拦截
SEARCH_ENGINE_HOSTS = (
    "bing.com/search", "baidu.com/s?", "baidu.com/link", "google.com/search",
    "so.com/", "sogou.com/web", "sogou.com/sie", "search.360.cn",
    "duckduckgo.com/?q", "yandex.com/search", "search.yahoo.com",
)


def _decode_html(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            text = raw.decode(enc)
            m = re.search(rb'(?:charset|encoding)\s*[=:]\s*["\']?([\w\-]+)', raw[:2048], re.I)
            if m:
                declared = m.group(1).decode("ascii", errors="ignore").lower()
                if declared in ("gbk", "gb2312", "gb18030", "windows-1252"):
                    return raw.decode("gb18030", errors="replace")
            return text
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


async def fetch_web(url: str) -> str:
    lower = url.lower()
    if any(bad in lower for bad in SEARCH_ENGINE_HOSTS):
        return "该 URL 是搜索引擎结果页，请改用 searchweb 工具。"

    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-sL", "--max-time", "20",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            url,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
    except FileNotFoundError:
        return "抓取失败：未安装 curl"
    except asyncio.TimeoutError:
        return "抓取超时（20s）"
    except Exception as exc:
        return f"抓取异常：{exc}"

    if proc.returncode != 0:
        return f"抓取失败：curl 退出码 {proc.returncode}"

    html = _decode_html(stdout)
    if not html.strip():
        return "抓取失败：页面空"

    # 404 检测
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I | re.S)
    is_error = False
    if title_match:
        t = title_match.group(1).strip().lower()
        if any(k in t for k in ("404", "not found", "找不到", "页面不存在", "错误")):
            is_error = True

    # 提取正文
    try:
        import trafilatura
    except ImportError:
        return "抓取失败：未安装 trafilatura"

    markdown = ""
    if not is_error:
        markdown = trafilatura.extract(
            html, output_format="markdown", favor_recall=True, deduplicate=True,
        ) or ""

    if len(markdown) < MIN_CONTENT:
        try:
            import justext
            paras = justext.justext(
                html, justext.get_stoplist("Chinese") + justext.get_stoplist("English")
            )
            plain = "\n".join(p.text for p in paras if not p.is_boilerplate).strip()
            if len(plain) > len(markdown):
                markdown = plain
        except Exception:
            pass

    if len(markdown) < MIN_CONTENT:
        return f"无法提取有效正文，可能是 JS 渲染页或已失效"

    if len(markdown) > MAX_CHARS:
        markdown = markdown[:MAX_CHARS] + f"\n\n…（截断，原文约 {len(markdown)} 字符）"

    return f"来源：{url}\n\n{markdown}"


def build_fetch_registry() -> ToolRegistry:
    return ToolRegistry(ToolSpec(
        name="fetchweb",
        description="抓取指定网页正文转 Markdown。仅用于具体文章/文档页面，禁止搜索引擎结果页（bing/baidu/google/sogou/so.com），遇到搜索结果页改用 searchweb。",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "完整网页地址，如 https://example.com/article"},
            },
            "required": ["url"],
        },
        handler=fetch_web,
    ))
