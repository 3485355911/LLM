# AGENTS.md · 本仓库的项目级约定

这个文件会被 `agent/UnknownApp/Lagent_public` 的 Agent 自动检测并注入会话（默认文件名 `AGENTS.md`，
可用环境变量 `LAGENT_AGENTS_MD` 换成别的名字；超长时按 `LAGENT_AGENTS_MD_MAX_CHARS` 截断）。
Claude Code、Cursor 等工具也读这个约定文件，所以这里只写**事实性约定**。

## 语言与风格

- 代码注释、文档、提交说明统一用简体中文；变量名与接口字段用英文。
- Python 用 3.10+ 语法，公共函数写类型标注；Go 用标准库，不引入第三方依赖。
- 报错信息面向使用者，写清「发生了什么 + 怎么办」，不要只贴异常类型。

## 目录职责

| 路径 | 职责 | 不要做的事 |
| --- | --- | --- |
| `pet-hospital-mcp/internal/` | 数据模型、单文件存储、REST 路由 | 不要在这里写 MCP 相关代码 |
| `pet-hospital-mcp/mcp_server/` | MCP 工具定义与 REST 客户端 | 不要直连数据库，只走 REST |
| `anythingllm-mcp/server.py` | AnythingLLM 的 MCP 工具 | 不要把 API Key 写进代码 |
| `AnythingLLMserver/anythingllm-proxy.py` | 本地代理，唯一持有 Key 的地方 | 不要把 Key 传回前端 |
| `agent/UnknownApp/Lagent_public/core/` | Agent 主循环、工具、会话、上下文 | 不要在这里写死模型 Key |

## 密钥与配置

- 一切密钥走环境变量或 `config.ini` / `.mcp.json`（两者均已 `.gitignore` 排除）。
- 提交前扫一遍：`rg -n "sk-|Bearer [A-Za-z0-9]"`，命中就要处理。
- 示例配置只放 `config.example.ini`、`.mcp.example.json`，值是占位符。

## 改代码前后

- 改完跑对应单测：`pet-hospital-mcp/mcp_server/tests`（11 项）、`Lagent_public/tests`（8 项）。
- 新增 MCP 工具必须同时给：`description`（什么时候用）、参数约束（必填/枚举/范围）、失败时的可读提示。
- 新增文件请放在它所属模块的目录里，不要堆在仓库根目录；临时脚本用完即删。
