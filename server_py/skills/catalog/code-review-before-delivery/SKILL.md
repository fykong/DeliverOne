---
id: code-review-before-delivery
name: 交付前代码自查
kind: process
description: diff 产出之后、请求用户验收或创建 PR 之前的强制自查门禁——范围最小化、无调试残留与密钥、验证证据新鲜、回退路径完整;任何一项不过不得宣布完成。
riskLevel: low
requiresConfirmation: false
alwaysOn: true
triggers: [交付, 提交, 合并, 自查, 验收, 代码审查]
tools: [code.git_diff, code.read_file, code.search_files, verification.run]
verification:
  - "code.git_diff（自查对象必须是真实 diff 输出，不是记忆中的改动）"
  - "verification.run（全绿记录的时间必须晚于最后一次写入）"
acceptance:
  - "每个改动文件都能对应到需求点或已确认的计划步骤，对应不上的已回退"
  - "diff 无调试残留、无密钥、无与需求无关的格式化或重排"
  - "验证全绿且晚于最后一次写入；UI 改动附预览 smoke 证据"
  - "checkpoint 列表完整，交付说明写清单文件回退与全仓回退入口"
---

# 交付前代码自查 Skill

## 触发场景

执行链完成代码写入与验证、准备向用户宣布完成、请求验收或创建 PR 之前，强制执行一次本清单。

## 自查清单（逐项给出结论 + 证据）

1. 范围
   - 用 code.git_diff 列出全部改动文件，逐文件回答「对应哪条需求或计划步骤」。
   - 对应不上的改动（顺手格式化、IDE 自动修改、误入的锁文件或构建产物）按 checkpoint 直接回退，不解释、不保留。
2. 残留
   - 在本次新增行中搜索 console.log、debugger、print(、TODO、FIXME、被注释掉的代码块、写死的临时端口与本机路径。
   - 搜索 token、secret、password、apikey 等模式，确认没有任何凭据进入 diff。
3. 正确性快查
   - 新增分支的边界：空值、0、空数组、超长输入是否都有确定行为。
   - 错误路径：新增的 IO 或请求失败时是抛出、吞掉还是提示，必须与该仓库现有约定一致。
   - 命名与风格向被改文件的周边代码看齐，而不是向 Agent 的个人偏好看齐。
4. 证据新鲜度
   - 最后一次 verification.run 的时间必须晚于最后一次写入；改了就要重验，禁止复用旧绿灯。
   - UI 类改动必须有 browser.preview_smoke 的 DOM 或截图证据——「构建通过」不等于「页面正确」。
5. 可回退
   - 列出本次全部 checkpoint 及覆盖文件；交付说明中写明单文件回退与全仓回退的操作入口。

## 输出格式

自查报告按「检查项 → 通过/不通过 → 证据（diff 行、搜索结果、验证时间）」逐条输出，放在交付物之前。

## 硬限制

- 不允许凭记忆宣称「没改别的」，一切以 code.git_diff 的真实输出为准。
- 「这个测试本来就是红的」必须有改动前的基线记录佐证，否则一律按本次引入处理。
- 自查不通过的项，要么修复后重查，要么获得用户显式豁免并记入交付说明；禁止默默带病交付。
