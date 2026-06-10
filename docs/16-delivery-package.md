# Delivery Package

## 目的

本模块解决第六个框架缺口：Agent 完成沙盒修改后，需要生成可审查交付包，而不是只在聊天里说“完成了”。

借鉴 Codex 的机制：

- diff-first delivery：交付必须包含真实 diff 和 changed files。
- evidence bundle：把 tool plan、checkpoint、事件尾部一起打包。
- apply gate：应用回原仓库必须显式确认。
- source protection：第一版只支持本地原仓库；GitHub 源只生成交付包。

## 落地文件

```text
server_py/delivery/service.py
server_py/app.py
server_py/services.py
shared/src/index.ts
client/src/shared/api.ts
client/src/features/inspector/DeliveryPanel.tsx
client/src/features/inspector/MarkdownPreview.tsx
client/src/features/inspector/UnifiedDiffViewer.tsx
```

## API

```text
POST /api/delivery/package
POST /api/delivery/apply-to-source
GET /api/delivery/preview/{conversationId}
```

## 交付包内容

生成到：

```text
workspace/conversations/<conversationId>/delivery/
```

包含：

- `delivery-report.json`
- `delivery-report.md`
- `changes.patch`

报告包含：

- repository / sandbox
- toolPlan 摘要
- changedFiles
- git status
- diff stat
- checkpoints
- verificationGate / previewGate / rollbackGate
- eventTail
- artifacts 路径

右侧交付面板：

- 可以生成交付包。
- 可以确认后应用回本地原仓库。
- 可以展开查看 `delivery-report.md`。
- Markdown 报告会结构化渲染标题、段落、列表、表格、引用、代码块和链接。
- 可以展开查看 `changes.patch`，并复用统一 diff 查看器进行文件筛选、搜索、左右对比和统一视图切换。

## 应用回原仓库

`POST /api/delivery/apply-to-source` 需要：

```json
{
  "conversationId": "conv_xxx",
  "confirmed": true
}
```

限制：

- 只支持本地路径仓库。
- 只应用沙盒中有 diff 的文件。
- 应用前会把原文件备份到 conversation delivery 目录。
- GitHub 源第一版不会直接写回。

## 已验证

Smoke 流程：

```text
临时本地 git 仓库
-> 接入 conversation sandbox
-> 通过 MCP code.write_file 修改 README.md
-> 生成 delivery package
-> 显式确认应用回原仓库
```

结果：

```text
changedPath = README.md
changedFiles = 1
markdownExists = true
patchExists = true
appliedCount = 1
sourceUpdated = true
backupExists = true
```

## 当前不足

- `changes.patch` 主要覆盖 tracked diff，未跟踪文件会列入报告但 patch 还需要增强。
- Markdown 渲染是轻量实现，还缺完整 GFM 能力，例如任务列表和复杂嵌套表格。
- 还没有 GitHub PR / patch export 流程。
