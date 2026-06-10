# Codex 源码借鉴地图

审计对象：

```text
workspace/upstream/openai-codex
```

这个目录只用于研究机制，不作为当前平台的运行时依赖。

## 借鉴映射

| Codex 来源 | 机制 | 当前项目位置 | 当前方式 |
| --- | --- | --- | --- |
| `codex-rs/core/src/exec_policy.rs` | `allow / prompt / forbid` 执行决策、可信前缀、危险命令启发式 | `server_py/runtime/permissions.py` | Python 改写 |
| `codex-rs/core/src/tools/handlers/shell.rs` | 命令执行前先做权限决策、事件 begin/end、审批请求 | `server_py/tools/registry.py`、`server_py/tools/command_tools.py` | Python 改写 |
| `codex-rs/core/src/tools/handlers/apply_patch.rs` | patch 前解析涉及文件、检查路径和写入权限、输出 patch 事件 | `server_py/tools/code_tools.py`、`server_py/sandbox/checkpoint_manager.py` | 机制改写为结构化 patch |
| `codex-rs/utils/cli/src/approval_mode_cli_arg.rs` | approval mode | `server_py/runtime/permissions.py` | 改写 |
| `codex-rs/utils/cli/src/sandbox_mode_cli_arg.rs` | sandbox mode | `server_py/runtime/permissions.py` | 改写 |
| `codex-rs/app-server-protocol/src/protocol/v2/permissions.rs` | 文件、网络、沙盒权限模型 | `server_py/runtime/permissions.py` | 简化改写 |
| Codex approval request / resolve event pattern | 会话级授权和消费事件 | `server_py/runtime/approval_store.py`、`server_py/tools/registry.py` | 改写 |
| `codex-rs/app-server-protocol/src/protocol/v2/command_exec.rs` | 命令执行结构 | `server_py/tools/command_tools.py` | 简化改写 |
| Codex verification-loop skill / command evidence pattern | 验证命令证据 | `server_py/verification/runner.py`、`server_py/tools/verification_tools.py` | 改写 |
| `codex-rs/tools/src/tool_definition.rs` | 工具元数据 | `server_py/tools/types.py` | 改写 |
| `codex-rs/tools/src/mcp_tool.rs` | MCP tool 转内部 tool | `server_py/tools/registry.py`、`server_py/mcp/adapter.py` | 改写中 |
| MCP server config / diagnostics pattern | 外部 server 配置诊断、stdio tools/list、HTTP tools/list | `server_py/mcp/adapter.py`、`server_py/mcp/stdio_client.py`、`server_py/mcp/http_client.py` | 改写 |
| `codex-rs/rmcp-client/src/http_client_adapter.rs` | Streamable HTTP MCP：JSON-RPC、JSON/SSE 响应、Mcp-Session-Id | `server_py/mcp/http_client.py` | Python 简化改写 |
| Codex tool call result item / approval evidence pattern | 工具调用输入、输出、schema、审批和重放证据分层 | `server_py/mcp/adapter.py`、`client/src/features/inspector/MCPPanel.tsx` | Python/React 改写 |
| `codex-rs/app-server-protocol/src/protocol/thread_history.rs` | thread event reducer | `server_py/runtime/events.py` | 改写为 JSONL 事件流 |
| `codex-rs/app-server-protocol/src/protocol/item_builders.rs` | command/file change item | `server_py/agent/tool_call_plan.py` | 改写为工具计划步骤和证据 |
| `codex-rs/app-server-protocol/src/protocol/event_mapping.rs` | Exec / Patch / MCP 事件映射 | `server_py/runtime/events.py` | 改写 |
| `codex-rs/core/src/mcp_tool_call.rs` | MCP tool call 生命周期、approval、结果事件 | `server_py/mcp/adapter.py`、`server_py/tools/registry.py` | Python 改写 |
| Codex execute -> verify -> repair mental model | 执行失败后基于证据进入下一轮计划，而不是把错误直接抛给用户 | `server_py/agent/orchestrator.py`、`server_py/agent/tool_plan_drafter.py`、`server_py/agent/tool_call_plan.py` | Python 改写 |
| `codex-rs/apply-patch` | patch 语法和补丁应用 | 暂不接入运行时 | 只审计，不依赖 |

## 已验证行为

- `/api/mcp/discover` 可对 stdio MCP server 执行 `initialize` 和 `tools/list`。
- `/api/mcp/discover` 可对 HTTP MCP server 执行 `initialize`、`notifications/initialized` 和 `tools/list`。
- `/api/mcp/run` 可执行内部工具、外部 stdio MCP 和外部 HTTP MCP `tools/call`。
- 工具调用事件携带 `planId` 和 `stepId`，MCP 历史可以定位到具体工具计划步骤。
- `/api/mcp/replay` 可从已保存 input 的历史 entry 重放单条工具调用。
- 外部 MCP 工具调用会进入审批、事件流和 metrics。
- `PermissionPolicy` 已按 Codex `ExecPolicyManager` 思路重写为显式执行决策。
- `command.run` 会返回 stdout/stderr tail，供 Verifier 和修复循环使用。
- `code.apply_patch` 是平台自有结构化写入工具，会创建 checkpoint 并返回 diff。
- 修复循环已从固定轮次改为 Verifier repairPolicy：总修复链路上限 + 代码修复次数上限 + 失败类型分流。
- 旧工具计划执行接口已收口到 Orchestrator，任何执行都会经过 Verifier、repair loop 和 runtime bundle。
- `ToolPlanDrafter.draft_repair` 已真实调用模型消息；修复计划不再因为缺少 `messages` 回退。
- 失败日志中的绝对路径会规范化为沙盒相对路径，并且只把真实存在的文件加入 `code.read_file`。
- 修复计划确认执行后会复跑验证；失败时继续生成下一轮 waiting confirmation repair plan。
- `/api/preview/smoke-test` 可以保存 HTML、截图和 smoke-report。

## 下一批值得借鉴的机制

- 命令 stdout/stderr 的增量事件流。
- Browser / in-app browser 作为正式 Agent 工具。
- GitHub 插件作为正式 Agent 工具。
- Codex task progress/todo 的真实事件结构。
- 多 Agent thread/fork/handoff 协议。
- SSE/WS MCP 长连接生命周期。
- stdio/HTTP MCP 连接池、OAuth 登录和 session recovery。
