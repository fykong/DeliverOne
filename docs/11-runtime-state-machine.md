# Runtime State Machine

## 目的

本模块解决第一个框架缺口：任务状态不再散落在前端按钮和后端方法里，而是由后端统一记录、校验和暴露。

借鉴 Codex 的机制：

- thread history / event reducer：每个状态变化都成为可追踪记录。
- approval gate：等待确认、确认后执行、执行中、失败、完成都有明确阶段。
- sandbox-first execution：进入代码读写前必须已经有 conversation sandbox。

## 落地文件

```text
server_py/runtime/state_machine.py
server_py/conversations/store.py
server_py/app.py
shared/src/index.ts
```

## 当前能力

- 定义统一 `AgentPhase` 状态集合。
- 定义允许的状态转移表。
- 每次状态变化写入 `lastTransition`、`stateTransitions`、`stateWarnings`。
- 会话列表返回 `stateWarningCount`，便于 UI 后续提示异常转移。
- API：
  - `GET /api/runtime/state-machine`
  - `GET /api/conversations/{conversationId}/state`

## 当前策略

第一版使用 `record-and-warn` 模式：

- 合法转移：正常记录。
- 非法转移：不阻断现有功能，记录 warning。

原因是当前系统还处于框架搭建阶段，已有 planning、tool plan、rollback、preview 仍需要稳定运行。后续 Agent Orchestrator 接管主流程后，再逐步把关键路径切成 strict 模式。

## 下一步

下一步要做 Agent Orchestrator 主循环：

```text
需求输入
-> preflight
-> clarify / planning
-> plan confirmation
-> tool plan generation
-> tool plan approval
-> tool execution
-> observe evidence
-> verify
-> delivery package
```

Orchestrator 会调用 Runtime State Machine，而不是让前端自己拼流程。
