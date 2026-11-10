"""会话持久化：每个会话独立目录，支持 save/load/list/delete。

与 core.context.ContextArchive 的区别：
- ContextArchive 是 compact 归档，只读，按时间戳命名
- SessionStore 是用户主动管理的会话，可保存/加载/切换
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SESSIONS_DIR = ".agents"
AGENTS_MD = "AGENTS.md"

# 项目级指令文件的默认长度上限：超长文件只注入前 N 字符，避免一次塞爆上下文
AGENTS_MD_MAX_CHARS = 4000

# 可通过环境变量覆盖，方便不同项目使用自己的约定文件名（如 AGENT.md / CLAUDE.md）
AGENTS_MD_ENV = "LAGENT_AGENTS_MD"
AGENTS_MD_MAX_ENV = "LAGENT_AGENTS_MD_MAX_CHARS"


def agents_md_name() -> str:
    """当前生效的项目级指令文件名，默认 AGENTS.md。"""
    return (os.environ.get(AGENTS_MD_ENV) or AGENTS_MD).strip() or AGENTS_MD


def agents_md_max_chars() -> int:
    """当前生效的注入长度上限，非法值回落到默认值。"""
    raw = os.environ.get(AGENTS_MD_MAX_ENV, "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return AGENTS_MD_MAX_CHARS
    return value if value > 0 else AGENTS_MD_MAX_CHARS


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------


class SessionStore:
    """会话持久化存储。

    目录结构::

        <root>/.agents/sessions/
            ├── <session_id>/
            │   ├── session.json      # 元数据
            │   └── messages.jsonl    # 消息列表（每行一条 JSON）
            └── ...
    """

    def __init__(self, sessions_dir: Path) -> None:
        """sessions_dir 就是最终的会话存储目录（如 <root>/.agents/sessions/）。"""
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 列表 & 元数据
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[dict[str, Any]]:
        """返回所有会话的元数据，按 last_used 倒序。"""
        results: list[dict[str, Any]] = []
        for subdir in self.sessions_dir.iterdir():
            if not subdir.is_dir():
                continue
            meta_file = subdir / "session.json"
            if not meta_file.is_file():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            meta["_path"] = str(subdir)
            results.append(meta)
        results.sort(key=lambda m: m.get("last_used", 0), reverse=True)
        return results

    def get_metadata(self, session_id: str) -> dict[str, Any] | None:
        meta_file = self.sessions_dir / session_id / "session.json"
        if not meta_file.is_file():
            return None
        try:
            return json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    # ------------------------------------------------------------------
    # 新建 / 保存 / 加载 / 删除
    # ------------------------------------------------------------------

    @staticmethod
    def new_id() -> str:
        return datetime.now().strftime("%Y%m%d-%H%M%S")

    def create(self, title: str = "") -> str:
        """创建一个空会话并返回 session_id。"""
        sid = self.new_id()
        d = self.sessions_dir / sid
        d.mkdir(parents=True, exist_ok=True)
        meta = {
            "id": sid,
            "title": title or f"会话 {sid}",
            "created_at": datetime.now().isoformat(),
            "last_used": time.time(),
            "message_count": 0,
        }
        (d / "session.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (d / "messages.jsonl").write_text("", encoding="utf-8")
        return sid

    def save(
        self,
        session_id: str,
        messages: list[dict],
        title: str | None = None,
    ) -> Path:
        """把 messages 落盘到指定会话目录。"""
        d = self.sessions_dir / session_id
        d.mkdir(parents=True, exist_ok=True)

        meta_file = d / "session.json"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                meta = {}
        else:
            meta = {
                "id": session_id,
                "title": title or f"会话 {session_id}",
                "created_at": datetime.now().isoformat(),
            }

        if title is not None:
            meta["title"] = title
        meta["last_used"] = time.time()
        meta["message_count"] = len(messages)

        meta_file.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        msgs_file = d / "messages.jsonl"
        with msgs_file.open("w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        return msgs_file

    def load(self, session_id: str) -> list[dict] | None:
        """加载一个会话的 messages，找不到返回 None。"""
        msgs_file = self.sessions_dir / session_id / "messages.jsonl"
        if not msgs_file.is_file():
            return None
        messages: list[dict] = []
        for line in msgs_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        # 更新 last_used
        meta = self.sessions_dir / session_id / "session.json"
        if meta.is_file():
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                m["last_used"] = time.time()
                meta.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        return messages

    def delete(self, session_id: str) -> bool:
        d = self.sessions_dir / session_id
        if not d.is_dir():
            return False
        try:
            for f in d.iterdir():
                f.unlink()
            d.rmdir()
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# AGENTS.md 检测
# ---------------------------------------------------------------------------


def find_agents_md(root: Path) -> Path | None:
    """从当前目录向上递归找项目级指令文件（默认 AGENTS.md），找到返回绝对路径。"""
    name = agents_md_name()
    candidates = [Path.cwd() / name, root / name]
    # 向上最多追 5 层
    current = Path.cwd().resolve()
    for _ in range(5):
        p = current / name
        candidates.append(p)
        if p.parent == current.parent:
            break
        current = current.parent
    for p in candidates:
        if p.is_file():
            return p
    return None


def load_agents_md_content(root: Path) -> tuple[str, str | None]:
    """返回 (内容, 文件路径)。找不到则返回 ("", None)。

    超过 agents_md_max_chars() 的部分会被截断，并保留一行说明，
    避免项目指令文件过长时把上下文挤爆。
    """
    p = find_agents_md(root)
    if p is None:
        return "", None
    try:
        content = p.read_text(encoding="utf-8")
    except OSError:
        return "", None

    limit = agents_md_max_chars()
    if len(content) > limit:
        dropped = len(content) - limit
        content = content[:limit] + f"\n\n…（{p.name} 已截断：原文 {len(content)} 字符，注入前 {limit} 字符，省略 {dropped} 字符）"
    return content, str(p)
