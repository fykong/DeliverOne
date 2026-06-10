from __future__ import annotations

from typing import Any

from server_py.core.json_io import now_iso
from server_py.runtime.task_state_machine import TaskStateMachineService


class RuntimeSnapshotService:
    """Builds one reviewable runtime snapshot for the right-side status surface."""

    def __init__(self, task_state_machine: TaskStateMachineService | None = None) -> None:
        self.task_state_machine = task_state_machine or TaskStateMachineService()

    def build(
        self,
        state: dict[str, Any],
        tool_plan: dict[str, Any] | None,
        checkpoints: list[dict[str, Any]],
        events: list[dict[str, Any]],
        processes: list[dict[str, Any]],
        diff: dict[str, Any] | None = None,
        memory: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conversation_id = str(state.get("conversationId") or "")
        audits = state.get("audits") if isinstance(state.get("audits"), list) else []
        messages = state.get("messages") if isinstance(state.get("messages"), list) else []
        stages = self._stages(state, tool_plan, checkpoints, events, processes, diff, audits, messages, memory)
        active_stage = next((stage["id"] for stage in stages if stage["status"] in {"blocked", "current"}), stages[-1]["id"])
        blockers = [stage["summary"] for stage in stages if stage["status"] == "blocked" and stage.get("summary")]

        snapshot = {
            "conversationId": conversation_id,
            "phase": state.get("phase") or "idle",
            "summary": self._summary(stages),
            "activeStage": active_stage,
            "stages": stages,
            "evidence": self._evidence(tool_plan, checkpoints, events, processes, diff),
            "blockers": blockers,
            "warnings": state.get("stateWarnings", [])[-10:] if isinstance(state.get("stateWarnings"), list) else [],
            "nextActions": self._next_actions(state, tool_plan, checkpoints, diff),
            "reusedCodexMechanisms": [
                "状态面板只呈现当前任务阶段和下一步动作",
                "所有写入前必须经过 checkpoint 证据链",
                "工具计划按步骤执行并保留事件流",
                "失败后由 Verifier 结论驱动修复计划",
                "沙盒、命令、预览、回退都绑定到单个对话生命周期",
            ],
            "updatedAt": now_iso(),
        }
        snapshot["stateMachine"] = self.task_state_machine.persist(snapshot, state)
        controlled = self.task_state_machine.read(conversation_id)
        if isinstance(controlled.get("stages"), list):
            snapshot["stages"] = controlled["stages"]
        if controlled.get("activeStage"):
            snapshot["activeStage"] = controlled["activeStage"]
        if controlled.get("summary"):
            snapshot["summary"] = controlled["summary"]
        if isinstance(controlled.get("blockers"), list):
            snapshot["blockers"] = controlled["blockers"]
        if isinstance(controlled.get("nextActions"), list):
            snapshot["nextActions"] = controlled["nextActions"]
        return snapshot

    def _stages(
        self,
        state: dict[str, Any],
        plan: dict[str, Any] | None,
        checkpoints: list[dict[str, Any]],
        events: list[dict[str, Any]],
        processes: list[dict[str, Any]],
        diff: dict[str, Any] | None,
        audits: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        memory: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        clarifier = self._latest_audit(audits, "Clarifier")
        # 提问/闲聊输入的 Clarifier 审计只是意图路由依据(已转对话回答),
        # 不是交付阻断——别让状态机因为用户问了句话就显示红色"阻断"。
        if clarifier and str(clarifier.get("inputIntent") or "development") != "development":
            clarifier = None
        reviewer = self._latest_audit((plan or {}).get("audits", []) + audits if plan else audits, "Reviewer")
        verifier = self._latest_audit((plan or {}).get("audits", []) + audits if plan else audits, "Verifier")
        diff_count = int((diff or {}).get("fileCount") or 0)
        verification_count = len(((plan or {}).get("evidence") or {}).get("verificationResults", [])) if plan else 0
        has_delivery = any(item.get("type") == "delivery.package.generated" for item in events)
        has_rollback = any(str(item.get("type", "")).startswith("rollback.") for item in events)
        has_requirement = bool(state.get("lastRequirement")) or bool((plan or {}).get("requirement")) or any(item.get("role") == "user" for item in messages)
        has_sandbox = isinstance(state.get("sandbox"), dict) and bool(state["sandbox"].get("repoPath"))
        has_plan_turn = bool(state.get("turns")) or bool(plan)
        plan_status = (plan or {}).get("status")
        failed_steps = [step for step in (plan or {}).get("steps", []) if isinstance(step, dict) and step.get("status") == "failed"]
        waiting_tool_approval = plan_status == "waiting_approval"
        reviewer_blocked = reviewer and reviewer.get("verdict") == "blocked"
        clarifier_blocked = clarifier and clarifier.get("verdict") == "blocked"
        verifier_failed = verifier and verifier.get("verdict") in {"blocked", "warning"} and (plan_status == "failed" or failed_steps)
        running_processes = [item for item in processes if item.get("status") in {"starting", "running"}]
        memory_ledger = (memory or {}).get("taskLedger") if isinstance(memory, dict) else None

        stages = [
            self._stage(
                "requirement",
                "需求",
                "用户",
                "done" if has_requirement else "current",
                "需求已进入对话。" if has_requirement else "先输入要交付的真实需求。",
                {"消息": len(messages)},
                ["submit_requirement"] if has_sandbox else [],
            ),
            self._stage(
                "clarification",
                "澄清",
                "Clarifier",
                "blocked" if clarifier_blocked else ("done" if clarifier else ("pending" if not has_requirement else "current")),
                clarifier.get("summary") if clarifier else "判断需求是否足够进入方案和工具计划。",
                {"审查": 1 if clarifier else 0},
                ["submit_requirement"] if clarifier_blocked else [],
            ),
            self._stage(
                "plan",
                "方案",
                "Agent",
                "done" if has_plan_turn else ("current" if has_requirement else "pending"),
                "模型方案已生成，等待进入工具计划。" if has_plan_turn else "生成可审查的实现方案。",
                {"轮次": len(state.get("turns", []))},
                ["approve_plan"] if state.get("phase") == "waiting_plan_confirmation" else [],
            ),
            self._stage(
                "tool-plan",
                "工具计划",
                "Reviewer",
                "blocked" if reviewer_blocked else ("current" if plan_status == "waiting_confirmation" else ("done" if plan else "pending")),
                reviewer.get("summary") if reviewer else ("工具步骤已生成。" if plan else "将方案拆成可审查工具调用。"),
                {"步骤": len((plan or {}).get("steps", []))},
                ["edit_tool_plan", "approve_tool_plan"] if plan_status == "waiting_confirmation" else [],
            ),
            self._stage(
                "approval",
                "审批",
                "用户",
                "current" if plan_status in {"waiting_confirmation", "waiting_approval", "approved"} else ("done" if plan_status in {"running", "completed", "failed"} else "pending"),
                "确认后才会执行命令或写入步骤。" if plan_status == "waiting_confirmation" else ("有工具步骤等待授权。" if waiting_tool_approval else "审批状态随工具计划推进。"),
                {"待授权": 1 if waiting_tool_approval else 0},
                ["approve_tool_plan", "execute_tool_plan"] if plan_status in {"waiting_confirmation", "approved", "waiting_approval"} else [],
            ),
            self._stage(
                "execution",
                "执行",
                "Runtime",
                "blocked" if waiting_tool_approval else ("current" if plan_status == "running" else ("done" if plan_status in {"completed", "failed"} else "pending")),
                "工具正在沙盒内执行。" if plan_status == "running" else ("等待授权后继续。" if waiting_tool_approval else "按计划调用工具并记录结果。"),
                {"工具结果": len(((plan or {}).get("evidence") or {}).get("toolResults", [])) if plan else 0},
                ["grant_approval"] if waiting_tool_approval else [],
            ),
            self._stage(
                "verification",
                "验证",
                "Verifier",
                "blocked" if verifier_failed else ("done" if verification_count or (verifier and verifier.get("verdict") == "pass") else ("current" if plan_status == "completed" else "pending")),
                verifier.get("summary") if verifier else "运行测试、构建、lint、smoke，并把结果交给 Verifier。",
                {"验证": verification_count},
                ["repair_failed_plan"] if verifier_failed else ["run_verification"] if has_sandbox else [],
            ),
            self._stage(
                "repair",
                "修复",
                "Agent",
                "current" if plan and plan.get("repairOfPlanId") and plan_status == "waiting_confirmation" else ("blocked" if failed_steps and not plan.get("repairOfPlanId") else "pending"),
                f"修复计划 #{plan.get('repairSequence')} 等待审查。" if plan and plan.get("repairOfPlanId") else "失败后读取证据、生成修复计划、再复验。",
                {"失败步骤": len(failed_steps), "修复轮次": int((plan or {}).get("repairSequence") or 0)},
                ["repair_failed_plan"] if failed_steps else [],
            ),
            self._stage(
                "delivery",
                "交付",
                "Runtime",
                "done" if has_delivery else ("current" if plan_status == "completed" and diff_count > 0 else "pending"),
                "交付包已生成。" if has_delivery else "交付必须绑定 diff、checkpoint 和验证证据。",
                {"变更": diff_count, "检查点": len(checkpoints)},
                ["generate_delivery"] if plan_status == "completed" else [],
            ),
            self._stage(
                "rollback",
                "回退",
                "用户",
                "done" if has_rollback else ("current" if checkpoints or diff_count > 0 else "pending"),
                "回退已记录。" if has_rollback else "支持检查点回退、文件回退、hunk 回退和回到原始仓库。",
                {"检查点": len(checkpoints)},
                ["rollback_checkpoint", "rollback_original"] if checkpoints else [],
            ),
            self._stage(
                "preview",
                "预览",
                "Runtime",
                "current" if running_processes else ("done" if any(item.get("type") == "preview.smoke.end" for item in events) else ("pending" if has_sandbox else "blocked")),
                "沙盒预览进程正在运行。" if running_processes else "在当前对话沙盒里启动预览命令并收集 smoke 证据。",
                {"进程": len(processes), "运行中": len(running_processes)},
                ["start_preview"] if has_sandbox else [],
            ),
            self._stage(
                "memory",
                "记忆",
                "Memory",
                "done" if memory_ledger else ("current" if has_requirement else "pending"),
                "Task Ledger、搜索意图和长期记忆已进入上下文。" if memory_ledger else "沉淀用户偏好、失败模式和仓库画像。",
                {"账本": 1 if memory_ledger else 0},
                ["review_memory"] if memory_ledger else [],
            ),
        ]
        return stages

    def _stage(
        self,
        stage_id: str,
        title: str,
        owner: str,
        status: str,
        summary: str,
        evidence: dict[str, int],
        actions: list[str],
    ) -> dict[str, Any]:
        return {
            "id": stage_id,
            "title": title,
            "owner": owner,
            "status": status,
            "summary": summary,
            "evidence": evidence,
            "actions": actions,
        }

    def _evidence(
        self,
        plan: dict[str, Any] | None,
        checkpoints: list[dict[str, Any]],
        events: list[dict[str, Any]],
        processes: list[dict[str, Any]],
        diff: dict[str, Any] | None,
    ) -> dict[str, int]:
        plan_evidence = (plan or {}).get("evidence") or {}
        return {
            "toolResults": len(plan_evidence.get("toolResults", [])),
            "checkpoints": len(checkpoints),
            "diffFiles": int((diff or {}).get("fileCount") or len(plan_evidence.get("diffFiles", []))),
            "verificationResults": len(plan_evidence.get("verificationResults", [])),
            "events": len(events),
            "processes": len(processes),
            "deliveryPackages": sum(1 for item in events if item.get("type") == "delivery.package.generated"),
            "rollbackEvents": sum(1 for item in events if str(item.get("type", "")).startswith("rollback.")),
        }

    def _next_actions(
        self,
        state: dict[str, Any],
        plan: dict[str, Any] | None,
        checkpoints: list[dict[str, Any]],
        diff: dict[str, Any] | None,
    ) -> list[dict[str, str]]:
        actions: list[dict[str, str]] = []
        if not state.get("sandbox"):
            actions.append({"id": "connect_repository", "label": "接入仓库", "kind": "read"})
        if state.get("phase") == "waiting_plan_confirmation":
            actions.append({"id": "approve_plan", "label": "确认方案", "kind": "approval"})
        if plan and plan.get("status") == "waiting_confirmation":
            actions.append({"id": "edit_tool_plan", "label": "审查/编辑工具计划", "kind": "approval"})
            actions.append({"id": "approve_tool_plan", "label": "确认并执行", "kind": "approval"})
        if plan and plan.get("status") in {"approved", "waiting_approval"}:
            actions.append({"id": "execute_tool_plan", "label": "继续执行工具计划", "kind": "write"})
        if plan and (plan.get("status") == "failed" or any(step.get("status") == "failed" for step in plan.get("steps", []) if isinstance(step, dict))):
            actions.append({"id": "repair_failed_plan", "label": "生成修复计划", "kind": "write"})
        if state.get("sandbox"):
            actions.append({"id": "start_preview", "label": "启动沙盒预览", "kind": "command"})
        if plan and plan.get("status") == "completed" and int((diff or {}).get("fileCount") or 0) > 0:
            actions.append({"id": "generate_delivery", "label": "生成交付包", "kind": "write"})
        if checkpoints:
            actions.append({"id": "rollback_checkpoint", "label": "回退到检查点", "kind": "write"})
        return actions

    def _summary(self, stages: list[dict[str, Any]]) -> str:
        active = next((stage for stage in stages if stage["status"] in {"blocked", "current"}), None)
        if not active:
            return "任务状态机已完成当前可见链路。"
        return f"当前阶段：{active['title']}。{active['summary']}"

    def _latest_audit(self, audits: list[dict[str, Any]], source: str) -> dict[str, Any] | None:
        for audit in reversed(audits):
            if isinstance(audit, dict) and audit.get("source") == source:
                return audit
        return None
