"""上下文归档、压缩 Prompt、token 估算、全文检索。

本模块与任何 Agent / UI 解耦，纯函数 + 纯工具类。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 压缩专用 Prompt
# ---------------------------------------------------------------------------

COMPACT_SYSTEM_PROMPT = (
    "你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，"
    "需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。\n\n"
    "请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5000 tokens 的 Markdown 摘要。\n\n"
    "摘要应重点保留以下内容：\n"
    "1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？\n"
    "2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？\n"
    "3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？\n"
    "4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。\n"
    "5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。\n"
    "6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。\n\n"
    "请遵守以下要求：\n"
    "- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。\n"
    "- 对已经验证的事实与尚未验证的推测作出明确区分。\n"
    "- 不要将计划完成的任务描述为已经完成。\n"
    "- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。\n"
    "- 对失败的尝试，只保留有助于避免重复错误的信息。\n"
    "- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。\n"
    "- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 recallContext 工具重新检索。\n"
    "- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。\n\n"
    "**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"
)


def build_compact_user_prompt(history_text: str) -> str:
    """把压缩用的 user prompt 拼好，带上历史。"""
    return (
        "以下是当前会话的完整历史（包含用户、Agent、工具调用、工具返回），"
        "请依据上面的规则生成压缩摘要。\n\n"
        "----- 会话历史开始 -----\n"
        f"{history_text}\n"
        "----- 会话历史结束 -----"
    )


def messages_to_text(messages: list[dict]) -> str:
    """把 messages 列表序列化成可读文本，便于喂给压缩 LLM。"""
    lines: list[str] = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        if role == "system":
            continue  # system 会在 system prompt 里单独传，不进压缩历史
        lines.append(f"[{i}] role={role}")
        content = msg.get("content") or ""
        if content:
            lines.append(str(content))
        if role == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                name = tc.get("function", {}).get("name", "")
                args = tc.get("function", {}).get("arguments", "")
                lines.append(f"  → 调用工具 {name} 参数: {args}")
        lines.append("")
    return "\n".join(lines)


def archive_note(archive_id: str, dt: datetime | None = None) -> str:
    """压缩摘要末尾的归档说明，让后续 Agent 知道去哪找原始记录。"""
    stamp = (dt or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"\n\n---\n\n"
        f"⚠️ 此前上下文已于 **{stamp}** 完成压缩，"
        f"原始上下文保存在编号为 `{archive_id}` 的归档文件中。"
        f"如需查找历史信息，请使用 `recallContext` 工具。"
    )


# ---------------------------------------------------------------------------
# 归档（JSONL）
# ---------------------------------------------------------------------------

class ContextArchive:
    """把当前会话的原始上下文保存到 .agents/context/<id>.jsonl。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def next_id() -> str:
        return datetime.now().strftime("%Y%m%d-%H%M%S")

    def save(self, archive_id: str, messages: list[dict]) -> Path:
        path = self.root / f"{archive_id}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            meta = {"id": archive_id, "created_at": datetime.now().isoformat()}
            f.write(json.dumps({"type": "meta", **meta}, ensure_ascii=False) + "\n")
            for msg in messages:
                f.write(json.dumps({"type": "message", "data": msg}, ensure_ascii=False) + "\n")
        return path

    def list_ids(self) -> list[str]:
        ids = []
        for p in sorted(self.root.glob("*.jsonl")):
            ids.append(p.stem)
        return ids

    def load(self, archive_id: str) -> list[dict]:
        path = self.root / f"{archive_id}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"归档不存在：{path}")
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    def list(self) -> list[tuple[str, int, str]]:
        """返回 [(id, 消息数, 创建时间), ...]。"""
        results = []
        for path in sorted(self.root.glob("*.jsonl")):
            count = 0
            created = ""
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    if obj.get("type") == "meta":
                        created = obj.get("created_at", "")
                    elif obj.get("type") == "message":
                        count += 1
            except Exception:
                pass
            results.append((path.stem, count, created))
        return results


# ---------------------------------------------------------------------------
# 全文检索
# ---------------------------------------------------------------------------

class ContextSearch:
    """在归档里做 Python 原生关键词检索，返回命中片段。"""

    MAX_RESULTS = 15
    MAX_SNIPPET_LEN = 300

    def __init__(self, archive: ContextArchive) -> None:
        self.archive = archive

    def search(self, text: str, archive_id: str | None = None) -> list[dict]:
        text = text.strip()
        if not text:
            return []
        ids = [archive_id] if archive_id else self.archive.list_ids()
        hits: list[dict] = []
        for aid in ids:
            try:
                records = self.archive.load(aid)
            except FileNotFoundError:
                continue
            for idx, rec in enumerate(records):
                if rec.get("type") != "message":
                    continue
                msg = rec.get("data", {})
                content = msg.get("content") or ""
                if text.lower() in content.lower():
                    hits.append(
                        {
                            "archive_id": aid,
                            "role": msg.get("role", "?"),
                            "message_index": idx,
                            "snippet": _highlight(content, text),
                        }
                    )
                if len(hits) >= self.MAX_RESULTS:
                    return hits
        return hits


def _highlight(text: str, needle: str) -> str:
    """返回匹配片段的邻近上下文（前后各若干字）。"""
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return text[:ContextSearch.MAX_SNIPPET_LEN]
    half = ContextSearch.MAX_SNIPPET_LEN // 2
    start = max(0, idx - half)
    end = min(len(text), idx + len(needle) + half)
    snippet = text[start:end]
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


# ---------------------------------------------------------------------------
# Token 估算
# ---------------------------------------------------------------------------

def estimate_tokens(messages: list[dict]) -> int:
    """粗略估算当前 messages 的 token 数。

    OpenAI 系模型在英文场景下约 4 chars = 1 token，中文略多。
    为了保持零外部依赖，这里直接用字符数除以 3.5 作为统一估算。
    """
    total = 0
    for m in messages:
        content = m.get("content") or ""
        tool_calls = m.get("tool_calls") or []
        for tc in tool_calls:
            content += tc.get("function", {}).get("name", "")
            content += tc.get("function", {}).get("arguments", "")
        # OpenAI chat 每条消息有约 4 tokens 的固定开销
        total += 4
        total += max(1, int(len(content) / 3.5))
    return total
