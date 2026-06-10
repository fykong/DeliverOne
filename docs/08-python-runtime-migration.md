# Python Agent Runtime 迁移记录

## 为什么后端用 Python

前端继续使用 React + TypeScript，因为页面状态、对话流和右侧检查器适合 Web 技术栈。

后端使用 Python，因为核心是 Agent runtime：

- Agent 编排。
- Memory。
- MCP 风格工具层。
- 文件系统工具。
- 沙盒命令执行。
- 模型调用。
- 审计和交付报告。
- 后续 Playwright / 浏览器验证。

这些能力用 Python 写更直接，也更容易扩展。

## 已删除的旧结构

旧 TypeScript 后端已经移除，不保留两套后端，避免 API、memory、Agent 和工具层越做越乱。

## 当前 Python 后端能力

### 模型

- 读取 `config/model-providers.json`。
- 读取和保存 `config/model-settings.json`。
- API key 只从环境变量读取。
- 支持 Doubao / Ark。
- 支持 mock fallback。

### Memory

- 记录当前需求。
- 记录仓库画像。
- 记录匹配 Skill。
- 记录 Agent 输出。
- 记录用户确认和关键决策。
- 生成 context pack 给模型。

### Agent

- PlanningAgent：生成中文计划。
- ExecutorAgent：生成执行边界。
- ToolCallPlanService：生成、确认、执行工具调用计划。
- PlanAuditor：审计模型输出。

### 工具层

- `code.search_files`
- `code.read_file`
- `code.git_diff`
- `code.write_file`
- `code.apply_patch`
- `command.run`

### 沙盒和回退

- 公开 GitHub 仓库 clone 到当前对话沙盒。
- 本地路径复制到当前对话沙盒。
- 写入前 checkpoint。
- 按 checkpoint 回退。
- 确认后全仓回退到沙盒原始 HEAD。

### 预览

- `/api/preview/start` 可以在当前沙盒启动命令。
- 保存进程状态、stdoutTail、stderrTail 和端口。
- 仍缺端口等待、浏览器 smoke test 和截图证据。

## 运行方式

```bash
npm run dev
```

后端：

```text
http://127.0.0.1:4317
```

前端：

```text
http://127.0.0.1:5173
```
