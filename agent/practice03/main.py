import configparser
import json
import os
import shutil
import time
from pathlib import Path
import requests

config = configparser.ConfigParser()
config.read("config.ini")
cfg = config["llm"]

tools = [
    {
        "type": "function",
        "function": {
            "name": "getCwd",
            "description": "获取当前工作目录",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listDir",
            "description": "列出指定目录下所有文件和子目录，不传 dir 时默认列当前目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir": {"type": "string", "description": "目录路径，如 C:\\Users\\docs 或 /home/user/docs"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getFileType",
            "description": "获取指定文件的文件类型（扩展名+MIME-like 简要描述）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件完整路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "readFile",
            "description": "读取指定文件的内容（仅支持纯文本格式文件，如 .txt .py .md .json .yaml .csv 等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件完整路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createFile",
            "description": "根据指定目录和文件名创建新文件，可同时写入初始内容（文本）",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir": {"type": "string", "description": "目录路径，不存在时会自动创建"},
                    "filename": {"type": "string", "description": "文件名"},
                    "content": {"type": "string", "description": "可选，写入文件的初始文本内容"},
                },
                "required": ["dir", "filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "writeFile",
            "description": "覆盖写入指定文件的内容（仅支持纯文本格式文件）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件完整路径"},
                    "content": {"type": "string", "description": "要写入的文本内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createDir",
            "description": "创建新目录，不存在的父目录会一并创建",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "removeDir",
            "description": "删除目录（包括其下所有内容，即使非空）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "removeFile",
            "description": "删除指定文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件完整路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "renamePath",
            "description": "重命名文件或目录，也可用于移动到同一磁盘上的新路径",
            "parameters": {
                "type": "object",
                "properties": {
                    "old": {"type": "string", "description": "原路径"},
                    "new": {"type": "string", "description": "新路径（含新名字）"},
                },
                "required": ["old", "new"],
            },
        },
    },
]


def getCwd():
    return os.getcwd()


def listDir(dir=None):
    d = dir or os.getcwd()
    p = Path(d)
    if not p.exists():
        return f"目录不存在：{d}"
    if not p.is_dir():
        return f"不是目录：{d}"
    items = sorted(p.iterdir())
    lines = []
    for it in items:
        tag = "<DIR>" if it.is_dir() else f"<FILE {it.suffix or '(no-ext)'}>"
        lines.append(f"{tag}  {it.name}")
    return "\n".join(lines) if lines else "(空目录)"


def getFileType(path):
    p = Path(path)
    if not p.exists():
        return f"路径不存在：{path}"
    if p.is_dir():
        return f"目录（无文件类型）"
    ext = p.suffix.lower()
    # 常见纯文本扩展名，其余归为"二进制或未知"
    text_exts = {
        ".txt", ".md", ".markdown", ".rst",
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".cs",
        ".go", ".rs", ".rb", ".php", ".sh", ".bat", ".ps1",
        ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml", ".html",
        ".htm", ".css", ".scss", ".less", ".csv", ".log",
        ".sql", ".r", ".scala", ".swift", ".kt",
    }
    if ext in text_exts:
        kind = "纯文本"
    else:
        kind = "二进制或未知类型"
    size = p.stat().st_size
    return f"扩展名：{ext or '(无)'}，类型：{kind}，大小：{size} 字节"


def readFile(path):
    p = Path(path)
    if not p.exists():
        return f"路径不存在：{path}"
    if p.is_dir():
        return "路径是目录，不是文件"
    ext = p.suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".pdf", ".zip",
               ".tar", ".gz", ".7z", ".exe", ".dll", ".bin", ".pyc"}:
        return f"文件类型 {ext} 不是纯文本，不支持读取"
    # 用 UTF-8 读取，失败则尝试 GBK（兼容 Windows 本地编码）
    for enc in ("utf-8", "gbk"):
        try:
            content = p.read_text(encoding=enc)
            # 超大文件截断
            if len(content) > 50000:
                content = content[:50000] + "\n...（文件过长，已截断到前 50000 字符）"
            return content
        except UnicodeDecodeError:
            continue
    return f"无法以 UTF-8 或 GBK 解码该文件，可能是二进制"


def createFile(dir, filename, content=None):
    d = Path(dir)
    d.mkdir(parents=True, exist_ok=True)
    fp = d / filename
    if fp.exists():
        return f"文件已存在：{fp}"
    if content is None:
        fp.touch()
        return f"已创建空文件：{fp}"
    fp.write_text(content, encoding="utf-8")
    return f"已创建文件：{fp}，写入 {len(content)} 字符"


def writeFile(path, content):
    p = Path(path)
    if p.is_dir():
        return "路径是目录，不是文件"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"已写入 {len(content)} 字符到 {p}"


def createDir(path):
    p = Path(path)
    if p.exists():
        return f"已存在：{p}"
    p.mkdir(parents=True)
    return f"已创建目录：{p}"


def removeDir(path):
    p = Path(path)
    if not p.exists():
        return f"路径不存在：{path}"
    if not p.is_dir():
        return "路径不是目录"
    shutil.rmtree(p)
    return f"已删除目录：{p}"


def removeFile(path):
    p = Path(path)
    if not p.exists():
        return f"路径不存在：{path}"
    if p.is_dir():
        return "路径是目录，请用 removeDir"
    p.unlink()
    return f"已删除文件：{p}"


def renamePath(old, new):
    o, n = Path(old), Path(new)
    if not o.exists():
        return f"路径不存在：{old}"
    if n.exists():
        return f"目标已存在：{new}"
    n.parent.mkdir(parents=True, exist_ok=True)
    o.rename(n)
    return f"已重命名：{o} -> {n}"


TOOL_MAP = {
    "getCwd": lambda _a: getCwd(),
    "listDir": lambda a: listDir(a.get("dir")),
    "getFileType": lambda a: getFileType(a["path"]),
    "readFile": lambda a: readFile(a["path"]),
    "createFile": lambda a: createFile(a["dir"], a["filename"], a.get("content")),
    "writeFile": lambda a: writeFile(a["path"], a["content"]),
    "createDir": lambda a: createDir(a["path"]),
    "removeDir": lambda a: removeDir(a["path"]),
    "removeFile": lambda a: removeFile(a["path"]),
    "renamePath": lambda a: renamePath(a["old"], a["new"]),
}


messages = []
while True:
    question = input("请输入问题（直接回车退出）：")
    if not question.strip():
        break
    messages.append({"role": "user", "content": question})
    while True:
        resp = requests.post(
            f"{cfg['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {cfg['api_key']}"},
            json={
                "model": cfg["model_name"],
                "messages": messages,
                "tools": tools,
                "stream": True,
            },
            stream=True,
        )

        reply = ""
        tool_calls = {}
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                delta = json.loads(data)["choices"][0]["delta"]
                if delta.get("content"):
                    for ch in delta["content"]:
                        print(ch, end="", flush=True)
                        time.sleep(0.02)
                    reply += delta["content"]
                for tc in delta.get("tool_calls", []):
                    acc = tool_calls.setdefault(
                        tc["index"],
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    acc["id"] = acc["id"] or tc.get("id")
                    acc["function"]["name"] += tc["function"].get("name") or ""
                    acc["function"]["arguments"] += tc["function"].get("arguments") or ""
        print()

        if not tool_calls:
            messages.append({"role": "assistant", "content": reply})
            break

        calls = list(tool_calls.values())
        messages.append({"role": "assistant", "content": reply or None, "tool_calls": calls})
        for call in calls:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"] or "{}")
            func = TOOL_MAP.get(name)
            if func:
                result = func(args)
            else:
                result = f"未知工具：{name}"
            print(f"[{name}] {result}")
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
