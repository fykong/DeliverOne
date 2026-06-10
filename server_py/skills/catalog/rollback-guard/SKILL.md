---
id: rollback-guard
name: 回退保护
kind: process
description: 写文件前创建检查点，并支持任务文件回退或沙盒全仓回退。
riskLevel: high
requiresConfirmation: true
alwaysOn: false
triggers: [rollback, 回退, 还原, 撤销, 恢复, reset]
tools: [code.git_diff, code.write_file, rollback.checkpoint, rollback.original]
---

# 回退保护 Skill

## 触发场景

用户要求撤销、还原、回退，或 Agent 准备写文件时使用。

## 流程

1. 写入前为本次涉及文件创建 checkpoint。
2. 写入后记录 diff 和 checkpoint id。
3. 用户可选择按 checkpoint 回退本次涉及文件。
4. 用户也可显式确认后，将沙盒全仓回到原始 HEAD。

## 限制

- 没有 checkpoint 不允许写入。
- 全仓硬重置必须显式确认。
- 普通命令工具不能绕过回退接口直接执行危险重置。
