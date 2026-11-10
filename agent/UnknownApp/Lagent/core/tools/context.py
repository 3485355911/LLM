"""上下文检索工具：让 LLM 在压缩后仍能回溯历史。

与 core/context.py 里的 ContextSearch 配合，暴露成 ToolSpec。
"""

from __future__ import annotations

from pathlib import Path

from core.context import ContextArchive, ContextSearch
from core.tools.base import ToolRegistry, ToolSpec


def build_context_registry(session_dir: Path) -> ToolRegistry:
    archive = ContextArchive(session_dir)
    search = ContextSearch(archive)

    async def recall_context(text: str, id: str | None = None) -> str:
        hits = search.search(text, archive_id=id)
        if not hits:
            scope = f"归档 {id}" if id else "所有归档"
            return f"在{scope}中未找到与“{text}”相关的记录。"
        # 截断输出避免占满上下文
        lines = [f"共命中 {len(hits)} 条（最多展示 15 条）："]
        for h in hits:
            lines.append(
                f"- 【归档 {h['archive_id']}】role={h['role']} "
                f"(msg#{h['message_index']}): {h['snippet']}"
            )
        return "\n".join(lines)

    async def list_archives() -> str:
        items = archive.list()
        if not items:
            return "当前没有任何历史归档。"
        lines = ["可用上下文归档："]
        for aid, count, created in items:
            lines.append(f"- {aid}  消息数={count}  创建时间={created}")
        return "\n".join(lines)

    return ToolRegistry(
        ToolSpec(
            name="recallContext",
            description=(
                "在历史上下文归档中检索关键词。当你发现压缩摘要缺少某些历史细节时，"
                "可调用此工具回溯原始对话记录。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": (
                            "可选。指定归档编号（YYYYMMDD-HHMMSS 格式）。"
                            "不填则在所有归档中检索。"
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": "必需。需要查找的关键词或文本内容（大小写不敏感）。",
                    },
                },
                "required": ["text"],
            },
            handler=recall_context,
        ),
        ToolSpec(
            name="listContextArchives",
            description="列出所有历史上下文归档，含归档编号、消息数量和创建时间。",
            parameters={
                "type": "object",
                "properties": {},
            },
            handler=list_archives,
        ),
    )
