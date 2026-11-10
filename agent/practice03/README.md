# practice03 — 带 Function Calling 的文件系统智能体

基于 `requests` 流式调用 OpenAI 兼容的 `chat/completions` 接口，内置 **10 个本地文件系统工具**（目录/文件的新增、读取、删除、重命名等），由大模型自动决定调用哪个工具，支持多轮对话。

## 目录结构

```
practice03/
├── main.py             # 主程序
├── main.mmd            # Mermaid 架构图
├── README.md           # 本文件
├── config.ini          # 模型配置（需自备）
└── daimajiagoutu.png   # 架构图导出图片
```

## 运行

```bash
pip install requests
py main.py
```

交互：直接输入问题；**空行退出**。

## 配置

`config.ini` 需要一个 `[llm]` 节：

```ini
[llm]
base_url = https://your-endpoint/v1
api_key  = sk-xxx
model_name = your-model
```

## 内置工具

| 工具 | 参数 | 实现方式 | 说明 |
|---|---|---|---|
| `getCwd` | 无 | `os.getcwd()` | 获取当前工作目录 |
| `listDir` | `dir` (可选) | `pathlib.Path.iterdir` 排序 | 列出目录下文件与子目录，缺省为当前目录 |
| `getFileType` | `path` | 后缀白名单 + `stat().st_size` | 返回扩展名、纯文本/二进制分类、大小 |
| `readFile` | `path` | `read_text` UTF-8→GBK 兜底 | 读取纯文本；超过 5 万字符自动截断；拒绝二进制扩展名 |
| `createFile` | `dir`, `filename`, `content`(可选) | `mkdir(parents=True)` + `touch`/`write_text` | 创建文件，已存在则拒绝 |
| `writeFile` | `path`, `content` | 父目录 `mkdir` + `write_text` | 覆盖写入文本 |
| `createDir` | `path` | `mkdir(parents=True)` | 递归创建目录 |
| `removeDir` | `path` | `shutil.rmtree` | 删除目录（含非空） |
| `removeFile` | `path` | `Path.unlink` | 删除单个文件 |
| `renamePath` | `old`, `new` | `Path.rename` | 重命名 / 同盘移动 |

> 所有工具均做了路径存在性、目录/文件类型、编码等安全校验，出错时以中文提示字符串返回给模型，不会抛异常中断对话。

## 代码架构

核心分为五层（详见 [main.mmd](./main.mmd)）：

1. **入口与配置**：`configparser` 读取 `config.ini` 的 `[llm]` 段。
2. **工具声明层**：`tools` 列表，以 OpenAI tools schema 描述 10 个工具的参数。
3. **工具实现层**：每个工具对应的 Python 函数（`pathlib` / `os` / `shutil`）。
4. **分发层**：`TOOL_MAP` 将「工具名」映射到「lambda 参数适配函数」。
5. **运行时循环**：交互式 Agent 主循环（见下）。

```
flowchart 概览：
  config.ini → cfg ─┐
  tools ────────────┼─→ requests.post(/chat/completions, stream=True)
  messages ─────────┘        │
                             ▼
                  解析 SSE(data:) → 累积 content / tool_calls
                             │
                    ┌────────┴────────┐
                有 tool_calls?        无
                    │                 │
                    ▼                 ▼
          TOOL_MAP 分发执行      append assistant
               │                  → 回到外层
               ▼
          append role=tool
          → 回到内层循环继续请求
```

## 交互流程

1. 用户输入 → 写入 `messages`。
2. 内层循环请求 `chat/completions`（带 `tools` + `stream=true`），边收边逐字打印；同时把流式 `tool_calls` 分片累积成完整调用。
3. **无工具调用**：写入 `assistant` 消息，返回外层等待下一问。
4. **有工具调用**：通过 `TOOL_MAP` 分发执行，把 `role=tool` 结果追加到 `messages`，回到内层继续请求模型（直到模型不再请求工具）。

## 架构图

见 [main.mmd](./main.mmd)，可粘贴到 [mermaid.live](https://mermaid.live) 或支持 Mermaid 的 Markdown 预览器渲染。

## 示例

```
请输入问题（直接回车退出）：当前在哪个目录？
[getCwd] D:\LLm\agent\practice03
你当前所在的工作目录是 D:\LLm\agent\practice03。

请输入问题（直接回车退出）：列出当前目录内容
[listDir] <DIR>  .git
<FILE .py>  main.py
...
当前目录下有 main.py、README.md 等文件。

请输入问题（直接回车退出）：
EXIT_CODE=0
```
