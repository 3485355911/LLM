"""技能发现：只解析 SKILL.md 的 YAML 头，正文留给 loadSkill 工具按需读取。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SKILL_FILE = "SKILL.md"
MAX_FILE_CHARS = 50_000

BASE_PROMPT = """你是 Lagent，一个通过 function calling 执行任务的文件助手。

【核心规则】
1. 有对应工具能做的事，必须先调工具再回复——禁止空口答应、禁止先说"我来帮你"再行动、禁止先聊天再调工具
2. 需要联网查资料 → searchweb；需要读网页正文 → fetchweb；需要读写文件 → 文件系统工具
3. 需要创建/新建技能 → 直接用 createSkill，禁止先 runcli 探测 exe、禁止先 readFile 查文档
4. **用户提到已知技能名（如 officecli、miniEncryption、daily-horoscope-2）时，第一步必须先 loadSkill 加载该技能说明，再按 SKILL.md 规则执行**
5. 需要加载已有技能 → loadSkill；想知道有什么技能可用：看系统提示开头的【可用技能】列表
6. 用户说"帮我做个 XX 技能"时，createSkill 必须是第一且唯一的工具调用，一次性写完 SKILL.md
7. 创建技能时按用户描述起草 SKILL.md 内容（可以假设 exe 路径、命令格式等，写进 skill 里让 agent 自己跑 help 探测）
8. 工具失败要直接把错误返回给用户，不要假装成功；不要卡在同一个工具上反复重试
9. 回答简洁，能一句话说清就不说两句；max 12 轮，超过就停
10. 涉及黄历、八字、命理、干支、生肖、节气、纳音等传统历算问题时，**必须优先使用 `Bazi-MCP__*` 或 `MCP-cantian-baizi__*` 前缀的 MCP 工具**（如 getChineseCalendar 查黄历、getBaziDetail 排八字），不要用 searchweb/fetchweb 去网上查，MCP 工具返回的数据更准确可靠"""


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    directory: Path


def discover_skills(root: str | Path) -> list[Skill]:
    """扫描 root 下每个 skill 子目录，只读取 frontmatter 里的 name 与 description。"""
    root = Path(root)
    if not root.is_dir():
        return []

    skills: list[Skill] = []
    for skill_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        skill_file = skill_dir / SKILL_FILE
        if not skill_file.is_file():
            continue
        try:
            meta = _read_frontmatter(skill_file)
        except OSError:
            continue
        name = meta.get("name", "").strip()
        if not name:
            continue
        skills.append(
            Skill(name=name, description=meta.get("description", "").strip(), directory=skill_dir)
        )
    return skills


def render_catalog(skills: list[Skill]) -> str:
    """清单只含 name 与 description，并告知模型用 loadSkill 取全文。"""
    lines = [BASE_PROMPT, "", "## 可用技能", ""]
    if skills:
        lines.extend(f"- `{skill.name}`: {skill.description or '（无描述）'}" for skill in skills)
    else:
        lines.append("- （当前没有已安装的技能；可用 `createSkill` 新建）")
    lines.extend(
        [
            "",
            "需要某个技能的完整规则时，调用 `loadSkill` 工具加载它（只传 name 返回 SKILL.md 全文）。",
            "技能的附加文件（模板、脚本、参考资料）也用 `loadSkill` 传 filename 读取。",
        ]
    )
    return "\n".join(lines)


def load_skill_file(skills: list[Skill], name: str, filename: str | None = None) -> str:
    """按 name 定位技能：无 filename 读 SKILL.md，有 filename 读技能目录内的文件。"""
    skill = _find_skill(skills, name)
    if skill is None:
        available = "、".join(item.name for item in skills) or "（无）"
        return f"未找到技能：{name}。可用技能：{available}"

    skill_dir = skill.directory.resolve()
    if not filename:
        return _read_text(skill_dir / SKILL_FILE)
    return _load_attachment(skill_dir, filename)


def _find_skill(skills: list[Skill], name: str) -> Skill | None:
    wanted = name.strip().lower()
    for skill in skills:
        if skill.name.lower() == wanted:
            return skill
    return None


def _load_attachment(skill_dir: Path, filename: str) -> str:
    raw = Path(filename)
    if raw.is_absolute():
        resolved = raw.resolve()
        if not _inside(resolved, skill_dir):
            return f"拒绝读取：{filename} 不在技能目录 {skill_dir.name} 内"
        if resolved.is_file():
            return _read_text(resolved)
        return f"文件不存在：{filename}"

    # 技能目录相对路径优先，其次项目（当前工作目录）相对路径
    for base in (skill_dir, Path.cwd()):
        resolved = (base / raw).resolve()
        if _inside(resolved, skill_dir) and resolved.is_file():
            return _read_text(resolved)

    # 只给了文件名时，在该技能目录内递归查找同名文件
    if raw.name:
        matches = sorted(p for p in skill_dir.rglob(raw.name) if p.is_file())
        if len(matches) == 1:
            return _read_text(matches[0])
        if len(matches) > 1:
            options = "\n".join(f"- {p.relative_to(skill_dir).as_posix()}" for p in matches)
            return f"{skill_dir.name} 内有多个名为 {raw.name} 的文件，请用 filename 指定其一：\n{options}"
    return f"未找到文件：{filename}（限制在技能目录 {skill_dir.name} 内）"


def _inside(path: Path, directory: Path) -> bool:
    return path.is_relative_to(directory)


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "gbk"):
        try:
            content = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            return f"读取失败：{exc}"
    else:
        return f"无法解码：{path.name}，可能不是文本文件"

    if len(content) > MAX_FILE_CHARS:
        return content[:MAX_FILE_CHARS] + f"\n…（文件过长，已截断到前 {MAX_FILE_CHARS} 字符）"
    return content


def _read_frontmatter(path: Path) -> dict[str, str]:
    """按行读到第二个 --- 就停，不把正文载入内存。"""
    meta: dict[str, str] = {}
    with path.open(encoding="utf-8-sig") as handle:
        if handle.readline().strip() != "---":
            return {}
        for line in handle:
            if line.strip() == "---":
                return meta
            key, separator, value = line.partition(":")
            if separator:
                meta[key.strip()] = value.strip().strip('"').strip("'")
    return {}
