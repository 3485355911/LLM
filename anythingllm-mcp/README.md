# AnythingLLM MCP Server（MVP）

一个 **Model Context Protocol (MCP) 服务**，把本机 AnythingLLM「第一个工作区」的文档问答能力，通过 **Streamable HTTP** 暴露给 MCP 客户端（Claude Desktop、Cursor、VS Code 等），使 AI Agent 可以直接查询 AnythingLLM 工作区中已上传文档的内容。

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

## 提供的工具

| Tool | 说明 |
| --- | --- |
| `ask_first_workspace(question)` | 向 AnythingLLM 的第一个工作区提问，基于其中已上传的文档检索后由 AI 回答，并附带引用来源标题列表 |

工作区 slug 每次调用实时获取（取列表第 1 个），不缓存，避免工作区顺序变化导致失效。

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
