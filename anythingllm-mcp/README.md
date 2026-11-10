# AnythingLLM MCP Server

一个 **Model Context Protocol (MCP) 服务**，把本机 AnythingLLM 的能力通过 **Streamable HTTP** 暴露给 MCP 客户端（Claude Desktop、Cursor、VS Code、Lagent 等），使 AI Agent 可以直接管理工作区、上传并向量化文档、检索并问答工作区内容。

- 基于官方 **`mcp` SDK v2**（`MCPServer`）
- 遵循 **MCP 2026-07-28 规范**（Streamable HTTP，无状态核心）
- 默认监听 `http://127.0.0.1:8766/mcp`

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `ANYTHINGLLM_API_KEY` | ✅ 是 | — | AnythingLLM 的 API Key（缺失则启动即报错退出） |
| `ANYTHINGLLM_BASE_URL` | 否 | `http://localhost:3001` | AnythingLLM 服务地址 |
| `MCP_HTTP_PORT` | 否 | `8766` | MCP 服务监听端口 |

> API Key 只通过环境变量传入，不写进代码。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动（先确保 AnythingLLM 正在运行，且已配置 API Key）
set ANYTHINGLLM_API_KEY=your-key-here
python server.py
```

启动后服务监听 `http://127.0.0.1:8766/mcp`。

## 提供的工具（8 个，覆盖三类能力）

### 能力一：工作区管理

| Tool | 说明 |
| --- | --- |
| `list_workspaces()` | 列出全部工作区：slug、名称、文档数量 |
| `create_workspace(name)` | 新建工作区，返回生成的 slug |

### 能力二：文档上传与向量化

| Tool | 说明 |
| --- | --- |
| `upload_document(file_path, workspace_slug?, embed=true)` | 上传本机文件到文档库，并默认立即向量化嵌入；单文件上限 20MB，空文件/不存在/超限在本地拦截 |
| `embed_document(location, workspace_slug?, remove=false)` | 对已上传文档显式 `adds` / `deletes`，与 AnythingLLM 的 `update-embeddings` 语义一致 |
| `list_workspace_documents(workspace_slug?)` | 列出工作区已嵌入的文档，用来确认上传是否真的生效 |

### 能力三：检索与问答

| Tool | 说明 |
| --- | --- |
| `vector_search(query, workspace_slug?, top_n=5)` | 只做向量检索，返回命中片段与相似度，不调大模型，便于先看证据 |
| `ask_workspace(question, workspace_slug?)` | 指定工作区问答，`mode=query`，附引用来源标题 |
| `ask_first_workspace(question)` | 兼容早期用法：等价于对第一个工作区 `ask_workspace` |

工作区 slug 为空时统一回落到「列表第 1 个」，且每次调用实时获取、不缓存，避免工作区顺序变化导致失效。

## 客户端配置示例

在 MCP 客户端（如 Claude Desktop）中，以 Streamable HTTP 方式接入：

```json
{
  "mcpServers": {
    "anythingllm": {
      "type": "http",
      "url": "http://127.0.0.1:8766/mcp"
    }
  }
}
```

## 行为说明

- 问答使用 `mode=query`，只基于工作区文档检索作答，不串历史会话
- 推理超时设为 300 秒（本地 Ollama 模型可能较慢），超时返回可读错误提示
- AnythingLLM 未启动 / 连接失败 / 工作区无内容时，均返回可读错误文本，不抛栈
- 端到端验证：MCP 客户端 `initialize` → `tools/list` 可见 `ask_first_workspace` → 调用拿到非空回答

## 许可证

MIT
