# Agent Orchestrator

## 目的

本模块解决第二个框架缺口：前端不再自己拼接“规划、确认、生成工具计划、确认工具计划、执行、刷新证据”的流程，而是把用户意图交给后端统一编排。

借鉴 Codex 的机制：

- runtime-owned loop：前端只提交动作，后端负责推进状态。
- event stream：每个动作都有 `orchestrator.action.begin/end/failed`。
- conversation bundle：每次动作结束都返回同一份状态包，包含会话、工具计划、事件、checkpoint、进程和沙盒文件树。
- approval gate：确认方案和确认工具计划仍然是明确的用户授权点。
- sandbox-first execution：编排器只在当前 conversation sandbox 中组织代码工具和命令工具。

## 落地文件

```text
server_py/agent/orchestrator.py
server_py/services.py
server_py/app.py
shared/src/index.ts
client/src/shared/api.ts
client/src/features/workbench/useWorkbench.ts
```

## API

```text
POST /api/agent/orchestrator
```

请求：

```json
{
  "conversationId": "conv_xxx",
  "action": "submit_requirement | approve_plan | approve_tool_plan | execute_tool_plan | repair_failed_plan | refresh",
  "requirement": "optional",
  "planId": "optional"
}
```

返回：

```text
conversation
turn
toolPlan
executedToolPlan
repairPlan
repairLoop
checkpoints
events
processes
files
runtimeSnapshot
sandboxRuntime
nextActions
```

## 当前能力

- `submit_requirement`：调用 `AgentWorkflow.plan`，把模型真实输出写入会话。
- `approve_plan`：确认模型方案，随后由后端生成可审查工具调用计划。
- `approve_tool_plan`：确认工具计划，状态进入 `tool_plan_approved`。
- `execute_tool_plan`：按计划执行受控工具，执行后调用 Verifier 审查证据；失败时自动生成下一轮等待确认的修复计划。
- `repair_failed_plan`：用户手动要求基于当前失败计划生成修复计划。
- `refresh`：返回当前会话完整状态包，不触发写入动作。
- 旧接口 `POST /api/agent/tool-plan/execute` 已收口到 Orchestrator，不再绕过 Verifier、repair loop、runtime snapshot 和事件流。
- `execute_tool_plan` 返回 `executedToolPlan` 表示刚刚执行的计划；如果产生修复计划，`toolPlan` 和 `repairPlan` 都会指向新的等待确认计划。
- `repairLoop.created = true` 表示后端已创建修复计划；`repairLoop.reason` 说明自动生成或停止原因。

## 已验证

Smoke 流程：

```text
临时 git 仓库
-> 本地沙盒接入
-> 创建工具计划
-> Orchestrator 确认工具计划
-> Orchestrator 执行工具计划
```

验证结果：

```text
createdStatus = waiting_confirmation
approvedStatus = approved
executedStatus = completed
phase = tool_plan_completed
stateWarnings = 0
```

失败修复闭环 smoke：

```text
临时本地仓库
-> 构造 npm test 失败
-> Orchestrator 执行工具计划
-> Verifier 记录失败审查
-> 自动生成 repair plan，状态为 waiting_confirmation
-> 用户确认 repair plan
-> 执行 repair plan 后自动复验
-> 仍失败时生成第二轮 waiting_confirmation repair plan
```

关键结果：

```text
firstExecutedStatus = failed
firstRepairStatus = waiting_confirmation
firstRepairGenerationSource = repair-loop
firstRepairFallbackReason = null
secondRepairStatus = waiting_confirmation
secondRepairSequence = 2
```

## 当前不足

- Clarifier / Reviewer / Verifier 已接入模型优先、规则兜底，但 prompt 质量仍需要通过真实 Conduit 任务继续调优。
- repair loop 已经可以连续生成下一轮待确认计划，但还缺更强的失败聚类和修复策略沉淀。
- 当前 Verifier verdict 仍使用 `pass / warning / blocked`，前端需要把执行失败场景的 `blocked` 更清晰地展示为“未通过/需修复”。
- 外部 MCP 已能进入工具计划，但长连接、OAuth、连接池和 session recovery 仍未完成。
