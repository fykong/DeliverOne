# Policy And Observability

## 目的

本模块解决第九个框架缺口：用户和系统必须知道哪些动作需要审批，以及一次任务消耗了多少 token、耗时和成本估算。

借鉴 Codex 的机制：

- approval matrix：按风险等级决定允许、审批或阻断。
- event + metrics：事件解释发生了什么，metrics 解释花了多少。
- model/tool separation：模型调用和工具调用分别记录。
- configurable pricing：价格放配置，不在代码里硬编码。

## 落地文件

```text
config/model-pricing.json
server_py/observability/metrics.py
server_py/runtime/permissions.py
server_py/models/ark_client.py
server_py/tools/registry.py
server_py/app.py
server_py/services.py
shared/src/index.ts
client/src/shared/api.ts
```

## API

```text
GET /api/policy/matrix
GET /api/metrics/{conversationId}
```

## 审批矩阵

当前风险等级：

- `read`：默认允许，沙盒内只读。
- `write`：必须 checkpoint，默认允许写入沙盒。
- `command`：可信只读命令允许，非可信命令需要审批。
- `external`：需要审批。
- `dangerous`：必须专门审批，不能通过普通命令绕过。

## Metrics

模型调用记录：

- provider
- modelId / modelName
- latencyMs
- promptTokens
- completionTokens
- totalTokens
- estimatedCost

工具调用记录：

- toolId
- durationMs
- ok
- riskLevel

成本估算读取：

```text
config/model-pricing.json
```

默认价格为 0，不乱填价格；配置价格后会自动估算。

## 已验证

Smoke 结果：

```text
matrixRows = 5
hasDangerous = true
modelCallCount = 1
totalTokens = 1904
toolCallCount = 1
failedToolCalls = 0
```

## 当前不足

- 前端还没有 metrics 面板。
- token 成本依赖模型返回 usage；没有 usage 时使用字符数粗估。
- 还没有按任务总链路生成完整性能报告。
