"""AnythingLLM MCP Server (MVP).

把本机 AnythingLLM「第一个工作区」的文档问答能力，通过 Streamable HTTP
暴露给 MCP 客户端。MCP 协议 2026-07-28（官方 Python SDK v2 默认协商）。

环境变量：
  ANYTHINGLLM_API_KEY   必填，AnythingLLM 的 API Key
  ANYTHINGLLM_BASE_URL  默认 http://localhost:3001
  MCP_HTTP_PORT         默认 8766
"""

import asyncio
import os
import sys

import httpx2
from mcp.server import MCPServer

API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "").strip()
BASE_URL = os.environ.get("ANYTHINGLLM_BASE_URL", "http://localhost:3001").rstrip("/")
PORT = int(os.environ.get("MCP_HTTP_PORT", "8766"))
CHAT_TIMEOUT = 300.0  # 本地 Ollama 推理可能较慢

if not API_KEY:
    sys.exit("错误：未设置环境变量 ANYTHINGLLM_API_KEY，无法启动。")

mcp = MCPServer("anythingllm-mcp", "0.1.0")
_client: httpx2.AsyncClient | None = None


def client() -> httpx2.AsyncClient:
    """进程级懒加载的 httpx2 异步客户端。"""
    global _client
    if _client is None:
        _client = httpx2.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=CHAT_TIMEOUT,
        )
    return _client


async def first_workspace_slug() -> str:
    """实时获取第一个工作区的 slug（不缓存，避免顺序变化失效）。"""
    r = await client().get("/api/v1/workspaces")
    r.raise_for_status()
    workspaces = r.json().get("workspaces", [])
    if not workspaces:
        raise RuntimeError("AnythingLLM 中没有任何工作区")
    return workspaces[0]["slug"]


@mcp.tool(
    description=(
        "向 AnythingLLM 的第一个工作区提问，基于其中已上传的文档检索后由 AI 回答。"
        "适用于询问该工作区文档中的信息。"
    )
)
async def ask_first_workspace(question: str) -> str:
    """基于第一个工作区的文档回答问题。

    Args:
        question: 要提问的问题。
    """
    try:
        slug = await first_workspace_slug()
        r = await client().post(
            f"/api/v1/workspace/{slug}/chat",
            json={"message": question, "mode": "query"},
        )
        r.raise_for_status()
        data = r.json()

        if data.get("error"):
            return f"工作区返回错误：{data['error']}"

        text = (data.get("textResponse") or "").strip()
        if not text:
            text = "工作区中未检索到相关信息。"

        # 附上引用来源标题，便于判断答案依据
        sources = data.get("sources") or []
        titles = [s.get("title") for s in sources if s.get("title")]
        if titles:
            text += "\n\n来源：" + "、".join(dict.fromkeys(titles))  # 去重保序
        return text

    except httpx2.TimeoutException:
        return "错误：模型响应超时（超过 300 秒）。请稍后重试，或检查 Ollama 是否正常运行。"
    except httpx2.HTTPError as e:
        return f"错误：无法连接 AnythingLLM（{type(e).__name__}），请确认其已启动且地址为 {BASE_URL}。"
    except Exception as e:  # noqa: BLE001 — 工具内不抛栈，统一返回可读错误
        return f"错误：{type(e).__name__}: {e}"


async def main() -> None:
    print(f"AnythingLLM MCP server 监听 http://127.0.0.1:{PORT}/mcp", flush=True)
    await mcp.run_streamable_http_async(
        host="127.0.0.1", port=PORT, streamable_http_path="/mcp"
    )


if __name__ == "__main__":
    asyncio.run(main())
