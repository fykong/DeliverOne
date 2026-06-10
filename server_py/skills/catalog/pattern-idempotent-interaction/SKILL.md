---
id: pattern-idempotent-interaction
name: 需求模式·幂等计数交互
kind: requirement-pattern
description: 点赞/收藏类带计数的用户交互，核心是幂等性设计（重复请求不重复计数）与前端乐观更新，参考仓库内 Favorites 的既有实现。
riskLevel: medium
requiresConfirmation: true
alwaysOn: false
triggers: [点赞, 喜欢, 收藏, 计数, 幂等, like, likeCount, upvote]
tools: [code.search_files, code.read_file, code.apply_patch, command.run]
clarifyChecklist:
  - "交互挂在哪个实体上（Comment 点赞 / Article 收藏类比）？"
  - "幂等语义：重复点是无效，还是取消（toggle）？"
  - "计数怎么存：关联表实时 COUNT，还是实体上冗余 likeCount 列？两者一致性策略是什么？"
  - "未登录用户点击的行为（跳登录 / 禁用按钮）？"
  - "计数展示在哪些位置？"
antiPatterns:
  - "只在实体上加 likeCount 整数列、点一次加一——没有用户-实体关联就无法幂等，必须指出并按关联表设计。"
  - "需求说『支持点赞』但没说能否取消——toggle 与单向语义的接口设计完全不同，必须追问。"
locateStrategy:
  backend:
    - "幂等交互的现成参照：backend/controllers/favorites.js（Article 收藏的 through 表写法）"
    - "关联定义参照：backend/models/Article.js 中 belongsToMany(User, { through: \"Favorites\" })"
    - "新关联表需要迁移：backend/migrations/（参考 create-comment 的外键写法）"
    - "路由注册：backend/routes/ 下对应实体文件"
  frontend:
    - "按钮交互参照：frontend/src/components/FavButton/（收藏按钮的乐观更新写法）"
    - "评论区：frontend/src/routes/Article/CommentsSection.jsx、components/CommentList/、CommentEditor/"
    - "请求封装：frontend/src/services/ 新增对应动作文件"
changeChecklist:
  - "迁移：新增用户-实体关联表（联合唯一约束保证幂等）"
  - "模型：belongsToMany 关联（参考 Favorites through 表写法）"
  - "控制器：POST 幂等写入（先查后插或 findOrCreate），DELETE 取消；响应带最新计数和当前用户状态"
  - "路由：注册新端点，挂认证中间件"
  - "前端 service + 按钮组件：参考 FavButton 模式做乐观更新与失败回滚"
  - "计数展示组件更新"
verification:
  - "npm test -- --run"
  - "npm run build -w frontend"
acceptance:
  - "同一用户重复触发不会重复计数（幂等约束生效）"
  - "登录用户能看到自己的点赞状态；未登录行为符合约定"
  - "前端计数在操作后立即更新，失败时回滚"
---

# 需求模式 Skill：幂等计数交互

## 适用场景

「评论支持点赞（含幂等）」「文章加收藏数」这类带计数、且必须防重复的用户交互需求。

## 流程

1. 用 clarifyChecklist 确认幂等语义（toggle 还是单向）、存储策略和未登录行为。
2. 先读 favorites 的完整链路（model → controller → route → FavButton），这是本仓库幂等交互的标准答案，新交互照此模式实现。
3. 数据层先行（迁移+模型），再控制器/路由，最后前端按钮与计数。
4. 验证必须覆盖「重复请求」场景：连续两次同样请求，计数只变一次。

## 硬限制

- 幂等必须由数据库约束（联合唯一/主键）兜底，不能只靠前端禁用按钮。
- 写接口必须挂认证中间件，禁止匿名计数。
- 计数响应必须来自数据库真实状态，不允许前端自增后不校准。
