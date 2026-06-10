# Codex 机制借鉴边界

这份文档记录我们如何借鉴 Codex，而不是把平台做成 Codex CLI 的外壳。

当前结论：
- 不安装、不依赖 `@openai/codex`。
- 不把 Codex CLI 当成运行时依赖。
- 后端 Agent Runtime 继续用 Python 实现。
- 可以研究和复用 Codex 开源仓库中与本项目直接相关的机制或小段代码，但必须先判断是否服务于端到端交付平台。
- 本轮已参考 `codex-rs/core/src/exec_policy.rs`、`shell.rs`、`apply_patch.rs`，把审批决策、命令安全分级、补丁路径审计和事件流机制改写进 Python 后端。

## 可以借鉴的部分

### 1. 审批和沙盒机制

对应本项目：

```text
server_py/runtime/permissions.py
config/agent-policy.json
server_py/runtime/approval_store.py
```

目标：
- 区分 read / write / command / external / dangerous。
- 写入必须有 checkpoint。
- 非可信命令必须经过用户授权。
- 命令决策显式分为 `allow / prompt / forbid`。
- 高风险命令不能通过普通 `command.run` 绕过。
- 每个 conversation 在独立沙盒里执行。

### 2. 工具事件流

对应本项目：

```text
server_py/tools/registry.py
server_py/runtime/events.py
```

目标：
- 每次工具调用都有 begin / end 事件。
- 中间对话展示真实模型输出、工具调用、审批和验证结果。
- 不展示无意义的静态步骤。

### 3. Checkpoint / Rollback

对应本项目：

```text
server_py/sandbox/checkpoint_manager.py
server_py/sandbox/rollback_service.py
server_py/tools/code_tools.py
```

目标：
- 写代码前创建 checkpoint。
- 支持按本次任务涉及文件回退。
- 支持确认后全仓回到沙盒原始 HEAD。

### 4. MCP 工具层

对应本项目：

```text
server_py/mcp/adapter.py
server_py/mcp/stdio_client.py
```

目标：
- 内置工具和外部 MCP 工具统一出现在工具层。
- 外部工具进入审批、事件流和 metrics。
- 后续接入 Browser / GitHub 插件时也走同一套工具计划。

### 5. Skills 约束

对应本项目：

```text
server_py/skills/catalog
server_py/skills/runtime.py
```

目标：
- 用 skill 约束 Agent 执行流程。
- 把仓库上下文、回退保护、预览验证、交付流程沉淀成可复用规则。
- 后续支持 references/scripts 按需读取。

## 暂不做的部分

- 不依赖 Codex CLI。
- 不复制 Codex 完整 UI。
- 不接入 Codex 账号、云端任务或同步体系。
- 不把 OpenAI 模型绑定进当前主链路，主模型仍按配置走 Doubao / Ark。

## 当前代码修改工具

`code.apply_patch` 不是 Codex CLI 的 patch 工具。

它是我们平台自己的受控多文件写入工具，输入是结构化 `changes`：

```json
{
  "reason": "修改原因",
  "changes": [
    {
      "relativePath": "src/example.ts",
      "action": "write",
      "content": "新的完整文件内容"
    }
  ]
}
```

执行流程：

```text
校验文件路径在沙盒内
→ 为本次涉及文件创建 checkpoint
→ 写入或删除文件
→ 读取 git diff
→ 返回 checkpoint、applied、diff、reason
```

这个设计更符合当前平台目标：稳定、可审计、可回退、便于前端展示。
