# Preview Smoke Test

## 目的

本模块解决第七个框架缺口：沙盒预览不能只显示 iframe 或命令状态，还要能验证端口、HTTP 页面和截图证据。

借鉴 Codex 的机制：

- sandbox preview：预览命令只在当前 conversation sandbox 中运行。
- observable process：记录 stdout/stderr、端口和进程状态。
- browser evidence：保存页面响应、运行后 DOM、控制台事件、断言结果和截图。
- event stream：预览验证写入事件流。
- verifier evidence：预览报告会进入当前工具计划 evidence，供 Verifier 和交付包使用。

## 落地文件

```text
server_py/preview/process_registry.py
server_py/preview/smoke_test.py
server_py/agent/tool_call_plan.py
server_py/app.py
server_py/services.py
shared/src/index.ts
client/src/shared/api.ts
client/src/features/inspector/PreviewPanel.tsx
client/src/features/inspector/EvidencePanel.tsx
```

## API

```text
POST /api/preview/start
POST /api/preview/smoke-test
```

## Smoke Test 能力

`POST /api/preview/smoke-test` 会：

1. 等待指定端口打开。
2. 请求 `http://127.0.0.1:<port>/<path>`。
3. 保存 HTML 到 conversation preview 目录。
4. 优先用 CDP 读取运行后 DOM、控制台错误和 selector 匹配结果。
5. 尝试用本机 Edge/Chrome headless 截图。
6. 检查 `expectedTexts` 和 `requiredSelectors` 验收断言。
7. 写入 `smoke-report.json`。
8. 同步到当前工具计划 `toolPlan.evidence.previewResults`。
9. 写入事件：
   - `preview.smoke.begin`
   - `preview.smoke.end`
   - `tool_plan.evidence.synced`

## 已验证

Smoke 流程：

```text
临时静态 HTML 仓库
-> 接入 sandbox
-> 启动 python -m http.server
-> 等待端口
-> HTTP 200
-> 读取 title
-> 生成截图
-> 停止测试进程
```

结果：

```text
processStatus = running
ok = true
portOpen = true
httpStatus = 200
title = Preview Smoke
reportExists = true
screenshotOk = true
screenshotExists = true
```

## 当前不足

- 前端已有一键触发 smoke test、截图预览、运行后 DOM 摘要、控制台错误和断言失败展示。
- ProcessRegistry 已有 `/api/preview/stop`，可停止当前对话的沙盒预览进程树。
- 手动 smoke test 和工具计划中的 `browser.preview_smoke` 共用同一套 evidence 映射。
- Orchestrator 在 Verifier 前会自动同步最新 smoke report，避免预览证据停留在计划外。
- 截图依赖本机 Edge/Chrome headless；找不到浏览器时会跳过截图。
- 还缺点击/表单交互断言、截图像素异常判断，以及 iframe 不能嵌入时的代理/降级方案。
