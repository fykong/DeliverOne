# AI 使用说明(过程留痕)

按课题 §7.2 要求,记录本项目的 AI 工具使用方式、Prompt 策略与关键迭代。

## 模型清单与用途

| 模型 | 用途 | 来源 |
|---|---|---|
| doubao-seed-2.0-lite | 平台运行时全部 Agent 角色(Planning / Clarifier / Reviewer / Verifier / ToolPlanDrafter / SearchIntent / Memory Curator) | 比赛统一下发 EP + API Key |
| Claude(Claude Code CLI) | 开发期辅助:代码库多智能体审查、框架重构、测试编写、文档整理 | 自付费,仅用于开发期,不参与平台运行时 |

## 运行时 Prompt 策略

- **角色分离**:Clarifier / Reviewer / Verifier 三个角色独立调用模型,各自有系统提示与硬规则(`server_py/agent/role_agents.py`),输出强约束为 JSON;解析失败回退确定性规则,模型结论与规则兜底取"最严判定"合并。
- **澄清深度**:Clarifier 按六个歧义维度逐项检查(功能目标/位置载体/数据来源/边界范围/验收标准/状态权限),并注入命中需求模式 Skill 的 `clarifyChecklist` 与 `antiPatterns`;输出结构化需求 DSL + 歧义清单(含 blocking 标记)+ 反模式发现。存在 blocking 歧义时直接在对话中追问,不进入方案生成。
- **Skill 即上下文工程**:Skill 的 frontmatter(定位锚点/改动清单/验证命令/验收断言)与正文硬限制都会注入模型上下文;新增需求模式只需新增一个 SKILL.md,运行时热加载。
- **上下文包**:每轮调用注入仓库画像、记忆快照(需求/决策/失败经验)、任务账本与搜索意图,避免模型脱离真实仓库猜测。

## 过程留痕位置

- **Agent 调用日志**:每会话 `workspace/conversations/<id>/events.jsonl`(事件溯源)与 `metrics.jsonl`(每次调用 tokens/延迟/成本)。
- **模型原始输出**:角色审计记录携带 `rawResponse`,工具计划记录 `generation.rawResponse`。
- **Prompt 版本迭代**:prompt 演进随 git 提交历史可追溯(见 `git log -- server_py/agent/`)。
- **开发期 AI 辅助记录**:git 提交历史(2026-06-10 的重构系列提交)记录了多智能体审查发现的 20 个确认问题与对应修复,提交信息中逐条列出。

## 人工审阅声明

所有 AI 生成代码在合入前均经人工理解、校验与改造;运行时生成的业务代码必须经过工具计划确认、Reviewer 审查、验证命令与预览 smoke 后才能进入交付物,禁止未审阅直接提交。
