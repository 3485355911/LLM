"""文件系统工具集（由原 main.py 拆分而来）。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from core.tools.base import ToolRegistry, ToolSpec

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".cs",
    ".go", ".rs", ".rb", ".php", ".sh", ".bat", ".ps1",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml", ".html",
    ".htm", ".css", ".scss", ".less", ".csv", ".log",
    ".sql", ".r", ".scala", ".swift", ".kt",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".pdf", ".zip",
    ".tar", ".gz", ".7z", ".exe", ".dll", ".bin", ".pyc",
}

MAX_READ_CHARS = 50_000


def get_cwd() -> str:
    return os.getcwd()


def list_dir(dir: str | None = None) -> str:
    d = dir or os.getcwd()
    p = Path(d)
    if not p.exists():
        return f"目录不存在：{d}"
    if not p.is_dir():
        return f"不是目录：{d}"
    lines = []
    for item in sorted(p.iterdir()):
        tag = "<DIR>" if item.is_dir() else f"<FILE {item.suffix or '(no-ext)'}>"
        lines.append(f"{tag}  {item.name}")
    return "\n".join(lines) if lines else "(空目录)"


def get_file_type(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"路径不存在：{path}"
    if p.is_dir():
        return "目录（无文件类型）"
    ext = p.suffix.lower()
    kind = "纯文本" if ext in TEXT_EXTENSIONS else "二进制或未知类型"
    return f"扩展名：{ext or '(无)'}，类型：{kind}，大小：{p.stat().st_size} 字节"


def read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"路径不存在：{path}"
    if p.is_dir():
        return "路径是目录，不是文件"
    ext = p.suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return f"文件类型 {ext} 不是纯文本，不支持读取"
    for encoding in ("utf-8", "gbk"):
        try:
            content = p.read_text(encoding=encoding)
            if len(content) > MAX_READ_CHARS:
                content = content[:MAX_READ_CHARS] + f"\n...（文件过长，已截断到前 {MAX_READ_CHARS} 字符）"
            return content
        except UnicodeDecodeError:
            continue
    return "无法以 UTF-8 或 GBK 解码该文件，可能是二进制"


def create_file(dir: str, filename: str, content: str | None = None) -> str:
    directory = Path(dir)
    directory.mkdir(parents=True, exist_ok=True)
    fp = directory / filename
    if fp.exists():
        return f"文件已存在：{fp}"
    if content is None:
        fp.touch()
        return f"已创建空文件：{fp}"
    fp.write_text(content, encoding="utf-8")
    return f"已创建文件：{fp}，写入 {len(content)} 字符"


def write_file(path: str, content: str) -> str:
    p = Path(path)
    if p.is_dir():
        return "路径是目录，不是文件"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"已写入 {len(content)} 字符到 {p}"


def create_dir(path: str) -> str:
    p = Path(path)
    if p.exists():
        return f"已存在：{p}"
    p.mkdir(parents=True)
    return f"已创建目录：{p}"


def remove_dir(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"路径不存在：{path}"
    if not p.is_dir():
        return "路径不是目录"
    shutil.rmtree(p)
    return f"已删除目录：{p}"


def remove_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"路径不存在：{path}"
    if p.is_dir():
        return "路径是目录，请用 removeDir"
    p.unlink()
    return f"已删除文件：{p}"


def rename_path(old: str, new: str) -> str:
    source, target = Path(old), Path(new)
    if not source.exists():
        return f"路径不存在：{old}"
    if target.exists():
        return f"目标已存在：{new}"
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return f"已重命名：{source} -> {target}"


def _no_args() -> dict:
    return {"type": "object", "properties": {}}


def _path_args(name: str = "path", description: str = "路径") -> dict:
    return {"type": "object", "properties": {name: {"type": "string", "description": description}}, "required": [name]}


def build_filesystem_registry() -> ToolRegistry:
    """构建文件系统工具注册表。"""
    return ToolRegistry(
        ToolSpec("getCwd", "获取当前工作目录", _no_args(), get_cwd),
        ToolSpec(
            "listDir",
            "列出指定目录下所有文件和子目录，不传 dir 时默认列当前目录",
            {
                "type": "object",
                "properties": {
                    "dir": {"type": "string", "description": "目录路径，如 C:\\Users\\docs 或 /home/user/docs"},
                },
            },
            list_dir,
        ),
        ToolSpec("getFileType", "获取指定文件的文件类型（扩展名 + MIME-like 简要描述）", _path_args(), get_file_type),
        ToolSpec(
            "readFile",
            "读取指定文件的内容（仅支持纯文本格式文件，如 .txt .py .md .json .yaml .csv 等）",
            _path_args(),
            read_file,
        ),
        ToolSpec(
            "createFile",
            "根据指定目录和文件名创建新文件，可同时写入初始内容（文本）",
            {
                "type": "object",
                "properties": {
                    "dir": {"type": "string", "description": "目录路径，不存在时会自动创建"},
                    "filename": {"type": "string", "description": "文件名"},
                    "content": {"type": "string", "description": "可选，写入文件的初始文本内容"},
                },
                "required": ["dir", "filename"],
            },
            create_file,
        ),
        ToolSpec(
            "writeFile",
            "覆盖写入指定文件的内容（仅支持纯文本格式文件）",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件完整路径"},
                    "content": {"type": "string", "description": "要写入的文本内容"},
                },
                "required": ["path", "content"],
            },
            write_file,
        ),
        ToolSpec("createDir", "创建新目录，不存在的父目录会一并创建", _path_args(), create_dir),
        ToolSpec("removeDir", "删除目录（包括其下所有内容，即使非空）", _path_args(), remove_dir),
        ToolSpec("removeFile", "删除指定文件", _path_args(), remove_file),
        ToolSpec(
            "renamePath",
            "重命名文件或目录，也可用于移动到同一磁盘上的新路径",
            {
                "type": "object",
                "properties": {
                    "old": {"type": "string", "description": "原路径"},
                    "new": {"type": "string", "description": "新路径（含新名字）"},
                },
                "required": ["old", "new"],
            },
            rename_path,
        ),
    )
