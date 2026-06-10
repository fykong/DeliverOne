---
id: pattern-frontend-display
name: 需求模式·纯前端展示增强
kind: requirement-pattern
description: 不改后端，在已有页面上增加展示性内容：图标+数字、标识徽标、统计文案（如阅读量、字数统计、前 N 个标签打标）。
riskLevel: low
requiresConfirmation: true
alwaysOn: false
triggers: [展示, 显示, 图标, 徽标, 打标, 阅读量, 字数, 统计, 标识, badge, icon]
tools: [code.search_files, code.read_file, code.apply_patch, command.run]
clarifyChecklist:
  - "展示在哪个页面的哪个位置（列表卡片 / 详情页正文下方 / 侧边栏）？"
  - "数据来源：接口已有字段、前端现算，还是允许先用假数据占位？"
  - "展示形态：纯文本、图标+数字，还是徽标样式？"
  - "数值为 0 或数据缺失时显示什么（隐藏 / 显示 0 / 占位符）？"
  - "如果是『前 N 个』类需求：N 取接口返回顺序还是某种排序？"
antiPatterns:
  - "需求说『加阅读量』但没说数据从哪来——如果后端没有该字段，必须确认是前端假数据还是要走全栈新增字段模式。"
  - "『前 5 个打标』如果被理解成要后端排序，就升级成了跨栈需求——先和用户确认是否纯前端取前 5。"
locateStrategy:
  frontend:
    - "列表卡片：frontend/src/components/ArticlesPreview/"
    - "文章详情：frontend/src/routes/Article/Article.jsx"
    - "侧边栏标签：frontend/src/components/PopularTags/"
    - "文章元信息（作者、日期区）：frontend/src/components/ArticleMeta/"
    - "样式：组件目录内的样式文件或 frontend/src/styles.css"
changeChecklist:
  - "目标组件：新增展示元素，遵循该组件现有的 JSX 结构和 class 命名风格"
  - "如需前端计算（字数/阅读时长），抽成 frontend/src/helpers/ 下的纯函数并配套 .test.js（参考 dateFormatter.test.js 的写法）"
  - "空值/边界处理：0、undefined、超长文本都要有确定行为"
verification:
  - "npm test -- --run"
  - "npm run build -w frontend"
acceptance:
  - "目标页面指定位置出现新展示元素，样式与周边一致"
  - "数据缺失/为 0 时页面表现符合约定"
  - "新增的计算函数有单元测试覆盖典型与边界输入"
---

# 需求模式 Skill：纯前端展示增强

## 适用场景

「首页文章卡片加阅读量图标」「正文下方显示本文共 X 字预计阅读 Y 分钟」「Popular Tags 前 5 个加标识」这类不改后端接口、只动前端展示层的需求。

## 流程

1. 用 clarifyChecklist 确认位置、数据来源和空值行为；任何『从哪来』不明确的数字都要追问。
2. 读取目标组件现有 JSX，确认插入点和现有 class 命名风格。
3. 计算逻辑抽纯函数进 helpers 并写单测；组件里只做渲染。
4. 改完跑 verification；前端类需求建议补预览 smoke 截图作为验收证据。

## 硬限制

- 不修改 backend/ 下任何文件；如果实现过程中发现必须改后端，停下来向用户说明并改走全栈模式。
- 假数据必须集中、显式（如常量或 helper 默认值），不能散落硬编码在 JSX 里。
- 不引入新的 npm 依赖来做简单文本统计。
