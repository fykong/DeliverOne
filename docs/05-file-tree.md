# 文件树说明

项目根目录：

```text
C:/Users/kongfy/Desktop/AI-Delivery-Workbench-V2
```

## 顶层结构

```text
AI-Delivery-Workbench-V2/
  client/       React 前端
  config/       模型、策略、MCP、Skill 配置
  docs/         架构、流程、能力与缺口文档
  server_py/    Python Agent 后端
  shared/       前后端共享 TypeScript 类型
  workspace/    运行态数据：沙盒、memory、checkpoint、交付包
  package.json
```

`workspace/` 是运行态目录，不作为源代码整理目标。

## Python 后端结构

```text
server_py/
  app.py
  services.py

  agent/
    orchestrator.py
    planning_agent.py
    executor_agent.py
    role_agents.py
    tool_call_plan.py
    tool_plan_drafter.py
    workflow.py

  audit/
    plan_auditor.py

  conversations/
    store.py

  core/
    json_io.py
    paths.py

  delivery/
    service.py

  memory/
    context_pack.py
    curator.py
    long_term_store.py
    memory_service.py
    pattern_store.py
    preflight_service.py
    retrieval.py
    search_intent.py
    task_ledger.py

  mcp/
    adapter.py
    stdio_client.py

  models/
    ark_client.py
    model_config.py

  observability/
    metrics.py

  preview/
    process_registry.py
    smoke_test.py

  repository/
    profiler.py

  runtime/
    approval_store.py
    events.py
    permissions.py
    sandbox_runtime.py
    snapshot.py
    state_machine.py
    task_state_machine.py

  sandbox/
    checkpoint_manager.py
    diff_service.py
    file_browser.py
    manager.py
    rollback_service.py

  skills/
    registry.py
    runtime.py
    catalog/

  tools/
    browser_tools.py
    code_tools.py
    command_tools.py
    github_tools.py
    registry.py
    types.py
    unified_runtime.py
    verification_tools.py

  verification/
    runner.py
    stack_detector.py
```

## 前端结构

```text
client/src/
  app/
    App.tsx
    styles.css

  features/
    chat/
      ConversationView.tsx
    inspector/
    sidebar/
    topbar/
    workbench/

  shared/
    api.ts
```

## 整理原则

- Agent 后端统一使用 Python。
- 功能按领域放入 `agent`、`memory`、`mcp`、`sandbox`、`tools`、`preview`、`delivery` 等目录。
- 前端按页面区域和业务面板组织，右侧 inspector 只放交付、证据、memory、MCP、预览、回退等工作流面板。
- 不需要的实验代码直接删除，不保留占位文件。
- 新能力优先落到已有功能目录，避免继续散乱新增。
