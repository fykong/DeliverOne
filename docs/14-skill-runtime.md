# Skill Runtime

## 目的

本模块解决第四个框架缺口：Skill 不只是静态文档列表，而是 Agent 每轮执行前的运行时约束层。

借鉴 Codex 的机制：

- 先根据任务选择 Skill。
- 读取 `SKILL.md` 的核心内容。
- 提取硬限制和流程约束，显式注入模型上下文。
- 只暴露 references/scripts 文件名，后续按需渐进读取。
- 把 Skill 选择写入事件流，便于审计。

## 落地文件

```text
server_py/skills/runtime.py
server_py/memory/preflight_service.py
server_py/agent/planning_agent.py
server_py/agent/tool_plan_drafter.py
server_py/app.py
shared/src/index.ts
client/src/shared/api.ts
```

## API

```text
POST /api/skills/select
```

请求：

```json
{
  "conversationId": "conv_xxx",
  "requirement": "我要修改页面并支持预览和一键回退"
}
```

返回命中的 Skill，并包含：

```text
runtime.selectedReason
runtime.contentChars
runtime.truncated
runtime.constraints
runtime.references
runtime.scripts
```

## 当前能力

- 基础 Skill 默认启用：
  - `agent-delivery-flow`
  - `repo-context`
- 触发词命中后启用专项 Skill：
  - `sandbox-preview`
  - `rollback-guard`
- `PreflightService` 改为通过 Skill Runtime 选择 Skill。
- `PlanningAgent` 会把 Skill runtime 约束传给模型。
- `ToolPlanDrafter` 会把 Skill runtime 约束传给结构化工具计划生成器。
- 事件流记录 `skill_runtime.selected`。

## 已验证

中文 UTF-8 请求：

```text
我要修改页面并支持预览和一键回退
```

命中：

```text
agent-delivery-flow
repo-context
sandbox-preview
rollback-guard
```

## 当前不足

- references/scripts 目前只发现文件名，还没有按需读取内容。
- Skill 选择仍是触发词规则，后续需要加入模型辅助路由和历史成功模式。
- 前端还没有展示 Skill 命中原因和硬限制。
