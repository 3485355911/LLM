"""技能工具：loadSkill 按需读 SKILL.md / 附件；createSkill 按自然语言写新技能。"""

from __future__ import annotations

import re
from pathlib import Path

from core.skills import SKILL_FILE, discover_skills, load_skill_file
from core.tools.base import ToolRegistry, ToolSpec

_NAME_RE = re.compile(r"^[a-z0-9-]+$")
_MAX_NAME_LEN = 64
_MAX_CONTEXT = 200_000


def build_skill_registry(skills_root: Path | str) -> ToolRegistry:
    root = Path(skills_root)

    def _current_skills():
        return discover_skills(root)

    def load_skill(name: str, filename: str | None = None) -> str:
        return load_skill_file(_current_skills(), name, filename)

    def create_skill(name: str, skillContext: str) -> str:
        return _create_skill(root, _current_skills(), name, skillContext)

    specs = [
        ToolSpec(
            "loadSkill",
            f"加载指定技能的完整说明。只传 name 时返回该技能的 {SKILL_FILE} 全文；"
            "再传 filename 时读取该技能目录内的附加文件",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "技能名称"},
                    "filename": {"type": "string", "description": "可选，附件文件名"},
                },
                "required": ["name"],
            },
            load_skill,
        ),
        ToolSpec(
            "createSkill",
            "创建新技能到 .agents/skills/<name>/SKILL.md。这是创建技能的唯一工具——"
            "禁止用 runcli 或文件工具代替。先根据用户描述起草完整 SKILL.md"
            "（YAML frontmatter + 规则正文），再一次性写入。",
            {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "技能目录名，小写字母、数字和连字符，例如 officecli、meeting-summary",
                    },
                    "skillContext": {
                        "type": "string",
                        "description": "SKILL.md 全文（YAML frontmatter 以 --- 开头 --- 结尾，正文紧随其后）",
                    },
                },
                "required": ["name", "skillContext"],
            },
            create_skill,
        ),
    ]
    return ToolRegistry(*specs)


def _create_skill(
    root: Path, existing: list, name: str, skill_context: str
) -> str:
    name = name.strip()
    if not name:
        return "name 不能为空"
    if len(name) > _MAX_NAME_LEN:
        return f"name 过长（{len(name)}），上限 {_MAX_NAME_LEN}"
    if not _NAME_RE.match(name):
        return "name 只能使用小写字母、数字和连字符"

    skill_context = skill_context.strip("\ufeff")
    if not skill_context.strip():
        return "skillContext 不能为空"
    if len(skill_context) > _MAX_CONTEXT:
        return f"skillContext 过长（{len(skill_context)} 字符），上限 {_MAX_CONTEXT}"

    lines = skill_context.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return "skillContext 必须以 YAML frontmatter 开头（--- 开头，含 name、description 字段，再 --- 结尾）"
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return "skillContext 缺少 frontmatter 结束分隔符 ---"
    header_text = "\n".join(lines[1:end_idx])
    meta: dict[str, str] = {}
    for raw in header_text.splitlines():
        key, _, value = raw.partition(":")
        if _:
            meta[key.strip()] = value.strip().strip('"').strip("'")
    if meta.get("name", "").strip() != name:
        return f"frontmatter 里的 name 必须和目录名 {name} 一致"
    if not meta.get("description", "").strip():
        return "frontmatter 里缺少 description 字段"

    target_dir = root / name
    target_file = target_dir / SKILL_FILE
    if target_file.exists():
        return f"技能 {name} 已存在（{target_file}），如需修改请先 loadSkill 再 writeFile 覆盖"
    if target_dir.exists() and any(target_dir.iterdir()):
        return f"目录 {target_dir} 已存在且非空"

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file.write_text(skill_context, encoding="utf-8")
    except OSError as exc:
        return f"写入失败：{exc}"

    return (
        f"已创建技能 {name}：{target_file}\n"
        f"- description：{meta.get('description','')}\n"
        "后续可直接 loadSkill 加载该技能。"
    )
