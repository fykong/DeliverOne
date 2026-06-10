# Memory 当前状态

更新时间：2026-06-10

## 已补齐

- 长期记忆增加仓库级 namespace。
- 当前仓库 snapshot 默认只召回当前仓库 namespace 和 workspace 级记忆。
- `workspace/memory/patterns.json` 新增成功/失败模式库。
- 失败模式会按 dependency、typecheck、lint、test、build、preview、MCP、permission、rollback 等类别沉淀修复建议。
- 成功模式会从 delivery / preview 证据中沉淀可复用交付和验证流程。
- Memory 面板新增长期记忆 pin / forget 按钮。
- Memory 快照新增 `patterns` 字段，并在 recall diagnostics 中记录 pattern 数量和路径。
- 新增 Memory Curator，维护 `repo-memory.json`、`repo-memory.md`、`repair-recipes.json`、`verification-recipes.json`、`user-preferences.json`。
- Curator 结果会进入召回候选，并在 Memory 面板展示“结构化记忆”。
- Curator 写入 append-only `memory-events.jsonl`，每条记忆都保留证据来源。
- 新增 Search Intent：先用 Doubao / Ark 生成搜索线索，失败时回退本地规则。
- Search Intent 会写入 `memory/conversation/search-intent.json`，并进入本地召回候选。
- 新增 Task Ledger：写入 `memory/conversation/task-ledger.json`，记录当前理解、阶段状态、关卡检查、阻塞点、检索线索、候选上下文、风险和下一步。
- 中间对话顶部已经展示任务阶段条，右侧 Memory 面板已经展示任务账本详情，用户能先判断 Agent 有没有误解需求、当前卡在哪一步。
- 长期记忆新增 `POST /api/memory/manual`，用户可以手动新增或编辑当前仓库 namespace 下的长期记忆。
- Memory snapshot 新增 `longTerm` 字段，返回当前仓库 namespace、长期记忆文件路径、数量和可见条目。
- Memory 面板支持搜索、类型筛选、新增、编辑、置顶和遗忘长期记忆。
- 手动长期记忆写入时会生成 `lastPatch`，记录 create / update、变更字段、before / after 和同名 / 高相似内容冲突提示。
- Memory 面板会展示最近一次 memory patch 摘要，用户能看到这条长期记忆最近为什么被改、改了哪些字段、是否有冲突。
- 新增模型生成长期记忆草案：`POST /api/memory/patch/draft` 先让默认模型根据 Memory snapshot 提出候选，失败时回退到规则。
- 新增长期记忆草案应用接口：`POST /api/memory/patch/apply` 只在用户确认后写入，写入仍复用 `upsert_manual` 的 namespace、conflict 和 lastPatch 审计。
- Memory 面板新增“模型整理”，会展示候选理由、写入影响和冲突提示，用户可逐条写入。
- 长期记忆 snapshot 已返回来源阶段和最近 12 条 patch 历史。
- Memory 面板已展示每条长期记忆的来源阶段，并提供完整 patch 历史折叠区。

## 当前边界

- 现在还不是真 embedding / 向量语义召回。
- 当前召回是本地强多信号排序：BM25、短语、路径、符号、标签、重要性、时间衰减、pin、长期记忆、多样性。
- 当前还没有模型重排；模型只负责生成检索意图，不负责候选排序。
- 模式聚类第一版是规则分类，不是模型自动归纳。
- Curator 目前仍是程序审计版；模型已经可以提出长期记忆草案，但还没有升级为 Curator 统一审核结构化文件 patch。
- Task Ledger 目前是可审查状态账本；真正可编辑执行状态机由 `runtime/task-state-machine.json` 承担，两者还需要更清晰的前端联动。
- Memory 面板还缺更强 Curator 审核规则和结构化记忆文件 patch。

## 可直接下一步做

- 模型重排可以复用现有 Doubao / Ark chat completion：先用本地召回拿候选，再让模型返回 JSON 排序。
- 真 embedding 需要新增 embedding API 或本地 embedding 模型。
- 模式聚类可以升级为“规则先分桶，模型再归纳策略标题、适用条件、禁用条件和修复步骤”。
- 模型维护记忆文件可以升级为“模型提出 memory patch，Curator 审计 evidence / namespace / conflict 后再写入”。
