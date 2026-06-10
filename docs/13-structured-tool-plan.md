# Structured Tool Plan

## 目的

本模块解决第三个框架缺口：工具计划不能只靠前端按钮或固定默认步骤，而要让模型在受控工具目录内输出结构化 JSON，然后由审计器检查风险，再交给运行时执行。

借鉴 Codex 的机制：

- ToolDefinition：模型只能从工具目录选择工具。
- approval gate：命令和高风险步骤进入审批提示。
- patch/read discipline：写代码前必须先读上下文、定位文件和检查 diff。
- deterministic fallback：模型输出不可用时回退到确定性默认工具计划，不能让流程中断。

## 落地文件

```text
server_py/agent/tool_plan_drafter.py
server_py/audit/plan_auditor.py
server_py/agent/orchestrator.py
server_py/agent/tool_call_plan.py
shared/src/index.ts
```

## 当前能力

- `ToolPlanDrafter` 会在用户确认方案后调用当前模型，要求输出纯 JSON。
- `ToolPlanDrafter.draft_repair` 会在工具计划失败后调用当前模型生成修复计划。
- 修复计划模型 prompt 会收到失败步骤、stdout/stderr tail、验证证据、diff evidence、最近 audit、memory 和已读取文件内容。
- JSON 顶层必须包含 `steps`。
- 每个 step 必须包含：
  - `toolId`
  - `title`
  - `purpose`
  - `input`
- `PlanAuditor.audit_structured_tool_plan` 会检查：
  - 工具是否存在。
  - 每步是否有 input。
  - 是否写入发生在读取上下文之前。
  - 命令步骤是否需要审批提示。
  - 写入步骤是否有 reason。
- `ToolCallPlanService` 会把生成来源和审计结果写入 `tool-call-plan.json`。
- 修复计划统一使用 `generation.source = repair-loop`。
- 修复计划会记录 `repairOfPlanId`、`repairSequence`、`repairAttempt` 和 `repairPolicy`。
- 修复模型在没有 `readFiles` 时禁止生成 `code.apply_patch`。
- 修复模型如果 patch 未读取过的既有文件，后端会拒绝该模型计划并回退为证据收集计划。
- 后端会从失败日志提取候选文件路径，并只把真实存在于沙盒仓库内的相对路径加入 `code.read_file`，避免把绝对路径拼成错误路径。
- 修复计划如果缺少验证步骤，后端会自动补复验命令，优先复跑失败命令。

## 计划文件新增字段

```json
{
  "generation": {
    "source": "model",
    "rawResponse": "...",
    "fallbackReason": null
  },
  "audits": []
}
```

`source` 可能是：

- `model`：模型成功输出结构化工具计划。
- `fallback`：模型不可用、JSON 解析失败或审计阻断，使用默认计划。
- `heuristic`：旧接口直接创建计划时使用确定性默认计划。
- `repair-loop`：工具执行失败后由 Verifier 和 repair loop 生成的修复计划。

## 已验证

真实 Ark 模型 smoke：

```text
submitPhase = waiting_plan_confirmation
approvePhase = waiting_tool_plan_confirmation
generationSource = model
stepCount = 4
auditVerdict = warning
stateWarnings = 0
```

`auditVerdict = warning` 是预期结果，因为命令步骤会提示审批风险。

修复闭环 smoke：

```text
构造 npm test 失败
-> Verifier 记录失败审查
-> draft_repair 调用 Doubao，生成 repair-loop 计划
-> repair plan 状态保持 waiting_confirmation
-> 确认并执行 repair plan 后复跑验证
-> 失败后继续生成第二轮 repair-loop 计划
```

关键结果：

```text
firstRepairGenerationSource = repair-loop
firstRepairFallbackReason = null
firstRepairStepInputs = [code.search_files, code.read_file(package.json), command.run(npm test)]
secondRepairSequence = 2
```

## 当前不足

- 模型可以生成修复计划，但修复 patch 的质量控制仍需要加强，例如基于失败类型选择补读文件、生成最小改动、复验后总结可复用策略。
- 审计器和 Reviewer 已接入，但对复杂跨文件 patch 的语义审查还不够。
- 前端右侧已有 repair 信息，但还缺 repair plan 前后对比、模型 raw JSON 抽屉和失败聚类视图。
