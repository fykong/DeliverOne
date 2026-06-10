from __future__ import annotations

from typing import Any

from server_py.core.json_io import now_iso


class PlanAuditor:
    def audit_plan(self, reply: str, preflight: dict[str, Any]) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        required_sections = ["需求", "计划", "风险"]
        for section in required_sections:
            if section not in reply:
                findings.append(
                    {
                        "id": f"missing-{section}",
                        "title": f"缺少“{section}”",
                        "detail": "计划输出需要覆盖需求确认、执行计划和风险确认，方便用户判断 Agent 是否理解正确。",
                        "severity": "warning",
                    }
                )

        if any(word in reply for word in ["已经修改", "已写入", "已完成代码"]):
            findings.append(
                {
                    "id": "claims-code-change",
                    "title": "计划阶段声称已经改代码",
                    "detail": "计划阶段不能声称已经修改代码，除非工具结果证明已经写入。",
                    "severity": "error",
                }
            )

        if not preflight.get("sandbox"):
            findings.append(
                {
                    "id": "missing-sandbox",
                    "title": "缺少对话沙盒",
                    "detail": "Agent 后续执行前必须先创建当前对话沙盒。",
                    "severity": "warning",
                }
            )

        if not preflight.get("repository"):
            findings.append(
                {
                    "id": "missing-repository",
                    "title": "缺少仓库上下文",
                    "detail": "没有仓库上下文时，计划只能停留在需求澄清，不能进入代码定位。",
                    "severity": "warning",
                }
            )

        return {
            "id": f"audit_{now_iso()}",
            "stage": "planning",
            "source": "PlanAuditor",
            "verdict": "blocked" if any(item["severity"] == "error" for item in findings) else ("warning" if findings else "pass"),
            "findings": findings,
            "reusedFrom": [
                "Codex skill-quality-reviewer 的确定性检查思路",
                "Codex verification-loop 的阶段门禁思路",
            ],
            "createdAt": now_iso(),
        }

    def audit_plan_confirmation(self, has_plan: bool, has_pending_confirmation: bool) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        if not has_plan:
            findings.append({"id": "missing-plan", "title": "缺少计划", "detail": "确认计划前必须已经生成过一轮 Agent 计划。", "severity": "error"})
        if not has_pending_confirmation:
            findings.append({"id": "not-waiting-confirmation", "title": "当前不在确认阶段", "detail": "只有等待计划确认时才能进入代码定位。", "severity": "error"})
        return {
            "id": f"audit_{now_iso()}",
            "stage": "plan_confirmation",
            "source": "PlanAuditor",
            "verdict": "blocked" if findings else "pass",
            "findings": findings,
            "reusedFrom": ["Codex approval gate 思路"],
            "createdAt": now_iso(),
        }

    def audit_structured_tool_plan(
        self,
        steps: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        fallback_reason: str | None = None,
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        tool_map = {tool.get("id"): tool for tool in tools}

        if fallback_reason:
            findings.append(
                {
                    "id": "structured-plan-fallback",
                    "title": "结构化计划回退",
                    "detail": fallback_reason,
                    "severity": "warning",
                }
            )

        if not steps:
            findings.append(
                {
                    "id": "empty-tool-plan",
                    "title": "工具计划为空",
                    "detail": "模型没有给出可执行工具步骤，系统会使用确定性默认计划。",
                    "severity": "warning",
                }
            )

        has_read_context = False
        has_read_file_context = False
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                findings.append(
                    {
                        "id": f"step-{index}-invalid",
                        "title": "步骤格式错误",
                        "detail": "每个工具步骤都必须是对象。",
                        "severity": "error",
                    }
                )
                continue

            tool_id = str(step.get("toolId", "")).strip()
            if not tool_id:
                findings.append(
                    {
                        "id": f"step-{index}-missing-tool",
                        "title": "缺少 toolId",
                        "detail": "结构化工具计划的每一步都必须声明 toolId。",
                        "severity": "error",
                    }
                )
                continue

            tool = tool_map.get(tool_id)
            if not tool:
                findings.append(
                    {
                        "id": f"step-{index}-unknown-tool",
                        "title": f"工具不存在：{tool_id}",
                        "detail": "模型只能使用工具目录中存在的工具。",
                        "severity": "error",
                    }
                )
                continue

            input_payload = step.get("input")
            if not isinstance(input_payload, dict):
                findings.append(
                    {
                        "id": f"step-{index}-missing-input",
                        "title": "缺少 input 对象",
                        "detail": "每个工具步骤都需要显式 input，方便用户审查。",
                        "severity": "error",
                    }
                )
                continue

            if tool_id in {"code.search_files", "code.read_file", "code.git_diff"}:
                has_read_context = True
            if tool_id == "code.read_file":
                has_read_file_context = True

            if tool_id in {"code.write_file", "code.apply_patch"} and not has_read_context:
                findings.append(
                    {
                        "id": f"step-{index}-write-before-read",
                        "title": "写入发生在读取上下文之前",
                        "detail": "写代码前必须先搜索、读取文件或检查 diff，避免凭空修改。",
                        "severity": "error",
                    }
                )

            if tool_id == "code.apply_patch" and not has_read_file_context:
                findings.append(
                    {
                        "id": f"step-{index}-patch-without-file-read",
                        "title": "补丁前缺少具体文件读取",
                        "detail": "修复补丁应先读取相关文件真实内容，避免模型只凭日志生成完整文件写入。",
                        "severity": "warning",
                    }
                )

            if tool.get("riskLevel") == "command":
                command = str(input_payload.get("command", "")).strip()
                if not command:
                    findings.append(
                        {
                            "id": f"step-{index}-missing-command",
                            "title": "命令步骤缺少 command",
                            "detail": "command.run 必须显式给出将在沙盒中执行的命令。",
                            "severity": "error",
                        }
                    )
                else:
                    findings.append(
                        {
                            "id": f"step-{index}-command-approval",
                            "title": "命令步骤需要审批提示",
                            "detail": f"命令 `{command}` 会进入权限策略判断，非可信命令必须用户确认。",
                            "severity": "warning",
                        }
                    )

            if tool.get("riskLevel") == "external":
                purpose = str(step.get("purpose", "")).strip()
                if not purpose:
                    findings.append(
                        {
                            "id": f"step-{index}-missing-external-purpose",
                            "title": "外部 MCP 工具缺少调用原因",
                            "detail": "外部 MCP 工具可能传输上下文，必须说明为什么需要调用。",
                            "severity": "warning",
                        }
                    )
                findings.append(
                    {
                        "id": f"step-{index}-external-approval",
                        "title": "外部 MCP 工具需要审批提示",
                        "detail": f"工具 `{tool_id}` 来自外部 MCP server，执行前会进入审批或由已确认的工具计划授权。",
                        "severity": "warning",
                    }
                )

            if tool.get("requiresCheckpoint") and tool.get("riskLevel") == "write":
                reason = str(input_payload.get("reason", "")).strip()
                if not reason:
                    findings.append(
                        {
                            "id": f"step-{index}-missing-write-reason",
                            "title": "写入步骤缺少 reason",
                            "detail": "写入工具需要说明修改原因，checkpoint 会使用该原因记录回退点。",
                            "severity": "warning",
                        }
                    )

        return {
            "id": f"audit_{now_iso()}",
            "stage": "planning",
            "source": "StructuredToolPlanAuditor",
            "verdict": "blocked" if any(item["severity"] == "error" for item in findings) else ("warning" if findings else "pass"),
            "findings": findings,
            "reusedFrom": [
                "Codex ToolDefinition 工具目录约束",
                "Codex approval gate 命令审批思路",
                "Codex apply_patch 前置上下文检查思路",
            ],
            "createdAt": now_iso(),
        }
