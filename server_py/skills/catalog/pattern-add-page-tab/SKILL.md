---
id: pattern-add-page-tab
name: 需求模式·新增页面或 Tab
kind: requirement-pattern
description: 在已有页面体系中新增一个页面、路由或 Tab（如 Profile 页的 About Me Tab、Drafts Tab），复用现有导航与布局骨架。
riskLevel: medium
requiresConfirmation: true
alwaysOn: false
triggers: [新增页面, 加页面, tab, 标签页, 新增入口, 页签, about, 草稿箱]
tools: [code.search_files, code.read_file, code.apply_patch, command.run]
clarifyChecklist:
  - "新页面/Tab 挂在哪个现有页面或路由下？"
  - "入口放在哪里（Tab 栏、导航栏、侧边栏）、文案是什么？"
  - "内容数据从哪来：已有接口字段（如 User.bio）、新接口，还是静态内容？"
  - "未登录用户/无数据时显示什么？"
  - "是否需要独立 URL（可直接访问、可刷新），还是纯前端切换状态？"
antiPatterns:
  - "『加个 Tab』但内容数据不存在——若需要新数据，先拆出全栈新增字段/接口子需求。"
  - "需求要求展示的字段（如 bio）可能为空——必须定义空态，不能默认显示空白。"
locateStrategy:
  frontend:
    - "Profile 页与现有 Tab 实现：frontend/src/routes/Profile/Profile.jsx、ProfileArticles.jsx、ProfileFavArticles.jsx（My Articles / Favorited Articles 的切换写法就在这里）"
    - "路由注册：frontend/src/App.jsx 中 react-router-dom 的 Routes 定义"
    - "导航组件：frontend/src/components/Navbar/、NavItem/"
    - "用户数据：frontend/src/context/AuthContext.jsx 与 profiles 相关 service"
  backend:
    - "如内容来自已有字段：backend/routes/profiles.js 与 backend/controllers/profiles.js 确认响应里已包含该字段"
changeChecklist:
  - "复用现有 Tab 切换模式新增一个 Tab 项与对应内容组件（参考 ProfileArticles / ProfileFavArticles 的结构）"
  - "新内容组件放 frontend/src/routes/<页面>/ 或 components/，与现有目录习惯一致"
  - "需要独立 URL 时在 App.jsx 注册子路由；否则用现有切换状态"
  - "空态与加载态：无数据时给占位文案"
verification:
  - "npm test -- --run"
  - "npm run build -w frontend"
acceptance:
  - "新 Tab/页面入口出现在约定位置，与现有 Tab 样式一致"
  - "点击切换正确渲染内容；约定了独立 URL 时刷新不 404"
  - "空数据时显示约定的空态文案"
---

# 需求模式 Skill：新增页面或 Tab

## 适用场景

「个人主页加 About Me Tab 展示 User.bio」「个人主页加 Drafts Tab」「新增一个独立设置页」这类在现有页面骨架上增加入口和内容区的需求。

## 流程

1. 用 clarifyChecklist 确认挂载点、数据来源、空态和 URL 语义。
2. 先读现有 Tab/路由实现（Profile.jsx 的 Tab 切换、App.jsx 的 Routes），完全照搬现有模式，不发明新机制。
3. 新增内容组件 → 注册 Tab/路由 → 处理空态。
4. 跑 verification；建议预览 smoke 断言新 Tab 文案出现在页面上。

## 硬限制

- 必须复用页面现有的 Tab 切换/路由模式，禁止为单个 Tab 引入新的状态管理或路由库。
- 不破坏现有 Tab 的默认选中行为。
- 展示已有字段时先确认接口响应里真的有这个字段，不要假设。
