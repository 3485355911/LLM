"""百度千帆 AI 搜索工具——精简输出，只返回有用信息。"""

from __future__ import annotations

import httpx

from core.tools.base import ToolRegistry, ToolSpec

MCP_URL = "https://qianfan.baidubce.com/v2/ai_search/mcp/messages"
TIMEOUT = 30
# initialize 之后的消息 endpoint 要带 session_id query 参数
MSG_URL_TEMPLATE = "https://qianfan.baidubce.com/v2/ai_search/mcp/messages?session_id={sid}"

# 需要跳过的搜索结果跳转/镜像域名（给 LLM 的工具结果不能把 URL 列表再喂回去让它二次 fetch）
SKIP_HOSTS = {"so.com", "www.so.com", "m.so.com"}


async def search_web(query: str, qianfan_key: str) -> str:
    if not qianfan_key:
        return "搜索未配置：缺少 baidu_qianfan_apikey"

    headers = {
        "Authorization": f"Bearer {qianfan_key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "Lagent", "version": "1.0"}}}
        r = await client.post(MCP_URL, headers=headers, json=init)
        if r.status_code != 200:
            return f"[搜索失败] 千帆 MCP 初始化 HTTP {r.status_code}，该工具当前不可用，请直接用你的现有知识回答，不要再重试搜索"
        session_id = (
            r.headers.get("Mcp-Session-Id")
            or r.headers.get("mcp-session-id")
            or r.json().get("result", {}).get("sessionId", "")
        )
        if not session_id:
            return "[搜索失败] 未获取到 session_id，该工具当前不可用，请直接用你的现有知识回答，不要再重试搜索"
        headers["Mcp-Session-Id"] = session_id

        # 2) call_tool AIsearch —— URL 必须带 session_id query
        call_url = MSG_URL_TEMPLATE.format(sid=session_id)
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "AIsearch", "arguments": {"query": query}}}
        r = await client.post(call_url, headers=headers, json=call)
        if r.status_code != 200:
            return f"[搜索失败] AIsearch 调用 HTTP {r.status_code}，该工具当前不可用，请直接用现有知识回答，不要再重试"

        data = r.json()

    # 解析 AIsearch 返回
    summary_text = ""
    refs: list[tuple[str, str, str]] = []  # (title, url, snippet)
    content = data.get("result", {}).get("content", [])
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            t = item.get("text", "").strip()
            if t and not summary_text:
                summary_text = t
            continue
        sc = item.get("structuredContent") or {}
        if not summary_text:
            summary_text = (sc.get("summary") or sc.get("answer") or "").strip()
        for ref in sc.get("references") or sc.get("ReferenceDocuments") or []:
            url = ref.get("url", "") or ref.get("link", "")
            # 过滤跳转域名，优先真实来源
            if any(h in url for h in SKIP_HOSTS):
                continue
            title = (ref.get("title") or "").strip()
            snippet = (ref.get("summary") or ref.get("snippet") or "").strip()
            refs.append((title, url, snippet))

    # 去重 + 截断
    seen: set[str] = set()
    clean_refs: list[tuple[str, str, str]] = []
    for t, u, s in refs:
        if u and u in seen:
            continue
        if u:
            seen.add(u)
        # snippet 截断到 120 字以内
        s = s[:120] + ("…" if len(s) > 120 else "")
        clean_refs.append((t, u, s))

    parts: list[str] = []
    if summary_text:
        parts.append(f"【总结】{summary_text[:500]}")
    if clean_refs:
        parts.append("【来源】")
        for t, u, s in clean_refs[:5]:
            line = f"- {t}" if t else "- (无标题)"
            if s:
                line += f"\n  {s}"
            if u:
                line += f"\n  {u}"
            parts.append(line)

    return "\n".join(parts).strip() if parts else "无相关结果"


def build_search_registry(qianfan_key: str) -> ToolRegistry:
    async def _handler(query: str) -> str:
        return await search_web(query, qianfan_key)

    registry = ToolRegistry()
    registry.add(ToolSpec(
        name="searchweb",
        description="搜索互联网获取最新信息（新闻/时事/技术/产品资料）。优先使用此工具，不要用 fetchweb 去抓搜索引擎页面。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，简洁明确，可拆成多个工具调用分别搜索"},
            },
            "required": ["query"],
        },
        handler=_handler,
    ))
    return registry
