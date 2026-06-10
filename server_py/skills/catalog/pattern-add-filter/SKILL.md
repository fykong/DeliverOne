---
id: pattern-add-filter
name: 需求模式·列表筛选与状态过滤
kind: requirement-pattern
description: 给列表增加筛选、过滤或状态维度（如草稿/已发布状态、按标签筛选、只看某作者），含列表默认过滤语义的跨栈贯通。
riskLevel: medium
requiresConfirmation: true
alwaysOn: false
triggers: [筛选, 过滤, 筛选器, 草稿, 状态, 只看, 按标签, filter, draft, 枚举]
tools: [code.search_files, code.read_file, code.apply_patch, command.run]
clarifyChecklist:
  - "筛选维度是什么：已有字段，还是要先新增字段（如 Article.status 枚举）？"
  - "筛选在前端内存里做，还是后端 query 参数做（数据量和分页语义不同）？"
  - "默认视图是什么：不筛选全量，还是默认排除某状态（如列表默认隐藏 draft）？"
  - "筛选入口的 UI 形态：下拉、Tab、开关？放在哪个页面？"
  - "和现有分页/Feed 切换（FeedToggler）怎么叠加？"
antiPatterns:
  - "『加个草稿功能』隐含了字段+筛选+入口三个子需求——必须拆解后逐个确认，不能压成一次改动。"
  - "默认过滤语义不清（列表到底还显不显示 draft）会直接改变现有用户看到的数据——必须显式确认。"
locateStrategy:
  backend:
    - "列表接口：backend/routes/articles.js 与 backend/controllers/articles.js（where 条件、分页参数在这里）"
    - "新增枚举字段时参考 pattern-add-field-fullstack 的迁移+模型改法"
  frontend:
    - "列表数据获取：frontend/src/hooks/useArticles.js、frontend/src/services/getArticles.js（query 参数从这里传）"
    - "Feed 切换参考实现：frontend/src/components/FeedToggler/"
    - "列表渲染：frontend/src/routes/HomeArticles.jsx、components/ArticlesPreview/"
changeChecklist:
  - "（如需新字段）迁移 + 模型 + 控制器接受/返回该字段"
  - "后端列表接口：where 条件支持筛选参数，并实现约定的默认过滤"
  - "frontend/src/services/getArticles.js：传递筛选 query 参数"
  - "筛选 UI：复用 FeedToggler/Tab 模式新增入口"
  - "确认分页计数与筛选条件一致（总数不能算上被过滤的数据）"
verification:
  - "npm test -- --run"
  - "npm run build -w frontend"
acceptance:
  - "筛选入口按约定出现并可切换；切换后列表内容正确变化"
  - "默认视图符合确认过的语义（如默认不显示草稿）"
  - "分页总数与筛选结果一致"
---

# 需求模式 Skill：列表筛选与状态过滤

## 适用场景

「文章草稿功能（draft/published + 列表默认过滤 + Drafts Tab）」「按标签筛选」「只看已关注作者」这类给列表加筛选维度的需求。

## 流程

1. 先拆需求：字段是否已存在 → 筛选在哪层做 → 默认语义 → UI 入口；用 clarifyChecklist 逐项确认。
2. 涉及新字段时先按全栈新增字段模式打底，再做筛选层。
3. 后端筛选改 controller 的 where 与分页；前端筛选改 hook/service 的参数传递。
4. 跑 verification；验收时分别验证「默认视图」和「筛选后视图」。

## 硬限制

- 改默认过滤语义前必须有用户的显式确认记录。
- 筛选必须和分页一起验证，禁止只看第一页就判定通过。
- 草稿类需求必须保证未发布内容不会泄漏到公开列表和公开详情页。
