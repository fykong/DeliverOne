# 本地 Codex 能力复用审计

## 扫描范围

已查看 `C:/Users/kongfy/.codex` 中与产品设计相关的非敏感内容：

- 系统内置 Skills。
- 本地 Skills。
- 插件缓存 Skills。
- Browser、GitHub、MCP、验证、前端测试相关说明。

没有读取或复用：

- `auth.json`。
- token、secret、cookie、API key。
- sqlite 会话数据库正文。
- 用户历史对话正文。
- `.sandbox-secrets`。

## 可复用结论

### Skill 结构

Codex 的 Skill 机制值得复用：

- 每个 Skill 独立目录。
- 核心文件为 `SKILL.md`。
- 描述用于触发，正文用于流程约束。
- 复杂资料放 `references/`。
- 确定性脚本放 `scripts/`。
- 不把大量无关文档塞进模型上下文。

当前项目已落地：

```text
config/agent-skills.json
server_py/skills/catalog/*/SKILL.md
server_py/skills/registry.py
```

### MCP 风格工具层

Codex 的工具抽象值得复用：

- 工具有 id、描述、输入、风险等级。
- Agent 不能绕过工具直接改文件。
- 所有工具调用写入事件流。
- 外部 MCP Server 后续也应进入同一 ToolRegistry。

当前项目已落地：

```text
server_py/tools/types.py
server_py/tools/registry.py
server_py/tools/code_tools.py
server_py/tools/command_tools.py
```

### 沙盒机制

Codex 的沙盒思想值得复用，但不直接依赖 `.codex` 私有 runner。

当前项目已落地：

```text
server_py/sandbox/manager.py
server_py/sandbox/checkpoint_manager.py
server_py/sandbox/rollback_service.py
workspace/conversations/<conversationId>/repo
```

### 浏览器和预览

Browser / webapp-testing 的思路值得复用：

- 启动服务。
- 等待端口。
- 检查页面。
- 截图。
- 收集控制台和错误。

当前项目只有进程管理，后续需要补浏览器 smoke test。

## 不复用内容

不直接复用 Codex 私有运行时、内部 command runner、插件内部 Node REPL、会话数据库、鉴权文件和用户历史。

这些只能作为设计参考，不能进入项目源码。
