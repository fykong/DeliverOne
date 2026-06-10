# 文档索引

当前项目目标：做一个用户可用的本地全栈交付 Agent App。用户接入本地仓库或公开 GitHub 仓库后，每个对话创建独立沙盒；Agent 在沙盒里规划、修改、验证、预览和交付，必要时支持逐步回退或全仓回退到沙盒原始 HEAD。

## 推荐阅读顺序

1. `01-requirements.md`：产品需求整理。
2. `04-architecture.md`：总体架构。
3. `05-file-tree.md`：当前文件树。
4. `06-codex-direct-reuse.md`：Codex 机制复用记录。
5. `09-codex-source-reuse-map.md`：官方 Codex 源码到本项目的映射。
6. `10-current-functions-and-gaps.md`：当前功能和缺口。
7. `11-runtime-state-machine.md`：后端运行时状态机。
8. `12-agent-orchestrator.md`：后端 Agent 编排器。
9. `13-structured-tool-plan.md`：模型结构化工具计划和审计。
10. `14-skill-runtime.md`：Skill 运行时选择和约束注入。
11. `15-mcp-adapter.md`：MCP 风格工具协议适配层。
12. `16-delivery-package.md`：交付包和应用回原仓库。
13. `17-preview-smoke-test.md`：沙盒预览端口、HTTP 和截图验证。
14. `18-memory-feedback.md`：失败、交付和预览证据反哺上下文。
15. `19-policy-observability.md`：审批矩阵、token、耗时和成本监控。
16. `21-engineering-challenges.md`：关键工程难点与解决方案（提交材料）。
17. `ai-usage.md`：AI 使用说明与过程留痕（提交材料）。
18. `task-plan.md`：当前任务计划。

项目总览、快速开始、架构图与合规声明见仓库根目录 `README.md`。

## 启动入口

后端：

```bash
npm run dev:server
```

前端：

```bash
npm run dev:client
```

一起启动：

```bash
npm run dev
```

访问：

```text
http://127.0.0.1:5173/
```
