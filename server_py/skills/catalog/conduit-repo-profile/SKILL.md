---
id: conduit-repo-profile
name: Conduit 仓库画像
kind: repo-profile
description: TonyMckes/conduit-realworld-example-app 的真实结构地图：目录、模型、路由、命令和测试入口，为模块定位提供精确锚点。
riskLevel: low
requiresConfirmation: false
alwaysOn: false
triggers: [conduit, realworld, 文章, 标签, 评论, 用户主页, 收藏, 关注, 博客]
tools: [code.search_files, code.read_file]
locateStrategy:
  backend:
    - "Sequelize 模型在 backend/models/（Article.js、Comment.js、Tag.js、User.js、index.js）"
    - "Express 路由在 backend/routes/（articles.js、profiles.js、tags.js、user.js、users.js）"
    - "控制器在 backend/controllers/（articles.js、comments.js、favorites.js、profiles.js、user.js、users.js）"
    - "数据库迁移在 backend/migrations/，由 sequelize-cli 管理，根目录命令 npm run sqlz"
    - "认证中间件在 backend/middleware/authentication.js，错误处理在 backend/middleware/errorHandler.js"
  frontend:
    - "页面级路由组件在 frontend/src/routes/（Home.jsx、ArticleEditor.jsx、Article/、Profile/、Settings.jsx）"
    - "可复用组件在 frontend/src/components/（ArticleEditorForm、ArticlesPreview、ArticleMeta、PopularTags、FavButton、CommentList 等，每个组件一个目录）"
    - "HTTP 请求封装在 frontend/src/services/（axios，按动作一个文件，如 getArticles.js）"
    - "全局状态在 frontend/src/context/（AuthContext.jsx、FeedContext.jsx），自定义 hook 在 frontend/src/hooks/"
verification:
  - "npm test -- --run （根目录 vitest，jsdom 环境，setup 在 frontend/src/setupTests.js）"
  - "npm run build -w frontend （Vite 构建，验证前端可编译）"
---

# Conduit 仓库画像 Skill

## 适用场景

当前对话沙盒是 conduit-realworld-example-app（或其裁剪 fork）时启用，为需求拆解和模块定位提供真实结构锚点。

## 仓库事实

1. monorepo：根 package.json 用 npm workspaces 管理 `backend` 和 `frontend` 两个子包。
2. 后端：Express 5 + Sequelize 6 + PostgreSQL（pg），JWT 认证（jsonwebtoken + bcrypt），入口 backend/index.js。
3. 前端：React 19 + Vite + react-router-dom 7 + axios，入口 frontend/src/main.jsx。
4. 模型关系：Article belongsTo User(author)、hasMany Comment、belongsToMany Tag(through TagList)、belongsToMany User(through Favorites)。
5. Article 字段：slug、title、description、body；toJSON 会隐藏 id 和 userId。
6. 常用命令（都在仓库根目录执行）：
   - `npm run dev`：concurrently 同时起后端（node --watch）和前端（vite）。
   - `npm test`：根目录 vitest；CI 场景加 `-- --run` 避免 watch 模式挂起。
   - `npm run sqlz`：sequelize-cli（迁移、seed）。
7. 仓库没有内置 lint 脚本和 eslint 配置；验证以 vitest 单测和前端 build 为准，不要编造 lint 命令。
8. 后端需要 PostgreSQL 和 backend/.env（参考 backend/.env.example）；沙盒里如果没有数据库，验证退化为单测 + 构建，不要尝试启动依赖数据库的集成流程。

## 硬限制

- 不要凭记忆猜测文件路径，先用 locateStrategy 中的锚点搜索确认。
- 修改 Sequelize 模型字段时必须同时检查 backend/migrations/ 是否需要新迁移。
- 前端发请求必须走 frontend/src/services/ 封装，不要在组件里裸写 axios。
- 测试命令必须用 `npm test -- --run`，避免 watch 模式导致执行卡住。
