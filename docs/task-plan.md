# 当前任务计划

## 当前目标

先把 Agent App 的框架做稳，再补交互细节。当前重点是：Codex 机制复用、MCP、审批、沙盒、回退、预览、交付包、memory、metrics、事件流和 Agent 编排。

## 已完成

- [x] 新项目目录：`C:/Users/kongfy/Desktop/AI-Delivery-Workbench-V2`
- [x] 后端统一为 Python FastAPI。
- [x] 前端为 React + TypeScript，代码按功能模块拆分。
- [x] 模型配置独立放在 `config/`，支持 Doubao / Ark 主模型并保存到磁盘。
- [x] 支持本地路径仓库接入。
- [x] 支持公开 GitHub 仓库拉取。
- [x] 每个 conversation 创建独立沙盒目录。
- [x] Memory 基础结构：需求、决策、Agent turn、仓库画像、失败经验、交付记录、预览验证。
- [x] ContextPack 会把 memory、仓库、skills 和失败经验注入模型。
- [x] Skill Runtime：选择 skill、提取 constraints、发现 references/scripts。
- [x] 内置中文 Skills：交付流程、仓库上下文、回退保护、沙盒预览。
- [x] PlanningAgent、ToolPlanDrafter、ExecutorAgent 基础链路。
- [x] PlanAuditor 审查计划和工具计划。
- [x] ToolRegistry 统一注册 code、command、verification 工具。
- [x] PermissionPolicy：read/write/command/external/dangerous 风险矩阵。
- [x] Conversation-scoped approval grant：支持 `once`、`turn`、`session`。
- [x] 写文件前自动 checkpoint。
- [x] 支持按 checkpoint 回退本次任务涉及文件。
- [x] 支持确认后全仓回到沙盒原始 HEAD。
- [x] DeliveryService 生成 `delivery-report.json`、`delivery-report.md`、`changes.patch`。
- [x] 支持确认后把沙盒改动应用回本地原始仓库。
- [x] ProcessRegistry 在沙盒启动和停止预览命令。
- [x] PreviewSmokeTester 保存 HTML、smoke report 和截图证据。
- [x] VerificationRunner 执行验证命令并生成验证报告。
- [x] Metrics 记录模型调用、工具调用、耗时、token 和成本估算。
- [x] MCP Adapter 暴露内部工具为 MCP 风格 manifest。
- [x] MCP stdio `tools/list` 发现。
- [x] MCP stdio `tools/call` 调用。
- [x] MCP HTTP `tools/list` 发现和 `tools/call` 调用。
- [x] MCP SSE/WS 配置校验和状态展示已接入，长连接执行明确标记为待实现。
- [x] 外部 MCP 调用进入审批、事件流和 metrics。
- [x] 前端 MCP 基础面板：发现工具、授权和撤销授权。
- [x] 前端审批请求基础面板。
- [x] 前端运行指标基础面板。
- [x] 前端交付包基础面板。
- [x] 前端预览 smoke test 入口。
- [x] `code.apply_patch` 作为平台自有结构化多文件写入工具。
- [x] `code.apply_patch` 写入前创建 checkpoint，越界路径在执行前被拒绝。
- [x] 后端 DiffService：当前沙盒 diff、单文件 diff、checkpoint diff。
- [x] 前端右侧“文件与变更”面板：文件树、变更列表、diff 详情、checkpoint diff 和回退入口。
- [x] Diff 查看器支持左右 split diff、统一 diff 和行内高亮。
- [x] 工具计划步骤绑定 diff、checkpoint 和回退入口。
- [x] 支持 checkpoint 单文件回退：`POST /api/rollback/checkpoint-file`。
- [x] 支持 checkpoint hunk 级回退：`POST /api/rollback/checkpoint-hunk`。
- [x] Diff 查看器支持回退前后列标题和未变更上下文折叠。
- [x] Browser / GitHub 风格工具进入 ToolRegistry：`browser.preview_smoke`、`github.inspect_repository`。
- [x] GitHub 仓库默认工具计划会加入 `github.inspect_repository`。
- [x] MCP 面板支持工具 schema 展示和按工具过滤调用历史。
- [x] Clarifier / Reviewer / Verifier 角色骨架接入 orchestrator，并写入事件/audits。
- [x] 失败或等待审批的工具计划可以生成修复诊断计划。
- [x] MCP 配置支持 API 读取/保存，前端支持 JSON 编辑。
- [x] MCP 调用历史支持点开查看完整 payload 抽屉。
- [x] MCP / tool 调用事件携带 `planId` 和 `stepId`，可以追踪到具体工具计划步骤。
- [x] MCP 调用历史支持从已保存输入重放单条调用，并重新写入事件和 metrics。
- [x] 审批支持拒绝原因、绑定原始请求事件、审查弹窗和审批历史。
- [x] Hunk 回退前增加二次确认 diff 预览。
- [x] 新增统一工具运行时：Agent 工具计划可同时编排内置工具和已发现的外部 MCP 工具。
- [x] `/api/tools` 返回 Agent 当前可用的完整工具目录。
- [x] 外部 MCP 工具进入工具计划和执行链路的 smoke test 通过。
- [x] mock stdio MCP server 端到端验证通过。
- [x] 结构化 `code.apply_patch` 工具调用 smoke test 通过。
- [x] diff / checkpoint / 单文件回退后端 smoke test 通过。
- [x] hunk 回退 + Browser/GitHub 工具 smoke test 通过。
- [x] 框架细节 smoke test：审批拒绝、MCP 配置保存、失败计划生成修复诊断计划通过。
- [x] 预览验收断言进入 Agent 工具计划：本地生成 `expectedTexts` / `requiredSelectors`，并兜底注入 `browser.preview_smoke`。
- [x] 修复计划会保留上一轮预览断言并复跑页面验收，避免修复后只复跑命令、不复查页面。
- [x] 工具计划编辑从 prompt 升级为可审查编辑弹窗，支持标题、目的、参数和修改原因。
- [x] 工具计划编辑会进入任务状态机 `tool-plan` 阶段记录，保留人工干预和 Reviewer 重审结论。
- [x] 支持用户用自然语言要求模型重写完整工具计划，重写后仍需 Reviewer 重审和用户确认。

## 下一批框架问题

1. Tool plan 循环执行：根据失败结果继续生成 patch、验证和修复。
2. MCP 管理增强：外部工具候选排序、推荐理由、配置表单化、schema 校验、SSE/WS 长连接、按 plan/step 的聚合视图。
3. 审批弹窗增强：风险说明、拒绝后的计划改写建议、历史筛选。
4. Checkpoint / Diff 增强：回退后的对比确认和交付报告证据。
5. Agent 编排增强：把 Clarifier、Reviewer、Verifier 从规则骨架升级为模型驱动角色。
6. Browser / GitHub 增强：预览启动工具、GitHub PR 创建。
7. 事件流驱动中间对话：展示真实模型输出、工具调用、审批和验证证据。
8. 实时预览增强：点击/表单交互断言、截图像素异常判断、iframe 代理降级。
9. 交付体验增强：markdown 报告预览、diff 查看器、GitHub PR。
10. Memory 面板：需求记忆、决策、失败经验、交付历史和当前上下文包。

## 当前最大风险

- 前端已有基础面板，但很多仍是“能用”而不是“顺手”。
- Agent 已有修复诊断计划入口，已能保留预览断言并复跑页面验收；仍缺更强的自动 patch 质量评估和失败原因聚类。
- 多角色目前是规则骨架，未升级到模型驱动。
- 外部 MCP 目前支持 stdio stateless 和 HTTP stateless；SSE/WS 长连接还没做，stdio 也还没有连接池。
- 外部 MCP 工具已进入 Agent 工具目录，但候选排序和推荐理由还比较粗。
- Skills references/scripts 只发现文件，还没有按需读取。
- Browser/GitHub 已进入工具注册和候选工具，仍缺 PR 创建和预览启动工具。

## 最终验收门槛

- 不能只用 mock、单元测试或静态构建证明项目可用。
- 框架主干完成后，必须用真实豆包模型和真实仓库沙盒跑一个端到端任务。
- 默认验收仓库：`https://github.com/TonyMckes/conduit-realworld-example-app`。
- 真实任务必须覆盖：需求理解、澄清或计划、工具计划、用户确认、沙盒修改、checkpoint、diff、验证命令、预览 smoke、交付报告和回退能力。
- 验收证据必须包含：模型返回、工具计划、执行事件、变更 diff、验证输出、预览截图/DOM/控制台、交付包和失败/修复记录。
