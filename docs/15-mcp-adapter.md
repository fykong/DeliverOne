# MCP Adapter

## 目标

MCP Adapter 是 Agent Runtime 的统一工具协议层。Agent 和前端不直接依赖某个 Python 工具类，而是通过 MCP 风格的 manifest、tool id、审批和事件流来调用能力。

这一层借鉴 Codex 的核心机制：

- 工具统一暴露为 manifest，方便 Agent、UI 和审计读取。
- 工具调用必须进入审批、沙盒上下文和事件流。
- 内置工具和外部 MCP 工具使用同一个 `/api/mcp/run` 入口。
- 外部能力默认按高风险处理，不能静默执行。

## 落地文件

```text
config/mcp-servers.json
server_py/mcp/adapter.py
server_py/mcp/stdio_client.py
server_py/mcp/http_client.py
server_py/app.py
server_py/services.py
shared/src/index.ts
client/src/shared/api.ts
```

## API

```text
GET  /api/mcp/manifest
GET  /api/mcp/tools
GET  /api/mcp/servers
POST /api/mcp/discover
POST /api/mcp/run
POST /api/mcp/replay
```

## 当前能力

### 1. 内置工具 MCP 化

当前内置工具会以 `internal.<toolId>` 的形式出现在 MCP manifest 中：

```text
internal.code.search_files
internal.code.read_file
internal.code.git_diff
internal.code.write_file
internal.code.apply_patch
internal.command.run
internal.verification.run
```

调用路径：

```text
POST /api/mcp/run
-> MCPAdapter.run_tool
-> internal tool dispatch
-> ToolRegistry 权限判断
-> EventStore + Metrics
```

### 2. 外部 MCP server 配置诊断

`GET /api/mcp/servers` 会读取 `config/mcp-servers.json`，并返回：

- `configured`
- `disabled`
- `misconfigured`

诊断内容包括：

- `transport` 是否为 `stdio/http/sse/ws`
- stdio `command` 是否存在
- `args` 是否是数组
- HTTP/SSE/WS `url` 是否合法
- `env` 是否是对象

### 3. stdio tools/list 发现

`POST /api/mcp/discover` 支持第一版 stdio MCP 工具发现：

```text
启动 stdio server
-> initialize
-> notifications/initialized
-> tools/list
-> 转成 external.<serverId>.<toolName>
-> 并入 /api/mcp/tools
```

外部工具 manifest 会包含：

- `id`
- `mcpName`
- `serverId`
- `inputSchema`
- `riskLevel = external`
- `approvalAware = true`
- `sandboxScoped = false`

### 4. stdio tools/call 调用

`POST /api/mcp/run` 现在可以调用外部 MCP 工具：

```text
POST /api/mcp/run
-> MCPAdapter.run_tool
-> external tool index lookup
-> approval gate
-> MCPStdioClient.call_tool
-> initialize
-> notifications/initialized
-> tools/call
-> EventStore + Metrics
```

调用输入格式：

```json
{
  "conversationId": "xxx",
  "toolId": "external.mock-stdio.demo.echo",
  "input": {
    "arguments": {
      "text": "hello"
    },
    "timeoutSeconds": 15
  }
}
```

如果 `input.arguments` 不存在，后端会把 `input` 中除了 `approved` 和 `timeoutSeconds` 之外的字段作为 MCP arguments。

### 5. 审批规则

外部 MCP 工具默认按 `external` 风险处理。

允许执行的情况：

- 用户直接触发：`userInitiated = true`
- 调用显式带 `approved = true`
- 当前 conversation 已有匹配的 approval grant

否则返回：

```json
{
  "ok": false,
  "needsApproval": true,
  "riskLevel": "external"
}
```

一次性授权会在成功匹配后自动失效。

### 6. HTTP tools/list 和 tools/call

`POST /api/mcp/discover` 现在也支持 `transport = "http"` 的 MCP server：

```text
HTTP POST initialize
-> 保存 Mcp-Session-Id
-> HTTP POST notifications/initialized
-> HTTP POST tools/list
-> 转成 external.<serverId>.<toolName>
```

`POST /api/mcp/run` 调用 HTTP MCP 工具时仍沿用同一条审批链路：

```text
POST /api/mcp/run
-> MCPAdapter.run_tool
-> external tool index lookup
-> approval gate
-> MCPHttpClient.call_tool
-> HTTP initialize / initialized / tools/call
-> EventStore + Metrics
```

HTTP client 借鉴 Codex Streamable HTTP MCP 设计：

- 请求使用 JSON-RPC。
- `Accept` 同时声明 `application/json, text/event-stream`。
- 响应可以是 JSON，也可以是 SSE `data:` 中的 JSON-RPC 消息。
- 初始化响应里的 `Mcp-Session-Id` 会在本次短会话后续请求中透传。
- 支持 `headers`、`http_headers`、`env_http_headers`、`bearer_token_env_var`、`bearerTokenEnv`、`authEnv`。

当前 HTTP 仍是短会话 stateless 模式，还没有连接池、OAuth 自动登录、session recovery。

### 7. SSE / WS 配置诊断

`transport = "sse"` 和 `transport = "ws"` 已进入配置校验和 server 状态展示：

- SSE URL 必须是 `http://` 或 `https://`。
- WS URL 必须是 `ws://` 或 `wss://`。
- headers / env headers / timeout 会被校验。

当前不会真正建立 SSE/WS 长连接执行工具。发现时会返回明确失败原因，提示先使用 stdio 或 HTTP。

### 8. 事件和指标

外部 MCP 调用会写入：

```text
mcp.tool.dispatch
tool.call.begin
approval.requested
approval.consumed
mcp.external.call.begin
mcp.external.call.end
tool.call.end
```

同时写入 `metrics.jsonl`：

```text
kind = tool
toolId = external.<serverId>.<toolName>
riskLevel = external
durationMs
ok
```

### 9. 工具计划归因和历史重放

工具计划执行每个 step 时，会把 `planId` 和 `stepId` 放进 `ToolContext`，再由内置工具和外部 MCP 调用事件写入 payload：

```text
tool_plan.step.begin
-> tool.call.begin(planId, stepId)
-> mcp.tool.dispatch(planId, stepId, input)
-> mcp.external.call.begin(planId, stepId)
-> mcp.external.call.end(planId, stepId)
-> tool.call.end(planId, stepId)
-> tool_plan.step.end
```

这里没有把 `planId` / `stepId` 塞进 MCP tool arguments，避免把平台内部元数据发给外部 server。

`GET /api/mcp/history/{conversationId}` 返回的历史项现在包含：

- `planId`
- `stepId`
- `transport`
- `payload.input`

如果历史项带 `payload.input`，可以调用：

```text
POST /api/mcp/replay
```

后端会根据历史 entry 找回 `toolId` 和输入，用用户主动触发的方式重新执行一次，并写入：

```text
mcp.tool.replay.requested
mcp.tool.replay.completed
```

第一版重放是单条调用重放，不会自动重放整条工具计划。

## 已验证

mock stdio MCP server 测试通过：

```text
discover ok = true
toolId = external.mock-stdio.demo.echo
未授权调用 = needsApproval true
once grant 后调用 = echo:hello
grantActiveAfterUse = false
```

mock HTTP MCP server 测试通过：

```text
discover ok = true
toolId = external.fake-http.echo
transport = http
tools/call = echo:hello
```

mock HTTP MCP 历史重放测试通过：

```text
planId = plan_demo
stepId = step_01
historyEntry = hist_evt_0
replayOk = true
```

基础检查通过：

```text
python -m compileall server_py
npm run typecheck
```

前端基础面板已接入：

```text
client/src/features/inspector/MCPPanel.tsx
```

当前支持：

- 查看 MCP server、外部工具、有效授权数量。
- 手动触发 `POST /api/mcp/discover`。
- 查看 server transport、endpoint、发现错误和工具 transport。
- 查看调用所属 `planId / stepId`。
- 工具 manifest 返回 `schemaSummary`，前端可以直接展示字段名、类型、必填项和字段说明。
- `GET /api/mcp/history/{conversationId}` 返回的历史项会标准化 `schemaSummary`、`inputPreview`、`resultPreview` 和 `approval`，用于审查本次工具调用的输入、输出和授权状态。
- 调用结果抽屉已按“元信息 -> 审批 -> 输入 schema -> 本次输入 -> 本次输出 -> 完整 JSON”分层展示，不再只展示原始事件 JSON。
- 在调用结果抽屉里重放已保存输入的单条调用。
- 对外部工具授予一次授权或会话授权。
- 撤销当前 conversation 的有效授权。

## 当前缺口

- SSE/WS MCP transport 还没有真实长连接。
- stdio 和 HTTP server 目前是 stateless per call；还没有长连接生命周期、连接池和 session recovery。
- 前端 MCP 配置仍是 JSON 编辑器，后续需要表单化配置、字段级提示和失败重放策略。
- MCP 工具调用结果已经有详情抽屉，但还缺按失败类型筛选、按计划聚合、跨轮 repair 关联和历史搜索。
- OAuth/token 型 MCP server 还没有配置向导和密钥管理。
