# Codex 可借鉴的产品与架构思路

## 总结

最值得借鉴的不是页面样式，而是系统机制：

- 能力注册。
- 风险分级。
- 事件流。
- 沙盒。
- checkpoint。
- 显式 memory。
- 预检。
- 验证报告。
- 声明和证据绑定。
- 用户确认边界。

## 对本项目的映射

```text
Skill      -> 需求模式和流程约束
Agent      -> 执行角色
Orchestrator -> 决定阶段流转
Tool       -> 真正读写代码、跑命令、预览、回退的执行器
Memory     -> 仓库、需求、决策、失败经验
Event      -> 用户能审查的真实执行过程
```

## 第一版优先机制

1. PreflightService。
2. SkillRegistry。
3. ToolRegistry。
4. PermissionPolicy。
5. SandboxManager。
6. CheckpointManager。
7. ToolCallPlanService。
8. ProcessRegistry。
9. StackDetector。
10. MemoryService。

## UI 原则

- 中间只放用户和 Agent 的真实对话。
- 右侧放证据和操作。
- 模型设置独立成设置入口，不和主操作混堆。
- Skill 和 MCP 状态默认收起，不占主页面。
- 不展示无意义静态步骤。

## 后续增强

- Clarify Agent：拆解模糊需求。
- Reviewer Agent：检查 diff、验证结果和风险。
- VerificationService：执行 build/typecheck/lint/test。
- Browser smoke test：生成截图和页面证据。
- Dynamic MCP adapter：接外部 MCP Server。
