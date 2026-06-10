# 关键工程难点与解决方案

对应提交材料清单"关键工程难点与解决方案"项。

## 1. Skill 注册热加载:新增需求模式零改主干

**难点**:比赛加分锚点要求"新增需求模式仅需新增 1 个 Skill 文件,不改主干"。初版注册依赖 `config/agent-skills.json` + 进程启动时一次性读取,实际需要改配置 + 重启,不达标。

**方案**(`server_py/skills/registry.py`):
- Skill 文件自描述:`catalog/<id>/SKILL.md` 的 YAML frontmatter 即注册信息(触发词、风险、模式字段)。
- 注册器对 catalog 目录 + 兼容配置做 **mtime 指纹**,每次 list/match 前比对指纹,变更即重载——保存文件即生效,无需重启,现场演示可直接验证(有测试覆盖:`test_skill_registry.py::test_hot_reload_new_skill_file`)。
- 模式字段(`clarifyChecklist`/`locateStrategy`/`changeChecklist`/`verification`/`acceptance`)结构化透传给澄清、规划与工具计划生成,Skill 从"展示文档"升级为"运行时约束"。

## 2. 澄清深度:从"提示模型要问"到可执行的歧义检测

**难点**:L3 考察模糊需求主动追问与反模式识别;单靠一句"不明确就追问"的 prompt,模型经常硬编方案。

**方案**(`server_py/agent/role_agents.py` + `orchestrator.py`):
- 六个歧义维度清单 + 命中模式 Skill 的专属 checklist 注入 Clarifier;要求输出结构化需求 DSL、歧义清单(含 blocking 标记)、反模式发现。
- Clarifier 判定 blocked 时编排器**短路**:不再调用规划模型,直接把追问写进对话回复——省 token,且澄清对 PM 可见。
- 规则兜底含矛盾启发(如"不动后端"+"持久化"),模型不可用时仍能给出模式专属追问。

## 3. 权限矩阵与"自管理命令工具"的放行困境

**难点**:`verification.run` / `browser.preview_smoke` 风险等级是 command,但 payload 里没有 shell 命令字段,权限层按"缺命令"直接 forbid 且无审批出路;修复循环自动追加预览断言步骤后必然失败,修复闭环跑不通。同时可信前缀白名单作用于原始 shell 字符串,`npm test && <任意命令>` 可整体放行(shell=True)。

**方案**(`server_py/runtime/permissions.py` + `tools/types.py`):
- 引入 `AgentTool.managed_command`:工具自己决定执行内容(验证器按栈选命令、预览只打本地端口),权限层对它走"已确认计划/显式授权 → 放行,否则审批",不再因缺 command 字段死锁。
- 可信前缀命中但包含 shell 连接符(`&& ; | $() > <` 等)时强制进入审批;持久化 allow 规则同样降级。
- 全部行为有测试覆盖(`test_permissions.py`)。

## 4. 交付完整性:未跟踪新文件的静默丢失

**难点**:`git status --porcelain` 不带 `-uall` 时,新建目录折叠为 `?? dir/`;应用回原仓库按文件复制会把目录路径当文件静默跳过,`git diff --binary` 生成的 patch 也不含未跟踪文件——代码生成最常见的"新增组件目录"场景交付物不完整且无报错。

**方案**(`server_py/delivery/service.py`):status 加 `-uall` 展开到文件;生成 patch 前 `git add -N -A`(intent-to-add)让新文件进入 diff。提测链路(`git_submission.py`)则直接 `git add -A` + commit,从 commit 生成 format-patch,从机制上保证完整。

## 5. 断点重放与事件溯源

**难点**:流程任一阶段可暂停/修改/重放,且证据必须可重建。

**方案**:所有动作经由 Orchestrator 写入 `events.jsonl`(事件溯源);工具计划支持编辑/自然语言重写(改后强制 Reviewer 重审 + 用户再确认);任务状态机支持阶段暂停与下一步动作覆盖;写入前 checkpoint 支持文件级/hunk 级/全仓回退,回退本身也产生报告进入证据链。

## 6. 提测(PR)链路在无凭证环境下的降级

**难点**:MVP 链路终点是提交 PR,但比赛环境不一定有 GitHub 写权限;同时沙盒是 `--depth 1` 浅克隆,直接 push 会被 GitHub 拒绝。

**方案**(`server_py/delivery/git_submission.py`):统一产出提测分支 + commit + PR 描述 + format-patch;检测到 `GITHUB_TOKEN` 且 origin 是 GitHub 时自动 `fetch --unshallow` → push → REST API 建 PR;任何一步失败都降级为 PR-ready 产物并保留失败原因,链路终点永远有交付物。
