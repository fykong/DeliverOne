# 仓库上下文 Skill

## 触发场景

用户接入仓库、提出代码修改需求、要求解释项目结构或需要定位文件时使用。

## 流程

1. 读取仓库画像：分支、HEAD、package scripts、dirty file count。
2. 搜索需求相关文件。
3. 读取候选文件内容。
4. 检查当前 diff，避免覆盖用户已有改动。
5. 把证据写入事件流和 memory。

## 限制

- 只读取当前对话沙盒仓库。
- 不凭空猜测文件位置。
- 不读取 node_modules、dist、build、coverage 等无关目录。
