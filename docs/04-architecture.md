# 架构说明

## 产品目标

用户输入真实需求，系统在当前对话沙盒中完成：

```text
需求理解 -> 计划确认 -> 工具计划确认 -> 代码定位 -> 安全修改 -> 验证 -> 预览 -> 交付 -> 可回退
```

所有代码修改默认只发生在对话沙盒内，不直接污染原始仓库。

## 分层

```text
Frontend
  左侧历史对话
  中间 Agent 对话
  右侧交付证据、checkpoint、diff、验证、预览、回退

FastAPI API
  模型、仓库、Agent、工具、事件、checkpoint、回退、预览接口

Agent Layer
  PlanningAgent：生成需求确认和执行计划
  ExecutorAgent：生成执行边界和工具调用建议
  ToolCallPlanService：生成、确认、执行可审查工具调用计划
  AgentWorkflow：编排计划确认后的代码定位
  PlanAuditor：审计模型输出和阶段门禁

Runtime Layer
  EventStore：真实事件流
  PermissionPolicy：审批模式、沙盒模式、命令风险判断
  ToolRegistry：统一工具注册、权限判断、事件记录

Tool Layer
  code.search_files
  code.read_file
  code.git_diff
  code.write_file
  code.apply_patch
  command.run

Sandbox Layer
  SandboxManager：本地 / GitHub 仓库沙盒创建
  CheckpointManager：写入前文件快照
  RollbackService：按检查点回退、全仓回退

Memory Layer
  记录需求、决策、Agent turn、仓库画像、Skill 命中

Preview / Verification
  ProcessRegistry：启动沙盒预览命令
  StackDetector：选择验证命令
```

## 核心约束

1. Agent 不能直接读写任意路径，只能通过 ToolRegistry。
2. ToolRegistry 必须先调用 PermissionPolicy。
3. 写入工具必须声明 `requiresCheckpoint=true`。
4. `code.write_file` 和 `code.apply_patch` 写入前必须创建 checkpoint。
5. 非可信命令默认返回 `needsApproval`。
6. 高风险命令不能通过普通命令工具绕过。
7. 全仓回退只能通过专门 API，并且必须显式确认。
8. 所有关键信息都写入 event stream。

## 工具调用计划

工具调用计划文件：

```text
workspace/conversations/<conversationId>/tool-call-plan.json
```

状态流转：

```text
waiting_confirmation -> approved -> running -> completed
                         |            |
                         |            -> failed / waiting_approval
```

计划包含：

- 需求。
- 仓库和沙盒。
- 步骤列表。
- 每步工具 id、输入、风险等级、是否需要审批、是否需要 checkpoint。
- 执行证据：tool results、checkpoints、diff files、verification results。
- Codex 复用机制标记。

## 事件模型

事件文件：

```text
workspace/conversations/<conversationId>/events.jsonl
```

当前关键事件：

```text
sandbox.create.begin
sandbox.create.end
turn.started
user.message
agent.message
approval.resolved
approval.requested
tool_plan.created
tool_plan.approved
tool_plan.execution.begin
tool_plan.step.begin
tool.call.begin
tool.call.end
tool_plan.step.end
tool_plan.execution.end
rollback.checkpoint.begin
rollback.checkpoint.end
rollback.original.begin
rollback.original.end
preview.command.begin
preview.command.end
turn.completed
```

中间对话区应优先展示 Agent 的真实输出；右侧展示事件、diff、checkpoint 和验证证据。
