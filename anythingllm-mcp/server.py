"""AnythingLLM MCP Server.

把本机 AnythingLLM 的能力通过 MCP 协议暴露给客户端，覆盖三类能力：
  1) 工作区管理      list_workspaces / create_workspace
  2) 文档上传与向量化 upload_document / embed_document / list_workspace_documents
  3) 检索与问答      ask_workspace / ask_first_workspace / vector_search

传输：Streamable HTTP（MCP 协议 2026-07-28，官方 Python SDK v2 默认协商）。

环境变量：
  ANYTHINGLLM_API_KEY   必填，AnythingLLM 的 API Key
  ANYTHINGLLM_BASE_URL  默认 http://localhost:3001
  MCP_HTTP_PORT         默认 8766
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Annotated

import httpx2
from mcp.server import MCPServer
from pydantic import Field

API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "").strip()
BASE_URL = os.environ.get("ANYTHINGLLM_BASE_URL", "http://localhost:3001").rstrip("/")
PORT = int(os.environ.get("MCP_HTTP_PORT", "8766"))
CHAT_TIMEOUT = 300.0  # 本地 Ollama 推理可能较慢
UPLOAD_TIMEOUT = 120.0  # 大文件上传与解析
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 单文件上限 20MB，避免把超大文件塞进工作区

if not API_KEY:
    sys.exit("错误：未设置环境变量 ANYTHINGLLM_API_KEY，无法启动。")

mcp = MCPServer("anythingllm-mcp", "0.2.0")
_client: httpx2.AsyncClient | None = None
_upload_client: httpx2.AsyncClient | None = None


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


def upload_client() -> httpx2.AsyncClient:
    """上传专用客户端：不预设 Content-Type，交给 multipart 自己生成边界。"""
    global _upload_client
    if _upload_client is None:
        _upload_client = httpx2.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=UPLOAD_TIMEOUT,
        )
    return _upload_client


async def workspace_slugs() -> list[dict]:
    """实时获取工作区列表（不缓存，避免顺序变化失效）。"""
    r = await client().get("/api/v1/workspaces")
    r.raise_for_status()
    return r.json().get("workspaces", [])


async def first_workspace_slug() -> str:
    workspaces = await workspace_slugs()
    if not workspaces:
        raise RuntimeError("AnythingLLM 中没有任何工作区")
    return workspaces[0]["slug"]


async def resolve_slug(explicit: str | None) -> str:
    """显式给了 slug 就用它，否则回落到第一个工作区。"""
    return explicit or await first_workspace_slug()


def _error(prefix: str, exc: Exception) -> str:
    if isinstance(exc, httpx2.TimeoutException):
        return f"错误：{prefix}超时。请稍后重试，或检查 Ollama / AnythingLLM 是否正常运行。"
    if isinstance(exc, httpx2.HTTPError):
        return f"错误：{prefix}失败（{type(exc).__name__}），请确认 AnythingLLM 已启动且地址为 {BASE_URL}。"
    return f"错误：{prefix}失败：{type(exc).__name__}: {exc}"



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


# ===================== 能力一：工作区管理 =====================


@mcp.tool(description="列出 AnythingLLM 的全部工作区（slug、名称、文档数量），用于确定后续操作的目标工作区。")
async def list_workspaces() -> str:
    try:
        workspaces = await workspace_slugs()
    except Exception as e:  # noqa: BLE001
        return _error("列工作区", e)
    if not workspaces:
        return "当前没有任何工作区。可用 create_workspace 新建。"
    lines = ["共 %d 个工作区：" % len(workspaces)]
    for w in workspaces:
        docs = w.get("documents") or []
        lines.append(f"- {w.get('slug')}｜{w.get('name') or w.get('slug')}｜文档 {len(docs)} 篇")
    return "\n".join(lines)


@mcp.tool(description="新建一个 AnythingLLM 工作区。名称建议用英文或拼音，避免 slug 生成异常。")
async def create_workspace(
    name: Annotated[str, Field(min_length=1, max_length=64, description="工作区名称，必填")],
) -> str:
    try:
        r = await client().post("/api/v1/workspace/new", json={"name": name})
        r.raise_for_status()
        data = r.json()
        slug = (data.get("workspace") or {}).get("slug") or data.get("slug") or "(未返回 slug)"
        return f"已创建工作区：{name}（slug: {slug}）"
    except Exception as e:  # noqa: BLE001
        return _error("创建工作区", e)


# ===================== 能力二：文档上传与向量化 =====================


@mcp.tool(
    description=(
        "把本机文件上传到 AnythingLLM 的文档库，并（可选）直接向量化进指定工作区。"
        "一步完成「上传 → 嵌入」，嵌入后即可被 ask_workspace 检索到。返回文档 location。"
    )
)
async def upload_document(
    file_path: Annotated[str, Field(min_length=1, description="本机文件的绝对路径，如 D:/notes/接口文档.md")],
    workspace_slug: Annotated[str | None, Field(description="目标工作区 slug；不填则用第一个工作区")] = None,
    embed: Annotated[bool, Field(description="是否上传后立即向量化嵌入，默认 true")] = True,
) -> str:
    path = Path(file_path)
    if not path.is_file():
        return f"错误：文件不存在或不是普通文件：{file_path}"
    size = path.stat().st_size
    if size == 0:
        return f"错误：文件为空：{file_path}"
    if size > MAX_UPLOAD_BYTES:
        return f"错误：文件 {size} 字节，超过上限 {MAX_UPLOAD_BYTES} 字节（20MB）。"

    try:
        with path.open("rb") as fh:
            payload = fh.read()
        r = await upload_client().post(
            "/api/v1/document/upload",
            files={"file": (path.name, payload, "application/octet-stream")},
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return _error("上传文档", e)

    if data.get("success") is False:
        return f"错误：AnythingLLM 拒绝了上传：{data.get('error') or data}"

    doc = (data.get("documents") or [{}])[0]
    location = doc.get("location")
    if not location:
        return f"错误：上传成功但未返回文档 location，无法嵌入。原始响应：{data}"

    summary = [
        f"已上传：{doc.get('title') or path.name}",
        f"location：{location}",
        f"字数：{doc.get('wordCount', '-')}　Token 估算：{doc.get('token_count_estimate', '-')}",
    ]

    if embed:
        try:
            slug = await resolve_slug(workspace_slug)
            emb = await client().post(
                f"/api/v1/workspace/{slug}/update-embeddings",
                json={"adds": [location], "deletes": []},
            )
            emb.raise_for_status()
            summary.append(f"已向量化嵌入工作区：{slug}")
        except Exception as e:  # noqa: BLE001
            summary.append(f"警告：上传成功但嵌入失败，可用 embed_document 重试。原因：{e}")

    return "\n".join(summary)


@mcp.tool(description="把已上传的文档显式向量化嵌入指定工作区（adds/deletes 语义，与 AnythingLLM API 一致）。")
async def embed_document(
    location: Annotated[str, Field(min_length=1, description="文档 location，如 custom-documents/xx.md-uuid.json")],
    workspace_slug: Annotated[str | None, Field(description="目标工作区 slug；不填则用第一个工作区")] = None,
    remove: Annotated[bool, Field(description="true 表示从工作区移除此文档，而不是加入")] = False,
) -> str:
    try:
        slug = await resolve_slug(workspace_slug)
        body = {"adds": [], "deletes": [location]} if remove else {"adds": [location], "deletes": []}
        r = await client().post(f"/api/v1/workspace/{slug}/update-embeddings", json=body)
        r.raise_for_status()
        action = "移除" if remove else "嵌入"
        return f"已在工作区 {slug} {action} 文档：{location}"
    except Exception as e:  # noqa: BLE001
        return _error("更新嵌入", e)


@mcp.tool(description="列出某工作区当前已嵌入的文档（标题与 location），用于确认上传/嵌入是否生效。")
async def list_workspace_documents(
    workspace_slug: Annotated[str | None, Field(description="工作区 slug；不填则用第一个工作区")] = None,
) -> str:
    try:
        slug = await resolve_slug(workspace_slug)
        r = await client().get(f"/api/v1/workspace/{slug}")
        r.raise_for_status()
        docs = ((r.json().get("workspace") or {}).get("documents")) or []
    except Exception as e:  # noqa: BLE001
        return _error("列工作区文档", e)
    if not docs:
        return f"工作区 {slug} 还没有文档。可用 upload_document 上传。"
    lines = [f"工作区 {slug} 共 {len(docs)} 篇文档："]
    for d in docs:
        lines.append(f"- {d.get('title') or '(无标题)'}｜{d.get('location') or ''}")
    return "\n".join(lines)


# ===================== 能力三：检索与问答 =====================


@mcp.tool(description="在指定工作区做向量检索，只返回命中的文档片段与相似度，不调用大模型，适合先看证据。")
async def vector_search(
    query: Annotated[str, Field(min_length=1, max_length=200, description="检索语句，必填")],
    workspace_slug: Annotated[str | None, Field(description="工作区 slug；不填则用第一个工作区")] = None,
    top_n: Annotated[int, Field(ge=1, le=20, description="返回条数，1-20，默认 5")] = 5,
) -> str:
    try:
        slug = await resolve_slug(workspace_slug)
        r = await client().post(
            f"/api/v1/workspace/{slug}/vector-search",
            json={"query": query, "topN": top_n, "scoreThreshold": 0},
        )
        r.raise_for_status()
        results = r.json().get("results") or []
    except Exception as e:  # noqa: BLE001
        return _error("向量检索", e)
    if not results:
        return "没有命中任何片段。可尝试换关键词，或确认文档已嵌入。"
    lines = [f"命中 {len(results)} 条："]
    for item in results[:top_n]:
        title = ((item.get("metadata") or {}).get("title")) or item.get("title") or "(无标题)"
        score = item.get("score")
        text = (item.get("text") or "").strip().replace("\n", " ")[:160]
        lines.append(f"- [{score:.3f}] {title}：{text}" if isinstance(score, (int, float)) else f"- {title}：{text}")
    return "\n".join(lines)


@mcp.tool(description="在指定工作区提问，由 AI 基于该工作区文档作答，并附引用来源标题。")
async def ask_workspace(
    question: Annotated[str, Field(min_length=1, max_length=2000, description="要提问的问题，必填")],
    workspace_slug: Annotated[str | None, Field(description="工作区 slug；不填则用第一个工作区")] = None,
) -> str:
    try:
        slug = await resolve_slug(workspace_slug)
        r = await client().post(f"/api/v1/workspace/{slug}/chat", json={"message": question, "mode": "query"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return _error("工作区问答", e)

    if data.get("error"):
        return f"工作区返回错误：{data['error']}"
    text = (data.get("textResponse") or "").strip() or "工作区中未检索到相关信息。"
    titles = [s.get("title") for s in (data.get("sources") or []) if s.get("title")]
    if titles:
        text += "\n\n来源：" + "、".join(dict.fromkeys(titles))
    return f"[工作区 {slug}] {text}"


async def main() -> None:
    print(f"AnythingLLM MCP server 监听 http://127.0.0.1:{PORT}/mcp", flush=True)
    await mcp.run_streamable_http_async(
        host="127.0.0.1", port=PORT, streamable_http_path="/mcp"
    )


if __name__ == "__main__":
    asyncio.run(main())
