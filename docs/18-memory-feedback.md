# Memory Feedback

## 目标

Memory 不是把所有历史消息硬塞进上下文，而是让 Agent 在下一轮任务里能稳定拿到：

- 当前仓库画像：来源、分支、脚本、模块地图、项目指令。
- 当前对话记忆：需求、用户决策、Agent 输出、失败原因。
- 长期记忆：跨对话但限定在当前仓库 namespace 内的关键经验。
- 可复用策略：从成功/失败证据自动沉淀出的修复模式。

这套机制借鉴 Codex 的项目指令、thread memory、上下文压缩和失败证据沉淀，但不复刻 Codex CLI。

## 文件落点

```text
server_py/memory/memory_service.py       # memory 主流程
server_py/memory/retrieval.py            # 本地多信号召回
server_py/memory/long_term_store.py      # 长期记忆与仓库级 namespace
server_py/memory/pattern_store.py        # 成功/失败模式聚类
server_py/memory/context_pack.py         # 注入模型的上下文包
server_py/memory/search_intent.py        # 模型或规则生成检索意图
server_py/memory/task_ledger.py          # 当前任务账本
client/src/features/inspector/MemoryPanel.tsx
client/src/features/chat/ConversationView.tsx
```

运行态数据：

```text
workspace/conversations/<conversationId>/memory/
  repo/
  conversation/
    search-intent.json
    task-ledger.json
  delivery/
  skill/

workspace/memory/
  long-term-memory.json
  patterns.json
  global/
    user-preferences.json
  repos/
    <repoNamespace>/
      repo-memory.json
      repo-memory.md
      repair-recipes.json
      verification-recipes.json
  events/
    memory-events.jsonl
```

## 当前能力

- 每个对话有独立 memory 目录。
- 接入仓库后生成 repo profile、package scripts、模块地图、项目指令。
- 自动读取沙盒仓库里的 `AGENTS.md` / `AGENTS.override.md`。
- 记录需求、用户决策、Agent 输出、失败经验、交付记录、预览验证和命中的 Skills。
- 生成结构化 memory entries，并写入 `memory-entries.json`。
- 使用本地强多信号召回：
  - BM25
  - 短语命中
  - 路径命中
  - 代码符号拆分
  - 标签
  - 重要性
  - 时间衰减
  - pin
  - 长期记忆
  - 多样性选择
- 重要条目会沉淀到 `workspace/memory/long-term-memory.json`。
- 长期记忆已经支持仓库级 namespace，默认只召回当前仓库和 workspace 级记忆，避免不同项目互相污染。
- 后端提供 `POST /api/memory/pin` 和 `POST /api/memory/forget`。
- 前端 Memory 面板已经支持对长期记忆置顶和遗忘。
- 成功/失败证据会自动聚类到 `workspace/memory/patterns.json`。
- 模式库会沉淀依赖、typecheck、lint、test、build、preview、MCP、权限、回退等常见修复策略。
- Memory Curator 会维护结构化记忆文件：
  - `repo-memory.json`：机器读取的仓库记忆。
  - `repo-memory.md`：人可读的仓库记忆。
  - `repair-recipes.json`：可复用修复策略。
  - `verification-recipes.json`：可复用验证策略。
  - `user-preferences.json`：workspace 级用户偏好。
  - `memory-events.jsonl`：append-only 审计日志。
- Curator 写入的每条记忆都有 evidence id、source path、confidence、namespace 和 section。
- 当前 Curator 是审计版程序逻辑；后续模型可以输出 memory update patch，由 Curator 审计后写入同一套文件。
- ContextPack 会把召回结果组织成 `memory-recall` section，供 Planning / ToolPlan / Clarifier / Reviewer / Verifier / repair loop 使用。
- Search Intent 会先用 Doubao / Ark 把需求拆成 `searchQueries`、`fileHints`、`memoryQueries`、`riskHints`、`verificationHints`。
- 如果模型不可用或 JSON 解析失败，Search Intent 会回退到本地规则，不阻断主链路。
- 本地召回会把 Search Intent 拼入 recall query，并额外把 `search-intent.json` 作为高权重候选条目。
- Task Ledger 会把当前理解、检索线索、候选上下文、命中 Skill、风险和下一步写入 `task-ledger.json`。
- 中间对话顶部会显示任务账本摘要，方便用户判断 Agent 是否理解错需求。
- 用户可以通过 `POST /api/memory/manual` 或右侧 Memory 面板手动新增 / 编辑长期记忆。
- Memory 面板已支持搜索、类型筛选、置顶和遗忘。
- 手动长期记忆会保留最近一次 `lastPatch` 审计摘要，包含变更字段、before / after 和冲突提示；Memory 面板会展示这份摘要。
- 模型可以通过 `POST /api/memory/patch/draft` 生成长期记忆草案；草案不会自动写入。
- 用户在 Memory 面板审查模型草案、写入影响和冲突提示后，可以逐条通过 `POST /api/memory/patch/apply` 写入长期记忆。
- 长期记忆 snapshot 会返回来源阶段、来源对话、来源 entry 和最近 12 条 patch 历史。
- Memory 面板会展示来源阶段和完整 patch 历史折叠区。

## 还没做

- 现在还不是真 embedding / 向量语义召回。
- 现在还没有 embedding 和模型重排：目前是模型拆意图，本地多信号排序直接进上下文。
- 现在的模式聚类是规则分类，不是模型自动归纳。
- Curator 目前是确定性沉淀；模型草案已经可用，但还没有统一升级为 Curator 对结构化记忆文件的完整 patch 审核。
- 还没有把模型草案统一升级为 Curator 对结构化记忆文件的完整 patch 审核。

## Embedding 与模型重排方案

第一阶段不强依赖新 API：

1. 先用当前本地 BM25 多信号召回取 20 到 40 条候选。
2. 复用现有 Doubao / Ark chat completion 做 JSON rerank。
3. 让模型只返回最该进上下文的条目 id、理由和排序。
4. JSON 解析失败时回退本地排序。

真 embedding 需要新增能力：

- 接 embedding API；或
- 本地加载 embedding 模型；或
- 用轻量本地句向量库。

没有 embedding API 时也能先做“模型 rerank”，因为它只需要现有对话模型，不需要额外接口。

## 验证重点

- A 仓库写入的长期失败经验，不会在 B 仓库 snapshot 中召回。
- pin 后长期记忆优先进入候选。
- forget 后该条长期记忆不再进入召回。
- 失败证据能生成可复用修复策略。
- `python -m compileall server_py`、`npm run typecheck`、`npm run build` 通过。
