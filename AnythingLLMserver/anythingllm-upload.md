# AnythingLLM 文档上传网页

## 文件位置

```
D:\LLm\AnythingLLMserver\anythingllm-upload.html
D:\LLm\AnythingLLMserver\anythingllm-proxy.py     ← 本地代理（密钥只在服务端）
```

## 启动方式

**不要**再用 `python -m http.server` 直接开页面——那样页面必须自带密钥。现在走本地代理：

```powershell
cd D:\LLm\AnythingLLMserver
$env:ANYTHINGLLM_API_KEY="你的开发者 API Key"
python anythingllm-proxy.py
```

浏览器访问：**http://127.0.0.1:8090/**

> 代理同时做了两件事：`GET /` 返回页面；`/api/**` 转发到 AnythingLLM 并补上 `Authorization` 头。
> 因此页面是同源的，也没有 CORS 问题。

可选环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ANYTHINGLLM_BASE_URL` | `http://127.0.0.1:3001` | 上游地址 |
| `PROXY_PORT` / `PROXY_HOST` | `8090` / `127.0.0.1` | 监听端口与地址 |

## 功能

调用 AnythingLLM 两个接口完成「上传 → 向量化嵌入」：

| 步骤 | 接口 | 说明 |
|------|------|------|
| 1 | `POST /api/v1/document/upload` | 上传文件，返回 `documents[0].location`（如 `custom-documents/姓名.txt-uuid.json`） |
| 2 | `POST /api/v1/workspace/{slug}/update-embeddings` | 显式嵌入，body `{"adds":[location],"deletes":[]}` |

> **重要**：`upload` 接口的 `addToWorkspaces` 参数在本实例不可靠，必须显式调用 `update-embeddings`。

## 页面交互

1. 页面加载时自动拉取 AnythingLLM 工作区列表，填入下拉选择框
2. 选文件 → 点「上传并嵌入」→ 两步串行执行
3. 成功后显示：工作区名称 / 文档标题 / 字数 / Token 估算 / location
4. 失败显示可读错误（HTTP 状态码 / AnythingLLM 返回的 error 字段）

## 依赖

- AnythingLLM 必须在线：`http://localhost:3001`
- API Key **不再出现在前端**：只通过环境变量 `ANYTHINGLLM_API_KEY` 注入代理进程，页面 `<script>` 里没有任何密钥
- 无需开启 AnythingLLM CORS：页面与接口同源（都由代理提供）

## 接口详情（来自 AnythingLLM Swagger）

Swagger UI：**http://localhost:3001/api/docs/**

### POST /api/v1/document/upload

- **Content-Type**：`multipart/form-data`（不要手动设，浏览器自动处理）
- **鉴权**：`Authorization: Bearer <API_KEY>`
- **FormData 字段**：
  - `file`（必填）：要上传的文件
  - `addToWorkspaces`（可选）：逗号分隔的工作区 slug —— 本实例不可靠，建议不用
  - `metadata`（可选）：`{"title":"...","docAuthor":"...","description":"...","docSource":"..."}`
- **成功响应**：
  ```json
  {
    "success": true,
    "documents": [{
      "location": "custom-documents/姓名.txt-uuid.json",
      "title": "姓名.txt",
      "wordCount": 1,
      "token_count_estimate": 6,
      ...
    }]
  }
  ```

### POST /api/v1/workspace/{slug}/update-embeddings

- **Content-Type**：`application/json`
- **鉴权**：`Authorization: Bearer <API_KEY>`
- **请求体**：
  ```json
  {
    "adds": ["custom-documents/姓名.txt-uuid.json"],
    "deletes": []
  }
  ```
- **成功响应**：
  ```json
  { "workspace": { "...": "..." }, "message": null }
  ```
- **注意**：`adds` / `deletes` 数组不能为空，必须传真实文档路径

## 验证嵌入是否成功

嵌入成功后，向量检索能召回：

```powershell
# 先在当前会话设置一次密钥（脚本从环境变量读，不写进任何文件）
$env:ANYTHINGLLM_API_KEY="你的开发者 API Key"

curl.exe -s -X POST "http://localhost:3001/api/v1/workspace/{slug}/vector-search" `
  -H "Authorization: Bearer $env:ANYTHINGLLM_API_KEY" `
  -H "Content-Type: application/json" `
  -d "{\"query\":\"测试关键词\",\"topN\":10,\"scoreThreshold\":0}"
```

返回的 `results[]` 中应包含新上传文档的 chunk，`score` 越高越相关。

## 清理文档（从工作区移除）

```powershell
curl.exe -s -X POST "http://localhost:3001/api/v1/workspace/{slug}/update-embeddings" `
  -H "Authorization: Bearer $env:ANYTHINGLLM_API_KEY" `
  -H "Content-Type: application/json" `
  -d "{\"adds\":[],\"deletes\":[\"custom-documents/姓名.txt-uuid.json\"]}"
```

## 已知限制

- 向量化嵌入是异步的，`update-embeddings` 返回 200 后可能需要等几秒才能在 UI 看到状态更新
- Ollama 嵌入模型在 CPU 上较慢，大文件嵌入可能耗时较长
- 页面只支持单文件上传，多文件需逐个操作
