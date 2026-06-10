---
id: agent-delivery-flow
name: 端到端交付流程
kind: process
description: 把需求从澄清、计划、确认、修改、验证、预览推进到交付，并把每一步写入事件流。
riskLevel: medium
requiresConfirmation: true
alwaysOn: true
triggers: [需求, 开发, 修改, 实现, 交付, 全栈, agent]
tools: [code.search_files, code.read_file, code.write_file, code.apply_patch, command.run]
---

# 端到端交付流程 Skill

## 触发场景

用户要求实现、修改、整理、验证或交付一个仓库功能时使用本 Skill。

## 目标

把一个真实需求推进到可审查、可验证、可回退的交付状态。过程必须让用户看见 Agent 真正做了什么，而不是展示静态步骤。

## 流程

1. 记录需求  
   把用户原始需求写入 conversation memory，不改写成评委文案。
2. 仓库和沙盒检查  
   必须确认当前 conversation 已有沙盒仓库。没有沙盒时，不执行代码工具。
3. 计划生成  
   调用模型生成中文计划，必须包含需求确认、需要澄清、执行计划、风险与确认。
4. 计划审计  
   检查模型是否误称已经改代码，是否缺少风险，是否缺少仓库上下文。
5. 用户确认  
   默认计划模式下，用户确认后才能进入代码定位和修改。
6. 代码定位  
   通过 `code.search_files`、`code.read_file`、`code.git_diff` 获取真实代码证据。
7. 安全修改  
   任何写入必须通过 `code.write_file` 或 `code.apply_patch`。写入前必须创建 checkpoint。
8. 验证  
   根据仓库栈运行 lint、typecheck、test、build。非可信命令必须先请求确认。
9. 预览  
   只允许在当前对话沙盒内启动预览命令。
10. 交付  
   输出 diff、验证结果、预览状态、checkpoint 列表和回退方式。

## 硬限制

- 不直接修改原始仓库。
- 不在计划阶段声称已经完成代码修改。
- 不运行未授权高风险命令。
- 不跳过 checkpoint 写文件。
- 不展示无意义的“执行步骤”，只展示模型输出、工具调用、验证证据和交付物。
