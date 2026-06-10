---
id: pattern-add-field-fullstack
name: 需求模式·全栈新增字段
kind: requirement-pattern
description: 给某个数据实体新增一个字段，并贯通数据库迁移、模型、接口序列化、前端表单与展示的跨栈一致性闭环。
riskLevel: medium
requiresConfirmation: true
alwaysOn: false
triggers: [新增字段, 加字段, 加一个字段, 增加字段, 封面图, coverImage, 字段, 新字段]
tools: [code.search_files, code.read_file, code.apply_patch, command.run]
clarifyChecklist:
  - "字段挂在哪个实体上（Article / Comment / User / Tag）？"
  - "字段名、类型、是否必填、默认值是什么？"
  - "字段值从哪里来：用户在表单输入，还是系统自动生成？"
  - "哪些页面要展示这个字段（列表卡片 / 详情页 / 编辑器 / 个人主页）？"
  - "旧数据怎么办：允许为空，还是需要回填默认值？"
  - "需不需要对字段做校验（格式、长度、URL 合法性）？"
antiPatterns:
  - "需求说『不要动后端』但字段需要持久化——纯前端存不住数据，必须向用户指出矛盾。"
  - "需求只说『加个字段』没说类型和展示位置——不能默认猜测，必须追问。"
locateStrategy:
  backend:
    - "模型定义：backend/models/<Entity>.js 的 init 字段块"
    - "迁移：backend/migrations/ 新增 addColumn 迁移（参考既有 create-article 迁移写法）"
    - "序列化：检查模型 toJSON 是否会隐藏新字段；控制器 backend/controllers/ 中实体的响应组装"
  frontend:
    - "编辑表单：frontend/src/components/ArticleEditorForm/（或对应实体的表单组件）"
    - "展示位置：frontend/src/components/ArticlesPreview/（列表卡片）、frontend/src/routes/Article/Article.jsx（详情页）"
    - "请求封装：frontend/src/services/ 中创建/更新该实体的文件，确认新字段进入请求体"
changeChecklist:
  - "backend/migrations/：新增 addColumn 迁移文件（字段可空或带默认值，保证旧数据兼容）"
  - "backend/models/<Entity>.js：init 中加字段定义，类型与迁移一致"
  - "backend/controllers/：创建和更新接口接受新字段；响应中包含新字段"
  - "frontend/src/services/：创建/更新请求体带上新字段"
  - "frontend 表单组件：新增受控输入项，含占位提示"
  - "frontend 展示组件：按需求在列表/详情渲染新字段（注意空值降级，不要渲染 broken UI）"
verification:
  - "npm test -- --run"
  - "npm run build -w frontend"
acceptance:
  - "编辑/新建表单中能输入新字段并成功保存"
  - "指定的展示页面能看到新字段内容；字段为空时页面不破版"
  - "旧数据（无该字段值）打开相关页面不报错"
---

# 需求模式 Skill：全栈新增字段

## 适用场景

「文章加封面图」「评论加点赞数」「用户加个人签名」这类给已有实体加字段、且要在前端可见可编辑的需求。

## 流程

1. 先用 clarifyChecklist 把字段定义补全；有任何一项缺失就追问，不要默认猜测。
2. 读取目标实体的模型、迁移、控制器和前端表单/展示组件，确认当前真实结构。
3. 按 changeChecklist 自后向前修改：迁移 → 模型 → 控制器 → service → 表单 → 展示。
4. 每个写入步骤前创建 checkpoint；改完跑 verification 命令。
5. 交付时在报告中列出「后端字段 → 前端类型/调用点」的对应关系，证明跨栈一致。

## 硬限制

- 迁移和模型字段类型必须一致，不允许只改模型不写迁移。
- 新字段必须允许为空或有默认值，禁止破坏已有数据。
- 检查 toJSON / 序列化白名单，确认新字段真的会出现在 API 响应里。
- 前端展示必须处理空值，禁止出现 undefined 文案或破图。
