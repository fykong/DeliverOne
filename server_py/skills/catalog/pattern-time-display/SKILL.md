---
id: pattern-time-display
name: 需求模式·时间与相对时间展示
kind: requirement-pattern
description: 在页面上展示时间类信息（创建/最后编辑时间、相对时间"X 小时前"），含时间计算纯函数、边界处理与后端时间戳语义确认。
riskLevel: low
requiresConfirmation: true
alwaysOn: false
triggers: [时间, 编辑时间, 最后编辑, 相对时间, 小时前, 分钟前, updatedAt, 多久前, 发布时间]
tools: [code.search_files, code.read_file, code.apply_patch, command.run]
clarifyChecklist:
  - "展示哪个时间字段（updatedAt 最后编辑 / createdAt 创建）？展示在哪个页面哪个位置？"
  - "展示形态：绝对时间、相对时间（X 小时前），还是两者结合？相对时间的粒度梯度（分钟/小时/天）怎么定？"
  - "从未编辑过（updatedAt 等于 createdAt）时显示什么：隐藏、显示创建时间，还是显示'未编辑'？"
  - "时间基准用浏览器本地时间即可，还是有时区要求？"
  - "需不需要后端保证更新操作会刷新该时间戳？"
antiPatterns:
  - "需求说'显示最后编辑时间'但实体可能从未被编辑——必须确认相等/空值时的展示行为，不能默认显示创建时间。"
locateStrategy:
  frontend:
    - "文章元信息（作者/日期区）：frontend/src/components/ArticleMeta/（现有日期展示就在这里）"
    - "现有时间格式化参照：frontend/src/helpers/dateFormatter.js 与 dateFormatter.test.js（新时间函数照此风格放 helpers 并写单测）"
    - "文章详情页：frontend/src/routes/Article/Article.jsx"
  backend:
    - "Sequelize 模型默认带 timestamps（createdAt/updatedAt），update 自动刷新 updatedAt；确认序列化未隐藏该字段：backend/models/Article.js 的 toJSON"
    - "更新接口：backend/controllers/articles.js 的 update 路径"
changeChecklist:
  - "frontend/src/helpers/ 新增相对时间纯函数（输入 ISO 时间，输出'X 分钟前/X 小时前/X 天前'），含未来时间、无效输入、刚刚（<1 分钟）边界"
  - "为该纯函数写 vitest 单测（参照 dateFormatter.test.js），覆盖分钟/小时/天梯度与边界"
  - "目标组件集成展示，updatedAt 与 createdAt 相等或缺失时按约定降级，不破版"
  - "如需求要求：确认后端 update 接口响应包含刷新后的 updatedAt"
verification:
  - "npm test -- --run"
  - "npm run build -w frontend"
acceptance:
  - "目标页面在约定位置出现'最后编辑于 X 前'类文案"
  - "未编辑过的文章按约定行为展示（不显示错误时间）"
  - "相对时间纯函数单测覆盖典型与边界输入并全部通过"
---

# 需求模式 Skill：时间与相对时间展示

## 适用场景

「文章详情页展示最后编辑时间（X 小时前）」「评论显示发布于多久前」这类把时间戳转成用户可读时间并展示的需求。

## 流程

1. 用 clarifyChecklist 确认字段、位置、相对时间梯度与"从未编辑"的行为。
2. 读取 ArticleMeta 与 dateFormatter 现有实现，沿用其格式化与测试风格。
3. 相对时间计算抽成 helpers 纯函数 + 单测；组件只做渲染与降级。
4. 跑 verification；建议预览断言检查页面出现"编辑于"类文案。

## 硬限制

- 时间计算必须是纯函数（接收时间参数，不在函数内部取 Date.now 以便测试注入；可接受第二参数 now）。
- 不引入 moment/dayjs 等新依赖，原生 Date 实现。
- updatedAt 与 createdAt 相等或字段缺失时禁止显示"编辑于 1970 年"之类的错误降级。
