# agent/ · 自制 Agent（Lagent）

本目录是一个自己写的命令行 Agent，核心在 `UnknownApp/Lagent_public/`：
不依赖 LangChain 之类框架，自己实现 ReAct 主循环、工具注册与调用、技能渐进加载、
上下文压缩归档、会话持久化，并配一个 Textual TUI。

## 目录地图

| 路径 | 内容 |
| --- | --- |
| `UnknownApp/Lagent_public/main.py` | 启动入口：读配置、装配工具、检测 AGENTS.md、进 TUI |
| `UnknownApp/Lagent_public/core/agent.py` | ReAct 主循环：`max_rounds` 轮次上限、工具结果回填、错误回填 |
| `UnknownApp/Lagent_public/core/llm/client.py` | 模型客户端（OpenAI 兼容协议，`httpx`） |
| `UnknownApp/Lagent_public/core/context.py` | 上下文压缩与归档（超限时压缩，归档可检索） |
| `UnknownApp/Lagent_public/core/session.py` | 会话持久化 + 项目级指令文件（AGENTS.md）加载 |
| `UnknownApp/Lagent_public/core/mcp.py` | MCP 客户端（当前只有 HTTP 传输） |
| `UnknownApp/Lagent_public/core/tools/` | 内置工具：文件系统、网页抓取、搜索、技能、命令行 |
| `UnknownApp/Lagent_public/tui/app.py` | Textual 界面：对话流、状态栏、命令面板 |
| `UnknownApp/Lagent_public/tests/` | 核心单测（会话、AGENTS.md） |
| `practice01` ~ `practice03` | 同一课程的练习题脚本，彼此独立，不属于主链路 |

`UnknownApp/Lagent/` 是本地开发副本（含真实 `config.ini` 与 `.mcp.json`，均被 `.gitignore` 排除），
对外形态以 `Lagent_public/` 为准。

## 启动步骤

```powershell
cd agent\UnknownApp\Lagent_public
pip install -r requirements.txt

# 1) 生成自己的配置（不要提交真实 Key）
copy config.example.ini config.ini

# 2) 按需配置 MCP 服务（可选）
copy .mcp.example.json .mcp.json

# 3) 启动
python main.py
```

## 配置矩阵

### `config.ini`（`[llm]` 段）

| 键 | 必填 | 默认 | 说明 | 环境变量覆盖 |
| --- | --- | --- | --- | --- |
| `api_key` | 是 | — | 模型 API Key | `LAGENT_API_KEY`（优先） |
| `base_url` | 否 | — | OpenAI 兼容地址，如 `https://api.deepseek.com/v1` | `LAGENT_BASE_URL` |
| `model_name` | 否 | — | 模型名，如 `deepseek-chat` | `LAGENT_MODEL` |
| `timeout` | 否 | `120` | 单次请求超时（秒） | — |
| `temperature` | 否 | 模型默认 | 0~2 | — |
| `context_window` | 否 | 模型默认 | 上下文窗口（tokens），决定压缩触发点 | — |
| `max_rounds` | 否 | `12` | 单次提问最多推理轮次，超限即停并提示 | — |
| `baidu_qianfan_apikey` | 否 | — | 千帆搜索工具的 Key | `BAIDU_QIANFAN_APIKEY` |

### `.mcp.json`（MCP 服务清单）

```json
{
  "mcpServers": {
    "pet-hospital": {
      "type": "streamable_http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `type` | 是 | 目前支持 `streamable_http`（stdio 传输尚未实现） |
| `url` | 是 | MCP 端点地址；若地址里带令牌，务必只写进 `.mcp.json` |
| 其他键 | — | 透传给客户端，不参与解析 |

### 项目级指令文件（AGENTS.md）

| 行为 | 说明 |
| --- | --- |
| 搜索范围 | 当前工作目录 → 向上最多 5 层，加上传入的 root |
| 默认文件名 | `AGENTS.md`，用 `LAGENT_AGENTS_MD` 可改成 `AGENT.md` 等 |
| 注入长度 | 默认 4000 字符，超出部分截断并附一行说明；用 `LAGENT_AGENTS_MD_MAX_CHARS` 调整 |
| 注入位置 | 作为一条独立 system 消息，位于对话历史最前，不参与压缩丢弃 |
| 状态可见 | TUI 状态栏与 `/status` 显示「AGENTS.md: ✅ 已注入 / （未使用）」 |

仓库根目录已提供一份真实的 `AGENTS.md`，从 `Lagent_public` 启动即可被检测到。

## 会话与归档

```text
<root>/.agents/
└── sessions/
    └── <session_id>/
        ├── session.json     # 元数据：标题、创建时间、last_used、消息数
        └── messages.jsonl   # 每行一条消息 JSON
```

- 会话由 `SessionStore` 管理：`create / save / load / list / delete`
- 上下文超限时触发压缩，压缩前的原文进归档，可在后续轮次里检索回来

## 自测

```powershell
cd agent\UnknownApp\Lagent_public
python -m unittest discover -s tests -v      # 8 项：会话往返、AGENTS.md 文件名/截断/缺失
```

## 已知限制

- MCP 客户端只实现了 HTTP 传输，stdio 未实现（`core/mcp.py` 顶部有标注）。
- 文件系统工具的写入与删除没有目录白名单，只在本地单人使用场景下安全。
- `practice02` 的时间工具调用 `date /t & time /t`，Windows 专属。
- 没有端到端的 Agent 集成测试（需要真实模型 Key），只有核心模块单测。
