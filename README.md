# LLm · MCP + Agent 综合实验仓库

一套围绕 **MCP（Model Context Protocol）** 搭起来的小型实验工程：一个能真正被 AI 客户端调用的宠物医院 MCP server、
一个把 AnythingLLM 能力暴露为 MCP 工具的 server、一个配套的文档上传网页（密钥放在服务端代理里），
以及一个自己写的命令行 Agent（含 ReAct 主循环、技能渐进加载、上下文压缩归档与会话持久化）。

## 模块地图

| 目录 | 是什么 | 语言 / 运行时 | 一句话入口 |
| --- | --- | --- | --- |
| `pet-hospital-mcp/` | 宠物医院系统：Go REST 服务 + 网页界面 + **MCP server（10 个工具，stdio/HTTP 双传输）** | Go 1.22+ / Python 3.10+ | `python -m mcp_server` |
| `anythingllm-mcp/` | AnythingLLM 的 MCP server：工作区管理、文档上传与向量化、向量检索与问答（8 个工具） | Python 3.10+ | `python server.py` |
| `AnythingLLMserver/` | 文档上传网页 + 本地代理（API Key 只在服务端，前端零密钥） | Python 3.10+ | `python anythingllm-proxy.py` |
| `agent/UnknownApp/Lagent_public/` | 自制命令行 Agent：ReAct 主循环、工具注册、技能渐进加载、会话持久化、上下文压缩归档、TUI | Python 3.10+ | `python main.py` |

> `agent/practice01` ~ `practice03` 是同一课程的**练习题代码**（独立小脚本），不是主链路的一部分，
> 各自带自己的 `config.ini`，运行方式见各目录源码注释。

## 目录结构

```text
LLm/
├── README.md                        ← 你在这里
├── AGENTS.md                        ← 项目级指令约定（Agent 会自动检测并注入）
├── pet-hospital-mcp/                Go REST + 网页 + MCP server
│   ├── mcp_server/                  MCP 服务（Python）
│   └── internal/                    数据模型 / 单文件存储 / REST 路由 / 内嵌网页
├── anythingllm-mcp/                 AnythingLLM MCP server
├── AnythingLLMserver/               上传网页 + 本地代理
└── agent/
    ├── practice01/ practice02/ practice03/   练习题
    └── UnknownApp/
        ├── Lagent_public/           对外形态（无密钥，可公开）
        └── Lagent/                  本地开发副本（含 config.ini，已被 .gitignore 排除）
```

## 环境要求与依赖

| 模块 | 必需依赖 | 安装命令 |
| --- | --- | --- |
| `pet-hospital-mcp` REST | Go 1.22+（仅编译需要，运行用发行包无需 Go） | `make dist` 或 `go build` |
| `pet-hospital-mcp/mcp_server` | `mcp`（官方 SDK v2） | `pip install mcp` |
| `anythingllm-mcp` | `mcp>=2.0`、`httpx2>=0.4` | `pip install -r requirements.txt` |
| `AnythingLLMserver` 代理 | 仅标准库 | 无 |
| `agent/.../Lagent_public` | `textual>=8.0`、`httpx>=0.27`、`trafilatura>=1.9`、`mcp>=1.0` | `pip install -r requirements.txt` |
| 外部服务 | AnythingLLM（默认 `http://localhost:3001`）、可选 Ollama | 各自单独安装 |

Python 实测版本：3.13。

## 分步启动

### 1) 宠物医院：先起 REST，再起 MCP

```bash
cd pet-hospital-mcp
go run .                                   # REST + 网页，默认 http://127.0.0.1:8080
# 另开一个终端：
pip install mcp
python -m mcp_server                       # MCP server，stdio 传输（由 AI 客户端拉起）
```

浏览器打开 <http://127.0.0.1:8080/> 即为网页操作界面；MCP 侧的 10 个工具、错误码与客户端配置见
[pet-hospital-mcp/README.md](pet-hospital-mcp/README.md#作为-mcp-server-接入-ai-客户端)。

### 2) AnythingLLM MCP server

```bash
cd anythingllm-mcp
pip install -r requirements.txt
$env:ANYTHINGLLM_API_KEY="你的开发者 API Key"     # PowerShell；bash 用 export
python server.py                                  # Streamable HTTP: http://127.0.0.1:8766/mcp
```

### 3) 文档上传网页（含向量化）

```bash
cd AnythingLLMserver
$env:ANYTHINGLLM_API_KEY="你的开发者 API Key"
python anythingllm-proxy.py                       # 打开 http://127.0.0.1:8090/
```

页面「上传 → 嵌入」两步走：`POST /api/v1/document/upload` 取回 `location`，
再 `POST /api/v1/workspace/{slug}/update-embeddings` 显式嵌入（本实例该参数不可靠，必须显式调用）。
详见 [AnythingLLMserver/anythingllm-upload.md](AnythingLLMserver/anythingllm-upload.md)。

### 4) 自制 Agent

```bash
cd agent\UnknownApp\Lagent_public
pip install -r requirements.txt
copy config.example.ini config.ini               # 填入模型 base_url / api_key / model
python main.py                                   # 启动 TUI
```

配置项与 `AGENTS.md` 行为见 [agent/README.md](agent/README.md)。

## 验证清单

按「能跑」而不是「看起来写了」判定的自检步骤：

| 检查 | 命令 | 期望 |
| --- | --- | --- |
| 宠物医院 REST 活着 | `curl http://127.0.0.1:8080/health` | `{"code":0,...}` |
| MCP server 工具可枚举 | `python -m mcp_server` + 客户端 `tools/list` | 10 个工具，`inputSchema` 带 enum/minimum |
| 宠物医院 MCP 单测 | `python -m unittest discover -s mcp_server/tests -v` | 11 项 OK（离线，不需要真后端） |
| AnythingLLM MCP 工具 | 起服务后客户端 `tools/list` | 8 个工具 |
| 上传网页无密钥 | 打开 `http://127.0.0.1:8090/`，搜 `API_KEY` | 页面上找不到任何密钥常量 |
| Agent 核心单测 | `python -m unittest discover -s tests -v`（在 `Lagent_public` 下） | 8 项 OK |
| Agent 启动 | `python main.py` | TUI 正常进入，状态栏显示 AGENTS.md 是否注入 |

## 配置与密钥

**所有密钥都从环境变量读取，不写进代码、不写进页面。**

| 变量 | 用途 | 默认 |
| --- | --- | --- |
| `ANYTHINGLLM_API_KEY` | AnythingLLM 开发者 Key（MCP server 与上传代理共用） | 无，缺失即报错退出 |
| `ANYTHINGLLM_BASE_URL` | AnythingLLM 地址 | `http://localhost:3001` |
| `PET_HOSPITAL_BASE_URL` | 宠物医院 REST 地址（MCP 侧） | `http://127.0.0.1:8080` |
| `MCP_HTTP_PORT` | AnythingLLM MCP 监听端口 | `8766` |
| `LAGENT_AGENTS_MD` | 项目级指令文件名 | `AGENTS.md` |
| `LAGENT_AGENTS_MD_MAX_CHARS` | 指令文件注入长度上限 | `4000` |

- `agent/UnknownApp/config.ini` 与 `Lagent/config.ini` 里的模型 Key 属于**本地开发配置**，已在 `.gitignore` 中排除；
  公开分发请使用 `config.example.ini` 模板并改成环境变量注入。
- 历史版本曾把 AnythingLLM Key 明文写在前端页面里，现已改为「代理注入」；**若该 Key 曾外发，请到 AnythingLLM
  设置页吊销并重新生成**。

## 已知限制

- 宠物医院 REST 为**明文 HTTP、无鉴权**，只适合本地/内网演示，不要直接暴露公网。
- `anythingllm-mcp` 的端到端问答依赖本机 AnythingLLM + Ollama，本机未装 Ollama 时只能验证到 `tools/list` 层。
- Agent 的 MCP 客户端目前只实现了 HTTP 传输，stdio 传输尚未实现（`core/mcp.py` 顶部有标注）。
- `agent/practice02` 的 `get_time` 工具调用 `date /t & time /t`，是 Windows 专属实现。

## 许可

课程实验用途，代码可自由参考。
