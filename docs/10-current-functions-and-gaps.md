# 当前功能和缺口

这份文档只记录当前项目真实具备的能力，不写展示口号。

## 1. 模型配置

已有功能：
- `config/model-providers.json` 管模型提供商。
- `config/model-settings.json` 保存默认模型。
- `GET /api/models` 读取模型配置。
- `PUT /api/models` 保存模型配置。
- 新 conversation 使用保存后的默认模型，旧 conversation 不强制变更。
- Ark / Doubao 调用由 `server_py/models/ark_client.py` 负责。

缺口：
- 前端模型设置入口还不够产品化。
- 缺模型连通性测试按钮和错误解释。
- 缺多模型 fallback 和按任务类型选模型。

## 2. 仓库接入和沙盒

已有功能：
- `POST /api/sandboxes/local` 支持本地路径仓库。
- `POST /api/sandboxes/github` 支持公开 GitHub 仓库。
- `GET /api/runtime/sandbox/{conversationId}` 返回当前对话沙盒 runtime 快照。
- 沙盒 runtime 快照聚合：仓库、沙盒路径、文件树、diff、预览进程、预览 smoke、验证报告、checkpoint、交付包、回退事件。
- 沙盒 Runtime 快照会自动生成验证命令和预览命令推荐，包含命令、阶段、来源、理由、置信度和预览端口。
- 右侧“沙盒 Runtime”面板展示进程、文件、变更、检查点、预览、验证、交付和回退生命周期。
- 右侧“沙盒 Runtime”面板会显示推荐验证命令和推荐预览命令。
- 每个 conversation 都有独立沙盒：

```text
workspace/conversations/<conversationId>/repo
```

- 后端通过 conversation state 找当前沙盒，不使用全局 current repo。
- `GET /api/sandbox/files/{conversationId}` 返回沙盒文件树。
- `GET /api/sandbox/file/{conversationId}` 返回当前沙盒单文件内容。

缺口：
- GitHub 第一版只支持公开仓库。
- UI 缺仓库切换、重新拉取、清理沙盒。
- 沙盒 Runtime 已有聚合快照，但还缺进程日志抽屉、沙盒清理、仓库重拉取和资源限制策略。
- 沙盒文件树已有右侧入口，但还缺搜索、折叠目录、二进制文件处理和大文件策略。

## 3. Agent 编排

已有功能：
- `POST /api/agent/orchestrator` 是前端主入口。
- 支持 `submit_requirement`、`approve_plan`、`approve_tool_plan`、`execute_tool_plan`、`repair_failed_plan`、`refresh`。
- 旧的 `POST /api/agent/tool-plan/execute` 已收口到 Orchestrator，不再绕过 Verifier、repair loop、runtime snapshot 和事件流。
- 每次返回统一 bundle：conversation、turn、toolPlan、checkpoints、events、processes、files、runtimeSnapshot、sandboxRuntime、nextActions。
- `GET /api/runtime/snapshot/{conversationId}` 返回统一任务状态机快照。
- `GET /api/runtime/task-state/{conversationId}` 返回持久化任务状态机摘要。
- `POST /api/runtime/task-state/edit` 支持人工编辑任务状态机。
- Runtime 快照覆盖：需求、澄清、方案、工具计划、审批、执行、验证、修复、交付、回退、预览、记忆。
- 每个阶段都有 `status`、`owner`、`summary`、`evidence` 和 `actions`。
- 每次生成 Runtime 快照时，后端会同步写入 `workspace/conversations/<conversationId>/runtime/task-state-machine.json`。
- 持久化状态机记录 `schemaVersion`、当前 `phase`、总状态、主链路阶段、阶段顺序、证据、阻断原因、下一步动作、最近状态转移和来源快照。
- 主链路阶段固定为：需求 → 澄清 → 方案 → 工具计划 → 审批 → 执行 → 验证 → 修复 → 交付 → 回退；预览和记忆作为辅助阶段进入同一 Runtime 快照。
- 状态机编辑支持：给阶段写备注、暂停阶段、恢复阶段、手动覆盖下一步动作、清除下一步动作覆盖。
- 状态机编辑会写入 `stageControls`、`nextActionOverride` 和 `editHistory`，并写入 `task_state.edited` 事件。
- Runtime 快照会回读持久化状态机控制项；被暂停的阶段会立即显示为阻断，并进入 blockers。
- 状态机人工控制已进入 Agent 上下文：memory snapshot 会返回 `taskState`，ContextPack 会新增 `runtimeControl` 片段。
- PlanningAgent、ToolPlanDrafter、Clarifier、Reviewer、Verifier 都会收到任务状态机控制信息。
- Orchestrator 已在入口执行状态机硬拦截：阶段暂停时禁止 `approve_plan`、`approve_tool_plan`、`execute_tool_plan`、`repair_failed_plan` 等推进动作。
- Orchestrator 已支持人工下一步覆盖拦截：如果用户把下一步覆盖为指定动作，其他推进动作会被拒绝并写入 `task_state.guard.blocked` 事件。
- 右侧“任务状态机”面板会显示状态机是否已持久化、阶段数、状态转移次数、人工控制次数、暂停阶段、下一步覆盖和状态机文件路径。
- 右侧“任务状态机”面板支持对当前阶段执行“备注 / 暂停 / 恢复 / 下一步”操作。
- 右侧“任务状态机”面板展示当前阶段、证据计数、阻断原因和阶段状态。
- PlanningAgent、ToolPlanDrafter、ExecutorAgent 会接收 preflight context、memory 和 skills。
- PlanAuditor 会审查计划阶段和工具计划。
- Clarifier / Reviewer / Verifier 角色骨架已接入 orchestrator。
- Clarifier 在提交需求时优先调用默认模型输出 JSON 审计，解析失败会回退确定性规则。
- Reviewer 在工具计划生成后优先调用默认模型审查步骤、diff 检查和 checkpoint 要求，规则结果会作为安全兜底合并。
- Verifier 在工具计划执行后优先调用默认模型审查失败步骤、验证证据、diff 和修复方向，解析失败会回退确定性规则。
- Clarifier / Reviewer / Verifier 的摘要、发现和建议会写入事件流，并展示在中间对话。
- 工具计划失败或等待审批后，可通过 orchestrator 生成修复诊断计划。
- 工具计划执行失败后，后端 Orchestrator 会根据 Verifier 结论自动生成下一轮“等待确认”的修复计划。
- `execute_tool_plan` 返回包会同时带回 `executedToolPlan`、`repairPlan` 和 `repairLoop`，前端不再自行二次判断是否创建修复计划。
- `repairLoop.created = true` 表示后端已创建下一轮待确认修复计划；`repairLoop.reason` 记录自动创建或停止原因。
- 修复计划会记录 `repairOfPlanId`、`repairSequence`、`repairAttempt`，并使用 `generation.source = repair-loop`。
- 修复计划会记录 `repairSource`，包含来源计划 id、失败摘要、失败类型、Verifier 摘要和失败步骤列表，前端可直接展示“为什么需要这轮修复”。
- 自动生成的修复计划会记录 `generation.trigger = auto`；用户手动生成的修复计划会记录 `generation.trigger = manual`。
- Verifier 会输出 `failureClass` 和 `repairPolicy`：环境问题、计划问题、代码问题、需求问题、外部权限问题分开处理。
- 自动修复不再按固定 2 轮停止；现在按“总修复链路上限”和“代码修复次数上限”控制。
- 依赖缺失、脚本缺失、版本冲突等环境问题不消耗代码修复次数。
- 类型错误、lint、测试失败、运行时报错等代码问题会消耗代码修复次数。
- 外部授权、API key、需求边界冲突会停止自动修复，要求先处理配置、权限或需求澄清。
- 修复计划可由模型生成 `code.search_files`、`code.read_file`、`code.apply_patch`、`command.run`、`code.git_diff` 步骤。
- 修复计划如果没有验证步骤，后端会自动补一个 `command.run` 复验步骤，优先复跑失败命令，否则使用 package scripts 中的 typecheck / lint / test / build。
- 修复计划会从失败日志中提取候选文件路径，例如 `src/App.tsx(12,5)`、`src/App.tsx:12:5`、`File "app.py", line 8`，并自动加入 `code.read_file` 步骤。
- 修复计划会优先读取真实失败文件，再考虑 patch，避免只凭日志直接写完整文件。
- 失败日志里的绝对路径会被规范化为沙盒仓库相对路径；如果候选文件在沙盒内不存在，不会生成错误的 `repo/Users/.../repo/file` 读文件步骤。
- `ToolPlanDrafter.draft_repair` 会把上一轮已完成的 `code.read_file` 内容注入修复模型 prompt。
- `ToolPlanDrafter.draft_repair` 的 repair prompt 已修复为真实返回 `messages`，当前 Doubao 修复计划调用 smoke 已通过，不再出现 Ark `MissingParameter: messages`。
- 模型只有在 `readFiles` 已包含目标文件完整内容时，才允许生成 `code.apply_patch`。
- 如果模型在没有读取文件内容时直接生成 `code.apply_patch`，后端会拒绝该模型计划，并回退为确定性证据收集计划。
- 如果模型 patch 了未读取过的文件，后端同样会拒绝，并要求先读取对应文件。
- `code.apply_patch` 仍使用结构化 `changes` 格式；修复计划生成后不会自动写入，必须等待用户确认工具计划。
- 前端右侧工具计划已收敛为一个主按钮：普通计划是“确认并执行”，修复计划是“确认修复并执行”，等待授权后是“继续执行”。
- 前端中间对话会展示工具执行轨迹摘要：工具名、状态、摘要和失败步骤，不再只显示“完成/暂停”。
- 前端中间对话会把执行失败显示为“未通过，需要修复”，不再把 Verifier 的 `blocked` 误读成普通暂停。
- 右侧工具计划面板会显示计划状态摘要：等待审查、执行未通过、修复计划等待确认、等待授权、执行完成。
- 右侧修复计划面板会展示来源失败步骤和 Verifier 摘要，帮助用户判断修复方向是否正确。
- 失败修复闭环 smoke 已验证：构造 `npm test` 失败后自动生成 waiting confirmation repair plan；确认并执行 repair plan 后自动复验；仍失败时继续生成第二轮 waiting confirmation repair plan。

缺口：
- Clarifier / Reviewer / Verifier 已是模型优先，但 prompt 和角色质量还需要结合真实任务继续调优。
- 自动修复已经由后端 Orchestrator 生成下一轮待确认计划，并能读取失败日志中的候选文件；patch 生成已有“必须基于已读文件内容”的硬拦截，后续还需要更强的代码语义评估和失败原因聚类。
- Runtime 快照已经会写入可恢复状态机存档，人工控制已经接入 memory、模型上下文和 Orchestrator 入口硬拦截；后续还需要做可视化状态机编辑器和基于编辑意见的工具计划自动重写。
- 中间对话还没完全由真实事件流驱动。

## 4. Skills

已有功能：
- `server_py/skills/catalog/*/SKILL.md` 存放内置中文 skills。
- SkillRuntime 会选择 skill，提取 constraints、references、scripts。
- `POST /api/skills/select` 可单独检查命中的 skills。
- preflight、PlanningAgent、ToolPlanDrafter 都已接入 Skill Runtime。

缺口：
- references/scripts 目前只发现文件，还没有按需渐进读取内容。
- Skill 路由仍偏规则触发，缺模型辅助路由。
- UI 缺 skill 命中原因、约束和引用展示。

## 5. 工具运行时

已有功能：
- `GET /api/tools` 查看工具。
- `POST /api/tools/run` 执行内置工具。
- 已有工具：`code.search_files`、`code.read_file`、`code.git_diff`、`code.write_file`、`code.apply_patch`、`command.run`、`verification.run`。
- 已接入 Browser / GitHub 风格工具：`browser.preview_smoke`、`github.inspect_repository`。
- `ToolRegistry` 统一处理权限、事件和 metrics。
- `PermissionPolicy` 已按 Codex 机制改写为 `allow / prompt / forbid` 决策模型。
- 命令执行会先检查可信前缀、持久化规则和危险命令模式。
- 高风险命令不能通过普通 `command.run` 绕过，必须走专门授权或回退接口。
- `command.run` 会返回 `stdoutTail` / `stderrTail`，供 Verifier 和修复计划判断真实失败原因。
- `code.apply_patch` 是平台自有的结构化多文件写入工具。
- `code.apply_patch` 输入 `changes`，每项包含 `relativePath`、`action`、`content`。
- `code.apply_patch` 会先创建 checkpoint，再写入或删除沙盒文件，最后返回 diff。
- `GET /api/diff/current/{conversationId}` 返回当前沙盒相对原始 HEAD 的变更列表和 unified diff。
- `GET /api/diff/file/{conversationId}?path=...` 返回单文件 diff。
- `GET /api/diff/checkpoint/{conversationId}?checkpointId=...` 返回 checkpoint 快照到当前文件的 diff。
- 右侧 diff 查看器支持“左右对比”和“统一 diff”两种模式。
- 左右对比会对同一行修改片段做行内高亮。
- Hunk 回退前会弹出二次确认预览，用户可以先看将回退的 diff 片段。
- 工具计划中的单步结果会显示 diff、checkpoint 和回退入口。
- GitHub 仓库默认工具计划会加入 `github.inspect_repository`，确认 remote、branch 和 HEAD。
- `browser.preview_smoke` 可进入工具计划，对已启动预览端口做浏览器 smoke test。
- Agent 工具计划现在使用统一工具运行时，工具目录包含内置工具和已发现的外部 MCP 工具。
- `GET /api/tools` 返回 Agent 当前可编排的完整工具目录。
- `external.*` MCP 工具可以进入工具计划，并由工具计划执行链路调用。
- `POST /api/agent/tool-plan/edit` 支持编辑工具计划。
- 工具计划编辑支持：禁用步骤、恢复步骤、修改步骤标题、修改步骤目的、修改步骤输入、填写修改原因、移动步骤顺序。
- `POST /api/agent/tool-plan/rewrite` 支持用户用自然语言描述修改意见，由当前模型重写完整工具计划。
- 工具计划编辑会写入 `editHistory` 和 `tool_plan.edited` 事件。
- 工具计划重写会写入 `tool_plan.rewritten` 和 `rewrite_plan` 编辑记录，并保持 `waiting_confirmation`，不会直接执行。
- 工具计划编辑后，后端会立即重新调用 Reviewer 审查当前计划，并把审查结果追加到 `audits`。
- 工具计划重写后同样会立即调用 Reviewer 重审，用户仍需确认后才能执行。
- 工具计划编辑后会写入任务状态机 `tool-plan` 阶段控制记录，保留用户修改原因和 Reviewer 重审结论，后续模型上下文能看到这次人工干预。
- Reviewer 的确定性规则会把“所有步骤都被禁用”判定为 blocked，避免确认后空执行。
- 工具计划确认时只看最新 Reviewer 结论；用户修正计划后，旧的 blocked 审计不会继续误拦截。
- 执行器会跳过 `skipped` 步骤，并写入 `tool_plan.step.skipped` 事件。
- 前端工具计划面板支持单步上移、下移、编辑标题/目的/参数/原因、禁用和恢复。
- 前端编辑步骤不再使用浏览器 prompt，而是使用右侧可审查编辑弹窗；保存后显示最近编辑和重审状态。
- 前端工具计划面板支持“用一句话调整计划”，把用户意见交给模型重写计划，并在中间对话显示重写摘要和 Reviewer 结论。
- 前端工具计划面板会展示最近一次编辑、编辑原因，以及编辑后 Reviewer 是否已经重审。

缺口：
- 单步工具重试和局部回退还不够细。
- 工具计划编辑已有审查弹窗、编辑原因、模型重写和 Reviewer 重审，但还缺命令字段专用编辑器、拖拽排序、批量编辑，以及重写前后的可视化计划 diff。
- 复杂增量 patch 还没有精细 diff hunk 应用能力，目前更适合写入完整文件内容。
- Diff 还缺更强的二进制文件说明和更细的跨文件 hunk 分组。

## 6. MCP

已有功能：
- `GET /api/mcp/manifest` 返回统一 MCP manifest。
- `GET /api/mcp/tools` 返回内部工具和外部工具，支持 `query` 参数按当前需求重新排序。
- `GET /api/mcp/servers` 诊断 MCP server 配置。
- `POST /api/mcp/config/validate` 校验 MCP 配置，返回 errors、warnings 和 normalized 配置。
- `GET /api/mcp/history/{conversationId}` 返回标准化 MCP / tool 调用历史，可按 `toolId` 过滤。
- `POST /api/mcp/discover` 支持 stdio MCP `tools/list`。
- `POST /api/mcp/discover` 支持 HTTP MCP `tools/list`，会执行 `initialize`、`notifications/initialized` 和 `tools/list`。
- `POST /api/mcp/run` 支持内部工具、外部 stdio MCP 和外部 HTTP MCP `tools/call`。
- HTTP MCP 调用支持 `application/json` 和 `text/event-stream` 响应，并在短会话内透传 `Mcp-Session-Id`。
- HTTP/SSE/WS 配置会校验 URL、headers、env headers、认证环境变量和 timeout；SSE/WS 当前只做配置与状态诊断。
- 外部 MCP 工具默认 `riskLevel = external`。
- 未授权外部 MCP 调用会返回 `needsApproval = true`。
- 一次性授权执行后自动失效。
- 外部 MCP 调用会写入事件和 metrics。
- 已发现的外部 MCP 工具会进入 Agent 工具目录，可被 ToolPlanDrafter 选择。
- 工具计划执行 `external.*` 步骤时，会通过统一工具运行时转发到 MCP Adapter。
- 工具目录会带 `recommendationScore`、`recommendationReason`、`recommendationSignals` 和 `capabilityTags`，用于前端和 Agent 解释为什么推荐某个工具。
- 工具执行结束事件会写入安全截断后的 `result`，支持调用结果审查。
- 工具计划执行时，内置工具和外部 MCP 工具事件都会写入 `planId`、`stepId` 和 `sandboxId`，便于把证据归因到具体步骤。
- 新版本 MCP 调用历史会保存安全截断后的 `input`，支持从历史重放单条调用。
- `POST /api/mcp/replay` 可以按历史 entry 重放 MCP / 内置工具调用，重放仍进入统一事件和 metrics。
- 右侧 MCP 面板可发现工具、授权和撤销授权。
- 右侧 MCP 面板展示后端推荐工具、推荐理由、transport、endpoint、输入 schema、调用历史、所属 plan/step 和完整 payload 抽屉。
- 右侧 MCP 调用结果抽屉对已保存输入的历史提供“重放调用”按钮。
- `GET /api/mcp/config` 读取 MCP 配置。
- `PUT /api/mcp/config` 保存 MCP 配置，并清空外部工具发现缓存。
- 右侧 MCP 面板支持直接编辑 JSON 配置、保存前校验和校验提示。

实现方式：
- `server_py/mcp/adapter.py` 负责 manifest、发现、路由、审批和事件。
- `server_py/mcp/stdio_client.py` 负责 `initialize`、`notifications/initialized`、`tools/list`、`tools/call`。
- `server_py/mcp/http_client.py` 负责 Streamable HTTP 风格 JSON-RPC 请求，兼容 JSON 和 SSE 响应。
- `ToolContext` 现在携带 `plan_id` 和 `step_id`，由工具计划执行器注入，避免把内部元数据发送给外部 MCP server。
- stdio 和 HTTP 当前都是 stateless：每次发现或调用都会建立短会话，完成后关闭或丢弃 session。

缺口：
- SSE/WS MCP 长连接还没接。
- stdio / HTTP MCP 还没有长连接生命周期、连接池和会话恢复。
- MCP 推荐排序目前是规则加权，还没有模型辅助重排。
- MCP 配置编辑目前仍是 JSON 编辑器，后续需要表单化编辑和更完整的 schema 提示。
- MCP 调用历史已有 plan/step 字段和单条重放入口，但还缺按 plan/step 的分组视图、批量重放和失败前后对比。

## 7. 审批和权限

已有功能：
- `GET /api/policy` 查看策略。
- `GET /api/policy/matrix` 查看风险矩阵。
- `GET /api/approvals/{conversationId}` 查看授权。
- `POST /api/approvals/grant` 创建授权。
- `POST /api/approvals/deny` 拒绝本次工具调用并记录原因。
- `POST /api/approvals/revoke` 撤销授权。
- 支持 `once`、`turn`、`session` 三种授权范围。
- 命令和外部能力都会走审批。
- 可信命令前缀写在 `config/agent-policy.json`，可以后续按项目持久化扩展。
- 普通命令来自用户已审查的工具计划时可在沙盒执行；危险命令即使在计划中也会进入单独审批。
- 审批记录支持绑定原始 `approval.requested` 事件。
- 右侧审批面板支持审查弹窗、一次授权、会话授权、拒绝原因和审批历史。

缺口：
- `turn` 授权还没和完整 Agent turn 生命周期强绑定。
- 审批弹窗还缺更细的风险解释和工具输入字段化展示。

## 8. Checkpoint 和回退

已有功能：
- 写文件前自动 checkpoint。
- 结构化多文件写入前自动 checkpoint。
- `GET /api/checkpoints/{conversationId}` 查看 checkpoint。
- `POST /api/rollback/checkpoint` 回退本次任务涉及文件。
- `POST /api/rollback/checkpoint-file` 只回退某个 checkpoint 记录的单个文件。
- `POST /api/rollback/checkpoint-hunk` 只回退某个 checkpoint diff 的单个 hunk。
- `POST /api/rollback/original` 确认后全仓回到沙盒原始 HEAD。
- 右侧“文件与变更”面板已有回退 tab，可以查看 checkpoint diff 并触发 checkpoint 回退。
- 右侧 checkpoint diff 可以对单个文件执行“回退此文件”。
- 右侧 checkpoint diff 可以对单个变更块执行“回退此段”。
- 右侧 checkpoint diff 对单个变更块执行回退前会先弹出 diff 预览确认。
- Diff 查看器支持“原始 HEAD / 当前沙盒”“检查点 / 当前沙盒”的左右对比列标题。
- Diff 查看器支持折叠未变更上下文。
- 工具计划步骤会绑定对应 checkpoint / diff 入口，可以从步骤直接审查和回退。
- 所有回退操作都会生成回退证据报告，记录回退前 diff/status、回退后 diff/status、影响文件、操作目标、报告路径。
- 回退证据报告保存在 `workspace/conversations/<conversationId>/rollback/rollback_*.json`。
- 回退接口会返回 `rollbackReport` 摘要，前端对话流会显示证据报告路径。
- 沙盒 Runtime 快照会读取最近一次回退报告，右侧“沙盒 Runtime”和“回退”面板会展示回退前后变更数量与影响文件。
- 交付包会绑定 `rollbackGate`：如果已有最近一次回退报告，会记录回退前后变更数量、影响文件和报告路径；否则根据 checkpoint 判断是否具备回退门禁。
- `GET /api/rollback/reports/{conversationId}` 返回当前对话所有回退报告摘要。
- `GET /api/rollback/report/{conversationId}/{reportId}` 返回单个回退报告完整详情，包含回退前 diff/status、回退后 diff/status、影响文件和目标信息。
- 右侧“回退”面板已有回退报告查看器，可以查看最近 6 条回退报告，并展开回退前/回退后的 diff 或 status。
- 回退报告查看器会把 unified diff 按文件折叠展示，并对新增、删除、hunk 和元信息做行级高亮。
- 回退报告查看器支持按文件筛选，便于在大 patch 中只审查某个文件。
- 回退报告查看器复用统一左右 diff 组件，支持“左右 / 统一”模式切换和上下文折叠。
- 回退报告查看器支持 diff 内搜索，并在左右/统一两种视图中高亮命中内容。
- 回退报告会自动生成 `confirmation`：比较回退前后变更文件数和 diff 字节数，标记 `clean / improved / unchanged / expanded / failed / unknown`，并给出是否达到预期的摘要。
- 沙盒 Runtime、回退面板和交付包 `rollbackGate.latest` 都会透传并展示最近一次回退确认结果。

缺口：
- Hunk 回退已有回退前预览和回退后自动确认摘要，后续还缺更细的 hunk 级 before/after 可视化确认。

## 9. 预览和验证

已有功能：
- `POST /api/preview/start` 在沙盒启动 dev server。
- 预览启动命令会优先使用 `SandboxRuntime.commandRecommendations.preview.primary`，并把推荐端口传给后端。
- Vite 项目会推荐 `npm run dev -- --host 127.0.0.1 --port 5173`；Next 项目会推荐 `npm run dev -- --hostname 127.0.0.1 --port 3000`。
- 前端“实时预览”面板会展示推荐预览命令和推荐理由，并支持一键填入推荐命令。
- 前端“实时预览”面板已接入 iframe：只有检测到当前对话沙盒存在运行中的预览端口时才显示页面，避免未启动时出现无意义的拒绝连接大框。
- iframe 工具栏支持刷新、打开外部页面和触发当前端口 smoke test。
- `POST /api/preview/stop` 停止预览进程，Windows 下会停止进程树。
- `POST /api/preview/smoke-test` 等待端口、请求页面、保存 HTML、生成 smoke report、尝试浏览器截图。
- smoke report 内置质量检查：端口、HTTP、HTML 非空、运行后 DOM、浏览器错误、截图生成六层门禁，并输出 `failureClass`、checks、warnings。
- smoke test 会优先用 Chromium DevTools Protocol 读取运行后 DOM，保存到 `preview/runtime-dom.html`，记录 DOM 字节数、标题和可见文本长度；CDP 不可用时降级为 headless `--dump-dom`。
- smoke test 会优先用 CDP 捕获 `Runtime.consoleAPICalled`、`Runtime.exceptionThrown` 和 `Log.entryAdded`；CDP 不可用时降级为 headless stderr 疑似错误检查。
- smoke test 支持验收断言：`expectedTexts` 检查运行后页面文字，`requiredSelectors` 检查 CSS selector 是否存在。
- 后端新增本地预览验收提示生成器：从明确文案、标题、按钮、输入框、表格、侧边栏、文件树、diff、iframe 等需求信号中生成保守的 `expectedTexts` / `requiredSelectors`。
- `ToolPlanDrafter` 会把 `previewAcceptanceHints` 注入模型工具计划 prompt；如果模型选择 `browser.preview_smoke`，应带上这些断言。
- `ToolCallPlanService` 会兜底补齐 `browser.preview_smoke` 的断言输入，避免模型漏写后只验证“页面能打开”。
- 验收断言会进入 `quality.checks`；断言失败时 `previewGate` 和 Verifier 不能把前端交付判定为可靠。
- `GET /api/preview/screenshot/{conversationId}` 安全读取当前对话 `preview` 目录内截图，供前端直接展示。
- `preview.smoke.end` 事件会记录 URL、HTTP 状态、HTML 标题、HTML 字节数、运行后 DOM、控制台错误数、截图路径、质量检查和 smoke report 路径。
- 工具计划执行 `browser.preview_smoke` 后，会把结果写入 `toolPlan.evidence.previewResults`，供 Verifier、证据面板和交付包使用。
- `toolPlan.evidence.previewResults` 会记录断言摘要、失败文字、失败 selector、运行后 DOM、控制台错误和截图路径。
- 手动点击右侧“预览验证”生成的 `preview/smoke-report.json` 会同步到当前工具计划 `toolPlan.evidence.previewResults`，不会只停留在 memory 和文件系统里。
- 手动点击验证生成的 `delivery/verification-report.json` 会同步到当前工具计划 `toolPlan.evidence.verificationResults`。
- Orchestrator 在执行计划后调用 Verifier 前，会自动吸收最新的验证报告和预览 smoke 报告，避免 Verifier 漏掉用户刚刚跑过的证据。
- 右侧证据面板会显示验证/预览证据来源、报告路径、阶段、耗时、截图和控制台错误。
- 沙盒 Runtime 快照会读取最近一次 `preview/smoke-report.json`，展示预览状态、URL、HTML 标题、HTML 字节数、运行后 DOM、控制台错误数和截图路径。
- 沙盒 Runtime 快照会带上最近一次预览质量检查，右侧面板可展示具体失败层。
- 没有 smoke report 时，沙盒 Runtime 会根据运行中进程和端口显示预览是否已启动。
- 右侧预览面板支持对运行中端口触发 smoke test，并展示截图、质量检查、运行后 DOM、控制台错误数、断言结果和失败原因。
- `POST /api/verification/run` 执行 build/typecheck/lint/test 或传入验证命令。
- 验证命令由 `StackDetector` 统一推荐：优先 typecheck，其次 lint、test、build；Python 项目会尝试 pytest / ruff。
- `VerificationRunner` 仍兼容手动传入命令；未传入时使用推荐命令。
- 沙盒 Runtime 快照会读取最近一次 `delivery/verification-report.json`，把验证状态进入统一生命周期。
- Verifier prompt 已要求前端、页面、UI、预览相关任务检查 `previewResults`；截图失败、HTTP 失败、HTML 为空、运行后 DOM 失败、浏览器错误存在或验收断言失败时不能直接判定交付可靠。
- Verifier 判断失败后，前端会自动生成下一轮修复计划，右侧显示失败原因、修复尝试编号和来源计划。
- 修复计划确认执行后会复跑失败命令或仓库最小验证；如果仍失败，前端会根据 Verifier 的修复策略继续生成下一轮待确认修复计划。
- 如果上一轮 `browser.preview_smoke` 有预览证据，修复计划会保留同一组 `expectedTexts` / `requiredSelectors`，并在修复后自动加入“复跑预览验收”步骤。
- 失败日志中的源码路径会进入下一轮修复计划，作为 `code.read_file` 的输入。

缺口：
- 预览和验证命令推荐已经进入 runtime，实时预览 iframe、截图查看器、运行后 DOM 检查、CDP 控制台错误采集和基础文字/selector 断言已接入；还缺命令编辑历史、截图像素级异常判断、点击/表单等浏览器交互断言和 iframe 不能嵌入时的代理/降级方案。

## 10. 交付包

已有功能：
- `POST /api/delivery/package` 生成交付包。
- 生成交付包前，后端会先同步最近一次验证报告和预览 smoke 报告到当前工具计划证据，避免交付报告漏掉手动触发的验证。
- 交付报告会绑定 `verificationGate`。
- 交付报告会绑定 `previewGate`，优先读取最近一次 `preview/smoke-report.json`，否则退回工具计划 `previewResults`。
- 交付报告的 `previewGate` 会记录运行后 DOM、控制台错误数、截图路径、HTML 标题和质量检查，供人工审查和 Verifier 复用。
- 交付报告的 `previewGate` 会记录验收断言结果，便于判断页面是否满足用户需求，而不只是成功打开。
- 交付报告会绑定 `rollbackGate`，记录 checkpoint 可用性、最近一次回退报告路径、回退前后变更数量和影响文件。
- `verificationGate` 优先读取最近一次 `verification-report.json`；如果没有独立验证报告，会退回工具计划里的验证命令证据。
- 如果没有任何验证证据，交付报告会标记 `verificationGate.status = missing`，并在 notes 中提示这是审查草稿。
- 如果没有任何预览证据，交付报告会标记 `previewGate.status = missing`，并提示前端或页面交付建议补充浏览器 smoke test。
- 如果没有任何 checkpoint，交付报告会标记 `rollbackGate.status = missing`，并提示写入类交付不可直接上线。
- 右侧交付包面板展示验证门禁状态和摘要。
- 右侧交付包面板展示预览门禁状态、摘要、质量检查、运行后 DOM、控制台错误数、断言结果和截图预览。
- 右侧交付包面板展示回退门禁状态、摘要，以及最近一次回退报告的前后变更数量和报告路径。
- 右侧交付包面板支持生成交付包。
- 右侧交付包面板支持确认后应用到原始本地仓库。
- `GET /api/delivery/preview/{conversationId}` 会读取当前对话的 `delivery-report.md` 和 `changes.patch`，并限制在当前对话交付目录内。
- 右侧交付包面板已支持直接展开查看交付报告 Markdown 和 Patch Diff，内容过大时会截断并标记。
- 交付报告 Markdown 已支持结构化渲染：标题、段落、列表、引用、表格、代码块、行内代码、加粗和链接会以可审查样式展示，不再只显示纯文本。
- 交付包 Patch Diff 已复用统一 diff 查看器，支持按文件筛选、按文件折叠、左右并排对比、增删统计和新增/删除/hunk 行级高亮。
- 交付包 Patch Diff 支持 diff 内搜索，并在左右/统一两种视图中高亮命中内容。
- 交付目录：

```text
workspace/conversations/<conversationId>/delivery/
```

- 包含 `delivery-report.json`、`delivery-report.md`、`changes.patch`。
- `POST /api/delivery/apply-to-source` 会先备份原文件，再把沙盒改动应用回本地原仓库。

缺口：
- 交付报告已支持基础 Markdown 结构化渲染，后续还缺更完整的 GFM 能力，例如任务列表、复杂嵌套表格和锚点目录。
- 缺 GitHub PR 创建。

## 11. Memory

已有功能：
- 每个 conversation 都有独立 memory 目录，按 repo / conversation / delivery / skill 分层保存。
- 记录需求、用户决策、Agent 输出、失败经验、交付记录、预览验证和命中的 Skills。
- 借鉴 Codex 的项目指令机制：沙盒仓库里存在 `AGENTS.md` 或 `AGENTS.override.md` 时，会写入 `memory/repo/project-instructions.md`。
- 生成仓库画像：保存 repo profile、package scripts、根目录模块地图和关键文件列表。
- 生成结构化 memory entries：把仓库画像、项目指令、当前需求、用户决策、失败经验、Agent 输出、交付、预览、Skills 转成可召回条目。
- 有多信号召回：按 BM25、短语、源码路径、代码符号、标签、重要性、时间衰减、置顶、长期记忆和多样性选择召回相关记忆。
- 召回结果写入 `memory/conversation/recall-items.json`，召回诊断写入 `memory/conversation/recall-diagnostics.json`。
- 已有 workspace 级长期记忆：重要仓库画像、项目指令、用户决策、失败经验、交付记录和 Skills 会沉淀到 `workspace/memory/long-term-memory.json`。
- 长期记忆支持仓库级 namespace，默认只召回当前仓库和 workspace 级记忆。
- 长期记忆支持 `pin` / `forget`，后端接口和右侧 Memory 面板按钮都已接入。
- 长期记忆支持用户手动新增 / 编辑：`POST /api/memory/manual` 会写入当前仓库 namespace，保存为 `lt_manual_*` 条目，并进入后续 snapshot、召回候选和 ContextPack。
- 手动长期记忆会生成 `lastPatch` 审计摘要，记录新增 / 更新、变更字段、before / after 快照和同名 / 高相似内容冲突提示。
- 模型可以生成长期记忆草案：`POST /api/memory/patch/draft` 会调用默认模型整理候选记忆，模型不可用或 JSON 解析失败时回退到确定性规则。
- 长期记忆草案默认不写入；用户在右侧 Memory 面板审查候选、冲突提示和写入影响后，才通过 `POST /api/memory/patch/apply` 写入。
- Memory snapshot 返回 `longTerm` 列表，包含当前仓库 namespace、长期记忆文件路径、数量和最多 80 条当前可见长期记忆。
- 右侧 Memory 面板支持搜索标题、内容、标签和来源路径，支持按记忆类型筛选。
- 右侧 Memory 面板支持新增长期记忆、编辑 `lt_*` 长期记忆、置顶和遗忘。
- 右侧 Memory 面板会展示最近一次 memory patch 摘要、变更字段和冲突提示，避免长期记忆被静默覆盖。
- 右侧 Memory 面板支持“模型整理”：先展示模型生成的长期记忆草案，再由用户单条确认写入。
- 长期记忆 snapshot 已返回 `sourcePhase`、`sourceConversationId`、`sourceEntryId` 和最近 12 条 `patchHistory`。
- 右侧 Memory 面板会在每条长期记忆上显示来源阶段，并提供完整 patch 历史折叠区。
- 成功/失败证据会沉淀到 `workspace/memory/patterns.json`，形成第一版可复用修复策略库。
- Search Intent 会把需求拆成检索线索、文件提示、风险提示和验证提示，写入 `memory/conversation/search-intent.json`。
- Task Ledger 会把当前理解、阶段状态、关卡检查、阻塞点、召回上下文、命中 Skill、风险和下一步写入 `memory/conversation/task-ledger.json`。
- 中间对话顶部会展示任务阶段条，右侧 Memory 面板会展示任务账本详情，方便用户判断 Agent 是否理解需求、卡在哪一步。
- ContextPack 已加入 `memory-recall` 片段，PlanningAgent、ToolPlanDrafter、Clarifier、Reviewer、Verifier、repair loop 都能拿到 memory。
- ContextPack 已加入 `runtimeControl` 片段，模型能看到用户暂停阶段、人工下一步覆盖、阻断原因和状态机文件路径。
- Memory snapshot 已返回 `taskState`，用于计划、工具计划、角色审查和修复循环遵守用户控制。
- 右侧已有 Memory 面板，能看到条目数量、候选数量、长期记忆数量、召回策略、召回原因、分数、重要性、来源文件和 ContextPack 片段。
- 仓库扫描会跳过 `.git`、`node_modules`、`dist`、`build`、`.next`、`coverage`、`.venv` 等目录，避免真实项目扫描过慢。

实现方式：
- `server_py/memory/memory_service.py` 负责 layout、记录、仓库画像、项目指令采集、结构化条目和召回。
- `server_py/memory/retrieval.py` 负责多信号召回排序。
- `server_py/memory/long_term_store.py` 负责 workspace 级长期记忆。
- `server_py/memory/long_term_store.py` 的 `upsert_manual` 负责用户手动维护长期记忆，并保留仓库级 namespace、patchHistory 和 lastPatch 审计证据。
- `server_py/memory/patch_service.py` 负责模型生成长期记忆草案，复用默认模型、Memory snapshot、长期记忆审查和 metrics。
- `server_py/memory/pattern_store.py` 负责成功/失败模式沉淀。
- `server_py/memory/search_intent.py` 负责模型或规则生成检索意图。
- `server_py/memory/task_ledger.py` 负责生成当前可审查任务账本。
- `server_py/memory/context_pack.py` 负责把 repo、需求、skills、失败经验和 recall 组织成模型上下文。
- `server_py/agent/orchestrator.py` 在 Clarifier / Reviewer / Verifier / repair Reviewer 前重新生成 memory snapshot。
- `server_py/agent/tool_plan_drafter.py` 会把 memory 注入初始工具计划和修复计划 prompt。
- `GET /api/conversations/{conversationId}/memory` 返回当前 memory snapshot。
- `POST /api/memory/manual` 新增或更新当前仓库命名空间下的手动长期记忆，并写入 `memory.manual.upserted` 事件。
- `client/src/features/inspector/MemoryPanel.tsx` 展示右侧 Memory 面板。
- `client/src/features/chat/ConversationView.tsx` 展示任务账本摘要。

缺口：
- 当前召回已经不是轻量词项召回，但还不是 embedding / 向量语义召回。
- 当前还没有模型重排，模型只负责拆搜索意图。
- 成功/失败模式目前是规则聚类，不是模型自动归纳。
- Task Ledger 目前仍是可审查任务摘要；真正可编辑执行状态机已经由 `runtime/task-state-machine.json` 承担，但两者还需要进一步做更清晰的前端关联。
- Memory 面板已有筛选、搜索、手动新增 / 编辑、模型整理草案、来源阶段、最近一次 memory patch 摘要和 patch 历史折叠区；后续还缺更强 Curator 审核规则和结构化记忆文件 patch。
- 长期 memory 已有仓库级 namespace，但还缺团队级隔离。

## 12. Metrics 和可观测性

已有功能：
- `GET /api/metrics/{conversationId}` 查看 metrics。
- 记录模型调用 token、耗时、成本估算。
- 记录工具调用耗时、结果和风险等级。
- 右侧运行指标面板展示模型调用数、工具调用数、token、成本估算和失败工具数。

缺口：
- token 估算还可以更准确。
- 缺任务级性能报告。
- 缺工具失败原因聚合。

## 下一步优先级

1. 做可视化状态机编辑器：阶段负责人、证据、可执行动作、编辑意见和自动重写计划联动。
2. 提升修复计划 patch 质量：读取足够上下文后再写，失败后能给出更明确的修复依据。
3. 做外部 MCP 工具候选排序、推荐理由和按需求过滤。
4. 把 MCP 配置编辑从 JSON 编辑器升级为表单和 schema 校验。
5. 把审批弹窗补上更细的风险解释、拒绝后的计划改写建议和审批历史筛选。
6. 做回退后的可视化对比确认。
7. 增强 memory：补更强 Curator 审核规则和结构化记忆文件 patch。
8. 增强预览失败归因、截图查看器和交付报告高级 Markdown 能力。
