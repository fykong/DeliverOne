# 弱点记录与优先路线

## 当前真实短板

### 1. 前端还没有完整展示工具计划证据

后端已有 tool-call plan、事件、checkpoint、diff、命令结果，但前端右侧还没有完整接入。

优先动作：

- 右侧增加工具计划面板。
- 展示每步工具、风险、输入摘要、状态、checkpoint、diff、命令结果。
- 提供确认和执行按钮。

### 2. 中间对话还没有完全基于事件流

当前中间区域主要展示手动追加的消息，还没有直接消费 `/api/events/{conversationId}`。

优先动作：

- 轮询或订阅事件流。
- 中间只展示用户消息、Agent 消息和关键错误解释。
- 工具细节放右侧。

### 3. 验证服务还没有真正执行

`StackDetector` 能选命令，但还没有 `verification.run`。

优先动作：

- 新增 VerificationService。
- 执行 build/typecheck/lint/test。
- 保存结构化验证报告。

### 4. 预览还缺浏览器验证

目前只能启动预览命令，还不能等待端口、截图、检查页面。

优先动作：

- 增加端口等待。
- 增加 Browser smoke test。
- 保存截图和检查结果。

### 5. MCP 仍是内置风格工具层

第一版这样更稳定，但后续必须接外部 MCP Server。

优先动作：

- 增加 MCP server 配置结构。
- 支持 stdio / http 至少一种。
- 外部工具也进入 ToolRegistry 和 PermissionPolicy。

### 6. Memory 还不够聪明

现在能记录需求、决策、Agent turn、仓库画像和 Skill 命中，但还没有失败经验、相似任务召回和业务术语沉淀。

优先动作：

- 记录失败原因。
- 记录成功模式。
- 新任务 preflight 时按仓库和 Skill 召回相关经验。

### 7. UI 仍然是骨架

页面已经比之前简洁，但还没到真正成熟 App。

优先动作：

- 左侧历史对话接真实 conversation。
- 右侧按标签区分计划、文件、验证、预览、回退、设置。
- 去掉所有静态假数据。

## 优先级

1. 前端接 tool-call plan 和事件证据。
2. VerificationService。
3. Browser smoke test。
4. 真实 conversation 列表和删除。
5. MCP server adapter。
6. Reviewer Agent。
7. Memory 召回增强。
