from __future__ import annotations

from typing import Any

from server_py.agent.role_agents import AgentRoleSuite
from server_py.agent.tool_call_plan import ToolCallPlanService
from server_py.agent.tool_plan_drafter import ToolPlanDrafter
from server_py.agent.workflow import AgentWorkflow
from server_py.conversations.store import ConversationStore
from server_py.memory.memory_service import MemoryService
from server_py.preview.process_registry import ProcessRegistry
from server_py.runtime.events import EventStore
from server_py.runtime.sandbox_runtime import SandboxRuntimeService
from server_py.runtime.snapshot import RuntimeSnapshotService
from server_py.runtime.task_state_machine import TaskStateMachineService
from server_py.sandbox.checkpoint_manager import CheckpointManager
from server_py.sandbox.diff_service import SandboxDiffService
from server_py.sandbox.file_browser import SandboxFileBrowser
from server_py.skills.runtime import SkillRuntime
from server_py.tools.types import ToolRunner


class AgentOrchestrator:
    """Backend-owned task loop inspired by Codex runtime events.

    The frontend sends intent-level actions. The orchestrator advances the
    conversation, writes events, and returns one fresh bundle for the UI.
    """

    def __init__(
        self,
        workflow: AgentWorkflow,
        conversations: ConversationStore,
        memory: MemoryService,
        tool_call_plans: ToolCallPlanService,
        tool_plan_drafter: ToolPlanDrafter,
        tools: ToolRunner,
        roles: AgentRoleSuite,
        events: EventStore,
        checkpoints: CheckpointManager,
        processes: ProcessRegistry,
        file_browser: SandboxFileBrowser,
        runtime_snapshot: RuntimeSnapshotService,
        sandbox_runtime: SandboxRuntimeService,
        diff: SandboxDiffService,
        task_state_machine: TaskStateMachineService,
        skills: SkillRuntime | None = None,
    ) -> None:
        self.workflow = workflow
        self.conversations = conversations
        self.memory = memory
        self.tool_call_plans = tool_call_plans
        self.tool_plan_drafter = tool_plan_drafter
        self.tools = tools
        self.roles = roles
        self.events = events
        self.checkpoints = checkpoints
        self.processes = processes
        self.file_browser = file_browser
        self.runtime_snapshot = runtime_snapshot
        self.sandbox_runtime = sandbox_runtime
        self.diff = diff
        self.task_state_machine = task_state_machine
        self.skills = skills

    def run(
        self,
        conversation_id: str,
        action: str,
        repository: dict[str, Any] | None = None,
        sandbox: dict[str, Any] | None = None,
        requirement: str | None = None,
        plan_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_action = action.strip()
        self.events.append(conversation_id, "orchestrator.action.begin", {"action": normalized_action}, actor="runtime")
        try:
            self._guard_task_state_control(conversation_id, normalized_action)
            output = self._dispatch(
                conversation_id=conversation_id,
                action=normalized_action,
                repository=repository,
                sandbox=sandbox,
                requirement=requirement,
                plan_id=plan_id,
            )
            self.events.append(
                conversation_id,
                "orchestrator.action.end",
                {"action": normalized_action, "phase": self.conversations.get(conversation_id).get("phase")},
                actor="runtime",
            )
            return self._bundle(conversation_id, **output)
        except Exception as error:
            self.memory.record_failure(conversation_id, "编排动作失败", f"动作：{normalized_action}\n错误：{error}", "orchestrator")
            self.events.append(
                conversation_id,
                "orchestrator.action.failed",
                {"action": normalized_action, "error": str(error)},
                actor="runtime",
            )
            raise

    def autopilot(
        self,
        conversation_id: str,
        requirement: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        max_rounds: int = 12,
        delivery: Any = None,
        submission: Any = None,
        verification_runner: Any = None,
    ) -> dict[str, Any]:
        """托管模式：一条需求指令自动推进到提测，免去逐步人工确认。

        自动确认以 actor=autopilot 写入事件流，全程可审计可回退。
        安全停车点（needsHuman）：澄清不通过、Reviewer 阻断、修复/推进
        轮次到上限、执行失败且无法自动修复。危险命令仍被权限层拦截。
        """
        trace: list[dict[str, Any]] = []
        summary: dict[str, Any] = {
            "finished": False,
            "needsHuman": False,
            "stage": "submit",
            "reason": "",
            "rounds": 0,
            "trace": trace,
            "delivery": None,
            "submission": None,
        }
        self.events.append(
            conversation_id,
            "autopilot.begin",
            {"requirement": requirement[:400], "maxRounds": max_rounds},
            actor="autopilot",
        )

        def finish(bundle: dict[str, Any]) -> dict[str, Any]:
            self.events.append(
                conversation_id,
                "autopilot.end",
                {
                    "finished": summary["finished"],
                    "needsHuman": summary["needsHuman"],
                    "stage": summary["stage"],
                    "reason": summary["reason"],
                    "rounds": summary["rounds"],
                },
                actor="autopilot",
            )
            bundle["autopilot"] = summary
            return bundle

        bundle = self.run(conversation_id, "submit_requirement", repository, sandbox, requirement=requirement)
        trace.append({"action": "submit_requirement", "phase": (bundle.get("conversation") or {}).get("phase")})
        turn = bundle.get("turn") or {}
        if turn.get("phase") == "clarification":
            summary.update(
                needsHuman=True,
                stage="clarification",
                reason="需求存在阻断性歧义，托管模式停在澄清环节，请先回答追问。",
            )
            return finish(bundle)

        state = self.conversations.get(conversation_id)
        if state.get("phase") == "waiting_plan_confirmation":
            self.events.append(conversation_id, "autopilot.auto_approve", {"target": "plan"}, actor="autopilot")
            bundle = self.run(conversation_id, "approve_plan", repository, sandbox, requirement=requirement)
            trace.append({"action": "approve_plan", "phase": (bundle.get("conversation") or {}).get("phase")})
        if self.conversations.get(conversation_id).get("phase") == "waiting_sandbox":
            summary.update(needsHuman=True, stage="sandbox", reason="当前对话还没有沙盒，请先接入仓库。")
            return finish(bundle)

        while summary["rounds"] < max_rounds:
            plan = self.tool_call_plans.get_plan(conversation_id)
            if not plan:
                summary.update(needsHuman=True, stage="tool-plan", reason="没有生成工具计划。")
                return finish(bundle)
            status = plan.get("status")
            if status == "waiting_confirmation":
                try:
                    self.events.append(
                        conversation_id,
                        "autopilot.auto_approve",
                        {"target": "tool_plan", "planId": plan.get("id")},
                        actor="autopilot",
                    )
                    bundle = self.run(conversation_id, "approve_tool_plan", repository, sandbox)
                    trace.append({"action": "approve_tool_plan", "planId": plan.get("id")})
                except Exception as error:
                    summary.update(
                        needsHuman=True,
                        stage="review-blocked",
                        reason=f"工具计划无法自动确认：{error}",
                    )
                    return finish(self._bundle(conversation_id))
                continue
            if status == "approved":
                summary["rounds"] += 1
                bundle = self.run(conversation_id, "execute_tool_plan", repository, sandbox)
                executed = bundle.get("executedToolPlan") or {}
                current = bundle.get("toolPlan") or {}
                trace.append(
                    {
                        "action": "execute_tool_plan",
                        "round": summary["rounds"],
                        "executedPlanId": executed.get("id"),
                        "executedStatus": executed.get("status"),
                        "nextPlanId": current.get("id") if current.get("id") != executed.get("id") else None,
                        "nextPlanSource": (current.get("generation") or {}).get("source")
                        if current.get("id") != executed.get("id")
                        else None,
                    }
                )
                if current.get("id") != executed.get("id") and current.get("status") == "waiting_confirmation":
                    continue  # 修复或推进计划已就绪，下一轮自动确认
                if executed.get("status") == "completed":
                    should_continue, reason = self._should_create_continuation_plan(executed)
                    if not should_continue:
                        summary.update(finished=True, stage="done", reason=reason)
                        break
                    summary.update(needsHuman=True, stage="continuation", reason=f"推进循环未能自动生成下一轮计划：{reason}")
                    return finish(bundle)
                summary.update(
                    needsHuman=True,
                    stage="execution-failed",
                    reason=str(
                        (bundle.get("repairLoop") or {}).get("reason")
                        or "执行失败且没有可自动确认的修复计划。"
                    ),
                )
                return finish(bundle)
            if status == "completed":
                should_continue, reason = self._should_create_continuation_plan(plan)
                if not should_continue:
                    summary.update(finished=True, stage="done", reason=reason)
                    break
                try:
                    self._create_continuation_plan(conversation_id, plan)
                    continue
                except Exception as error:
                    summary.update(needsHuman=True, stage="continuation", reason=str(error))
                    return finish(self._bundle(conversation_id))
            summary.update(needsHuman=True, stage="plan-status", reason=f"计划状态 {status} 需要人工处理。")
            return finish(self._bundle(conversation_id))

        if not summary["finished"]:
            summary.update(needsHuman=True, stage="round-cap", reason=f"托管轮次达到上限 {max_rounds}，请人工审查后继续。")
            return finish(self._bundle(conversation_id))

        # 交付前终检：重新跑一次验证，避免门禁读到历史失败报告。
        if verification_runner is not None:
            try:
                state = self.conversations.get(conversation_id)
                sandbox_state = state.get("sandbox") or {}
                if sandbox_state.get("repoPath"):
                    self.events.append(conversation_id, "autopilot.final_verification.begin", {}, actor="autopilot")
                    final_report = verification_runner.run(
                        conversation_id=conversation_id,
                        sandbox={"id": sandbox_state.get("id"), "repoPath": sandbox_state.get("repoPath")},
                    )
                    self.events.append(
                        conversation_id,
                        "autopilot.final_verification.end",
                        {"status": final_report.get("status"), "summary": str(final_report.get("summary"))[:200]},
                        actor="autopilot",
                    )
                    if final_report.get("status") != "pass":
                        summary.update(
                            finished=False,
                            needsHuman=True,
                            stage="final-verification",
                            reason=f"交付终检未通过：{final_report.get('summary')}",
                        )
                        return finish(self._bundle(conversation_id))
            except Exception as error:
                summary["reason"] += f"（交付终检执行失败：{error}）"

        # 验证绿后自动产出交付物：交付包 + 提测分支（PR-ready / GitHub PR）。
        if delivery is not None and submission is not None:
            try:
                state = self.conversations.get(conversation_id)
                plan = self.tool_call_plans.sync_latest_reports(conversation_id) or self.tool_call_plans.get_plan(conversation_id)
                checkpoints = self.checkpoints.list(conversation_id)
                events = self.events.list(conversation_id, 300)
                report = delivery.package(conversation_id, state, plan, checkpoints, events)
                summary["delivery"] = {
                    "verificationGate": (report.get("verificationGate") or {}).get("status"),
                    "changedFiles": len(report.get("changedFiles", [])),
                }
                if (report.get("verificationGate") or {}).get("status") == "pass":
                    record = submission.submit(
                        conversation_id,
                        state,
                        plan,
                        confirmed=True,
                        title=self._autopilot_title(requirement),
                    )
                    summary["submission"] = {
                        "mode": record.get("mode"),
                        "branch": record.get("branch"),
                        "commitSha": record.get("commitSha"),
                        "prUrl": (record.get("pullRequest") or {}).get("url"),
                    }
                else:
                    summary["reason"] += "（验证门禁未通过，已生成交付包但未自动提测。）"
            except Exception as error:
                summary["reason"] += f"（交付产出失败：{error}）"

        return finish(self._bundle(conversation_id))

    def _autopilot_title(self, requirement: str) -> str:
        first_line = (requirement.splitlines() or [""])[0].strip()
        return first_line[:72] or "AI Delivery Workbench 托管交付"

    def _dispatch(
        self,
        conversation_id: str,
        action: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        requirement: str | None,
        plan_id: str | None,
    ) -> dict[str, Any]:
        if action == "refresh":
            return {}

        if action == "submit_requirement":
            next_requirement = (requirement or "").strip()
            if not next_requirement:
                raise RuntimeError("需求不能为空。")
            memory_snapshot = self.memory.snapshot(
                conversation_id, repository=repository, requirement=next_requirement, sandbox=sandbox
            )
            clarification = self.roles.clarify(
                next_requirement,
                repository,
                sandbox,
                conversation_id,
                memory_snapshot=memory_snapshot,
            )
            self.events.append(
                conversation_id,
                "agent.role.clarifier",
                {
                    "verdict": clarification["verdict"],
                    "summary": clarification.get("summary"),
                    "recommendation": clarification.get("recommendation"),
                    "questions": clarification.get("questions", []),
                    "findings": clarification["findings"],
                },
                actor="agent",
            )
            if clarification.get("verdict") == "blocked":
                # 需求不可执行时短路：不调用规划模型，直接把追问作为 Agent 回复送回对话。
                turn = self.workflow.clarification_turn(
                    conversation_id, next_requirement, repository, sandbox, clarification
                )
            else:
                turn = self.workflow.plan(conversation_id, next_requirement, repository, sandbox)
            turn.setdefault("audits", []).append(clarification)
            self.conversations.record_audit(conversation_id, clarification)
            return {"turn": turn}

        if action == "approve_plan":
            state_before_confirm = self.conversations.get(conversation_id)
            clarification_block = self._latest_blocked_role_audit(state_before_confirm, "Clarifier")
            if clarification_block:
                reason = clarification_block.get("summary") or "Clarifier 判断需求还不能进入工具计划。"
                raise RuntimeError(f"{reason} 请先补充澄清问题后再确认方案。")
            turn = self.workflow.confirm_plan(conversation_id)
            state = self.conversations.get(conversation_id)
            if state.get("phase") == "waiting_sandbox":
                return {"turn": turn}

            plan_requirement = (requirement or state.get("lastRequirement") or "").strip()
            if not plan_requirement:
                raise RuntimeError("生成工具计划前缺少需求。")
            previous_turn = state.get("turns", [])[-1] if state.get("turns") else None
            tools = self.tools.list()
            draft = self.tool_plan_drafter.draft(
                conversation_id=conversation_id,
                requirement=plan_requirement,
                repository=state.get("repository") or repository,
                sandbox=state.get("sandbox") or sandbox,
                tools=tools,
                previous_turn=previous_turn,
            )
            try:
                plan = self.tool_call_plans.create_plan(
                    conversation_id=conversation_id,
                    requirement=plan_requirement,
                    repository=state.get("repository") or repository,
                    sandbox=state.get("sandbox") or sandbox,
                    tools=tools,
                    requested_steps=draft.get("steps") or None,
                    generation={
                        "source": draft.get("source"),
                        "rawResponse": draft.get("rawResponse"),
                        "fallbackReason": draft.get("fallbackReason"),
                    },
                    audits=[draft["audit"]] if draft.get("audit") else [],
                )
            except Exception as error:
                self.events.append(
                    conversation_id,
                    "tool_plan.structured.fallback",
                    {"reason": str(error)},
                    actor="runtime",
                )
                plan = self.tool_call_plans.create_plan(
                    conversation_id=conversation_id,
                    requirement=plan_requirement,
                    repository=state.get("repository") or repository,
                    sandbox=state.get("sandbox") or sandbox,
                    tools=tools,
                    generation={
                        "source": "fallback",
                        "rawResponse": draft.get("rawResponse"),
                        "fallbackReason": f"结构化计划标准化失败：{error}",
                    },
                    audits=[draft["audit"]] if draft.get("audit") else [],
                )
            review_memory = self.memory.snapshot(
                conversation_id,
                repository=state.get("repository") or repository,
                requirement=plan_requirement,
            )
            review = self.roles.review_tool_plan(
                plan, conversation_id, memory_snapshot=review_memory, prefer_rules=self._plan_is_read_only(plan)
            )
            plan = self.tool_call_plans.append_audit(conversation_id, review, plan["id"])
            self.events.append(
                conversation_id,
                "agent.role.reviewer",
                {
                    "verdict": review["verdict"],
                    "summary": review.get("summary"),
                    "recommendation": review.get("recommendation"),
                    "findings": review["findings"],
                    "planId": plan["id"],
                },
                actor="agent",
            )
            self.events.append(
                conversation_id,
                "tool_plan.structured.generated",
                {"source": draft.get("source"), "fallbackReason": draft.get("fallbackReason"), "stepCount": len(draft.get("steps") or [])},
                actor="agent",
            )
            return {"turn": turn, "tool_plan": plan}

        if action == "approve_tool_plan":
            plan = self.tool_call_plans.approve_plan(conversation_id, plan_id)
            return {"tool_plan": plan}

        if action == "execute_tool_plan":
            plan = self.tool_call_plans.execute_plan(conversation_id, self.tools, plan_id)
            synced_plan = self.tool_call_plans.sync_latest_reports(conversation_id, plan["id"])
            if synced_plan:
                plan = synced_plan
            verification_memory = self.memory.snapshot(
                conversation_id,
                repository=plan.get("repository"),
                requirement=plan.get("requirement"),
            )
            verification = self.roles.verify_execution(
                plan, conversation_id, memory_snapshot=verification_memory, prefer_rules=self._plan_is_read_only(plan)
            )
            plan = self.tool_call_plans.append_audit(conversation_id, verification, plan["id"])
            self.events.append(
                conversation_id,
                "agent.role.verifier",
                {
                    "verdict": verification["verdict"],
                    "summary": verification.get("summary"),
                    "recommendation": verification.get("recommendation"),
                    "findings": verification["findings"],
                    "planId": plan["id"],
                    "repairAttempt": plan.get("repairAttempt"),
                    "repairSequence": plan.get("repairSequence"),
                    "failureClass": verification.get("failureClass"),
                    "repairPolicy": verification.get("repairPolicy"),
                },
                actor="agent",
            )
            repair_plan, repair_loop = self._maybe_create_repair_plan(conversation_id, plan)
            if repair_plan:
                return {
                    "tool_plan": repair_plan,
                    "executed_tool_plan": plan,
                    "repair_plan": repair_plan,
                    "repair_loop": repair_loop,
                }
            continuation_plan, continuation_loop = self._maybe_create_continuation_plan(conversation_id, plan)
            if continuation_plan:
                return {
                    "tool_plan": continuation_plan,
                    "executed_tool_plan": plan,
                    "repair_loop": repair_loop,
                    "continuation_loop": continuation_loop,
                }
            return {
                "tool_plan": plan,
                "executed_tool_plan": plan,
                "repair_loop": repair_loop,
                "continuation_loop": continuation_loop,
            }

        if action == "repair_failed_plan":
            source_plan = self.tool_call_plans.get_plan(conversation_id)
            if not source_plan:
                raise RuntimeError("当前对话没有可修复的工具计划。")
            plan = self._create_repair_plan(conversation_id, source_plan, trigger="manual")
            return {"tool_plan": plan}

        if action == "continue_plan":
            source_plan = self.tool_call_plans.get_plan(conversation_id)
            if not source_plan:
                raise RuntimeError("当前对话没有可推进的工具计划。")
            should, reason = self._should_create_continuation_plan(source_plan)
            if not should:
                raise RuntimeError(f"当前不需要推进计划：{reason}")
            plan = self._create_continuation_plan(conversation_id, source_plan)
            return {"tool_plan": plan, "continuation_loop": {"created": True, "sourcePlanId": source_plan.get("id"), "continuationPlanId": plan.get("id"), "trigger": "manual"}}

        raise RuntimeError(f"未知编排动作：{action}")

    def _bundle(
        self,
        conversation_id: str,
        turn: dict[str, Any] | None = None,
        tool_plan: dict[str, Any] | None = None,
        executed_tool_plan: dict[str, Any] | None = None,
        repair_plan: dict[str, Any] | None = None,
        repair_loop: dict[str, Any] | None = None,
        continuation_loop: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.conversations.get(conversation_id)
        current_plan = tool_plan if tool_plan is not None else self.tool_call_plans.get_plan(conversation_id)
        sandbox = state.get("sandbox")
        files = None
        current_diff = None
        if isinstance(sandbox, dict) and sandbox.get("repoPath"):
            try:
                files = self.file_browser.list_tree(sandbox["repoPath"])
            except Exception as error:
                files = {"rootPath": sandbox.get("repoPath"), "items": [], "truncated": False, "error": str(error)}
            try:
                current_diff = self.diff.current(conversation_id, sandbox["repoPath"])
            except Exception as error:
                current_diff = {"conversationId": conversation_id, "kind": "current", "summary": str(error), "fileCount": 0, "files": []}

        checkpoints = self.checkpoints.list(conversation_id)
        events = self.events.list(conversation_id, 200)
        processes = [
            process for process in self.processes.list() if process.get("conversationId") == conversation_id
        ]
        try:
            memory = self.memory.snapshot(conversation_id, repository=state.get("repository"), requirement=state.get("lastRequirement"))
        except Exception:
            memory = None

        return {
            "conversation": state,
            "turn": turn,
            "toolPlan": current_plan,
            "executedToolPlan": executed_tool_plan,
            "repairPlan": repair_plan,
            "repairLoop": repair_loop,
            "continuationLoop": continuation_loop,
            "checkpoints": checkpoints,
            "events": events,
            "processes": processes,
            "files": files,
            "runtimeSnapshot": self.runtime_snapshot.build(
                state=state,
                tool_plan=current_plan,
                checkpoints=checkpoints,
                events=events,
                processes=processes,
                diff=current_diff,
                memory=memory,
            ),
            "sandboxRuntime": self.sandbox_runtime.build(
                state=state,
                processes=processes,
                checkpoints=checkpoints,
                events=events,
                diff=current_diff,
                files=files,
            ),
            "nextActions": self._next_actions(state, current_plan),
        }

    def _next_actions(self, state: dict[str, Any], plan: dict[str, Any] | None) -> list[dict[str, str]]:
        actions: list[dict[str, str]] = [{"id": "refresh", "label": "刷新状态", "kind": "read"}]
        phase = state.get("phase")
        if phase == "waiting_plan_confirmation":
            actions.append({"id": "approve_plan", "label": "确认方案", "kind": "approval"})
        if plan and plan.get("status") == "waiting_confirmation":
            actions.append({"id": "approve_tool_plan", "label": "确认并执行", "kind": "approval"})
        if plan and plan.get("status") == "approved":
            actions.append({"id": "execute_tool_plan", "label": "执行工具计划", "kind": "write"})
        if plan and plan.get("status") in {"failed", "waiting_approval"}:
            actions.append({"id": "repair_failed_plan", "label": "生成修复计划", "kind": "write"})
        if plan and plan.get("status") == "completed" and self._should_create_continuation_plan(plan)[0]:
            actions.append({"id": "continue_plan", "label": "继续推进需求", "kind": "write"})
        if state.get("sandbox"):
            actions.append({"id": "start_preview", "label": "启动沙盒预览", "kind": "command"})
        return actions

    def _guard_task_state_control(self, conversation_id: str, action: str) -> None:
        if action in {"refresh", "submit_requirement"}:
            return
        ledger = self.task_state_machine.read(conversation_id)
        if not ledger:
            return
        control = self._task_control_summary(ledger)
        paused_stage_ids = control.get("pausedStageIds", [])
        manual_action_ids = control.get("manualNextActionIds", [])
        controlled_actions = {"approve_plan", "approve_tool_plan", "execute_tool_plan", "repair_failed_plan", "continue_plan"}
        if paused_stage_ids and action in controlled_actions:
            stage_titles = self._stage_titles(ledger, paused_stage_ids)
            reason = f"任务状态机阶段已暂停：{', '.join(stage_titles)}。请先在右侧恢复阶段后继续。"
            self.events.append(
                conversation_id,
                "task_state.guard.blocked",
                {"action": action, "reason": reason, "pausedStageIds": paused_stage_ids},
                actor="runtime",
            )
            raise RuntimeError(reason)
        if manual_action_ids and action in controlled_actions and action not in manual_action_ids:
            reason = f"下一步动作已被用户覆盖为：{', '.join(manual_action_ids)}。当前动作 {action} 不在允许列表中。"
            self.events.append(
                conversation_id,
                "task_state.guard.blocked",
                {"action": action, "reason": reason, "manualNextActionIds": manual_action_ids},
                actor="runtime",
            )
            raise RuntimeError(reason)

    def _task_control_summary(self, ledger: dict[str, Any]) -> dict[str, list[str]]:
        controls = ledger.get("stageControls") if isinstance(ledger.get("stageControls"), dict) else {}
        override = ledger.get("nextActionOverride") if isinstance(ledger.get("nextActionOverride"), dict) else None
        paused = sorted(stage_id for stage_id, control in controls.items() if isinstance(control, dict) and control.get("paused"))
        manual = override.get("actionIds", []) if isinstance(override, dict) and isinstance(override.get("actionIds"), list) else []
        return {"pausedStageIds": [str(item) for item in paused], "manualNextActionIds": [str(item) for item in manual]}

    def _stage_titles(self, ledger: dict[str, Any], stage_ids: list[str]) -> list[str]:
        stages = ledger.get("stages") if isinstance(ledger.get("stages"), list) else []
        titles: list[str] = []
        for stage_id in stage_ids:
            stage = next((item for item in stages if isinstance(item, dict) and item.get("id") == stage_id), None)
            if stage:
                titles.append(f"{stage.get('title') or stage_id}({stage_id})")
            else:
                titles.append(stage_id)
        return titles

    def _plan_is_read_only(self, plan: dict[str, Any] | None) -> bool:
        """只读计划(搜索/读取/diff/仓库画像)走规则快速审计,不动用模型。"""
        if not plan:
            return False
        steps = [step for step in plan.get("steps", []) if isinstance(step, dict) and not step.get("disabled")]
        if not steps:
            return False
        return all(
            step.get("riskLevel") == "read" or step.get("toolId") == "github.inspect_repository"
            for step in steps
        )

    def _latest_blocked_role_audit(self, state: dict[str, Any], source: str) -> dict[str, Any] | None:
        for audit in reversed(state.get("audits", [])):
            if not isinstance(audit, dict):
                continue
            if audit.get("source") == source:
                return audit if audit.get("verdict") == "blocked" else None
        return None

    def _maybe_create_repair_plan(self, conversation_id: str, source_plan: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if not self._should_create_repair_plan(source_plan):
            return None, {
                "created": False,
                "reason": self._repair_stop_reason(source_plan),
                "sourcePlanId": source_plan.get("id"),
            }
        try:
            repair_plan = self._create_repair_plan(conversation_id, source_plan, trigger="auto")
            return repair_plan, {
                "created": True,
                "sourcePlanId": source_plan.get("id"),
                "repairPlanId": repair_plan.get("id"),
                "repairAttempt": repair_plan.get("repairAttempt"),
                "repairSequence": repair_plan.get("repairSequence"),
                "reason": "Verifier 判定失败后，后端 Orchestrator 已自动生成下一轮待确认修复计划。",
            }
        except Exception as error:
            self.events.append(
                conversation_id,
                "repair_loop.auto_create.failed",
                {"sourcePlanId": source_plan.get("id"), "error": str(error)},
                actor="agent",
            )
            return None, {
                "created": False,
                "sourcePlanId": source_plan.get("id"),
                "reason": str(error),
            }

    def _create_repair_plan(self, conversation_id: str, source_plan: dict[str, Any], trigger: str) -> dict[str, Any]:
        tools = self.tools.list()
        state = self.conversations.get(conversation_id)
        memory_snapshot = self.memory.snapshot(
            conversation_id,
            repository=state.get("repository") or source_plan.get("repository"),
            requirement=source_plan.get("requirement"),
        )
        draft = self.tool_plan_drafter.draft_repair(
            conversation_id=conversation_id,
            source_plan=source_plan,
            repository=source_plan.get("repository"),
            sandbox=source_plan.get("sandbox"),
            tools=tools,
            memory_snapshot=memory_snapshot,
        )
        plan = self.tool_call_plans.create_repair_plan(
            conversation_id,
            source_plan,
            tools,
            requested_steps=draft.get("steps") or None,
            generation={
                "source": "repair-loop",
                "rawResponse": draft.get("rawResponse"),
                "fallbackReason": draft.get("fallbackReason"),
                "summary": draft.get("summary"),
                "trigger": trigger,
            },
            audits=[draft["audit"]] if draft.get("audit") else [],
        )
        review = self.roles.review_tool_plan(
            plan, conversation_id, memory_snapshot=memory_snapshot, prefer_rules=self._plan_is_read_only(plan)
        )
        plan = self.tool_call_plans.append_audit(conversation_id, review, plan["id"])
        self.events.append(
            conversation_id,
            "agent.role.reviewer",
            {
                "verdict": review["verdict"],
                "summary": review.get("summary"),
                "recommendation": review.get("recommendation"),
                "findings": review["findings"],
                "planId": plan["id"],
                "repairOfPlanId": source_plan.get("id"),
                "repairAttempt": plan.get("repairAttempt"),
                "repairSequence": plan.get("repairSequence"),
                "repairPolicy": plan.get("repairPolicy"),
                "trigger": trigger,
            },
            actor="agent",
        )
        self.events.append(
            conversation_id,
            "repair_loop.plan.ready_for_confirmation",
            {
                "sourcePlanId": source_plan.get("id"),
                "repairPlanId": plan.get("id"),
                "repairAttempt": plan.get("repairAttempt"),
                "repairSequence": plan.get("repairSequence"),
                "trigger": trigger,
            },
            actor="agent",
        )
        return plan

    def _should_create_repair_plan(self, plan: dict[str, Any]) -> bool:
        has_failed_step = any(step.get("status") == "failed" for step in plan.get("steps", []) if isinstance(step, dict))
        if plan.get("status") != "failed" and not has_failed_step:
            return False
        policy = plan.get("repairPolicy") if isinstance(plan.get("repairPolicy"), dict) else {}
        if policy.get("requiresUserConfirmation") and not policy.get("autoAllowed"):
            return False
        max_total = int(policy.get("maxTotalRepairSteps") or 8)
        max_code = int(policy.get("maxCodeRepairAttempts") or 3)
        repair_sequence = int(plan.get("repairSequence") or 0)
        repair_attempt = int(plan.get("repairAttempt") or 0)
        if repair_sequence >= max_total:
            return False
        if policy.get("countsTowardCodeRepairLimit") and repair_attempt >= max_code:
            return False
        return True

    def _maybe_create_continuation_plan(
        self, conversation_id: str, source_plan: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        should, reason = self._should_create_continuation_plan(source_plan)
        if not should:
            return None, {"created": False, "reason": reason, "sourcePlanId": source_plan.get("id")}
        try:
            plan = self._create_continuation_plan(conversation_id, source_plan)
            return plan, {
                "created": True,
                "sourcePlanId": source_plan.get("id"),
                "continuationPlanId": plan.get("id"),
                "continuationSequence": plan.get("continuationSequence"),
                "reason": "上一轮计划已完成但需求尚未落地，已基于执行证据生成下一阶段待确认计划。",
            }
        except Exception as error:
            self.events.append(
                conversation_id,
                "continuation_loop.auto_create.failed",
                {"sourcePlanId": source_plan.get("id"), "error": str(error)},
                actor="agent",
            )
            return None, {"created": False, "sourcePlanId": source_plan.get("id"), "reason": str(error)}

    def _should_create_continuation_plan(self, plan: dict[str, Any]) -> tuple[bool, str]:
        if plan.get("status") != "completed":
            return False, "计划未完成，不进入推进循环。"
        steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
        if any(step.get("status") == "failed" for step in steps):
            return False, "存在失败步骤，由修复循环处理。"
        sequence = int(plan.get("continuationSequence") or 0)
        if sequence >= 4:
            return False, "推进轮次已达上限(4)，需要人工接管或重新提需求。"
        evidence = plan.get("evidence") if isinstance(plan.get("evidence"), dict) else {}
        wrote = any(
            step.get("toolId") in {"code.apply_patch", "code.write_file"} and step.get("status") == "completed"
            for step in steps
        ) or bool(evidence.get("checkpoints"))
        verifications = [item for item in evidence.get("verificationResults") or [] if isinstance(item, dict)]
        if not wrote:
            return True, "尚未产生代码改动，继续推进定位与写入。"
        if not verifications:
            return True, "已写入代码但还没有验证结果，继续推进验证。"
        # 同步进来的历史报告可能是旧的失败结果；以最近一次验证为准，未通过就继续。
        if not verifications[-1].get("ok"):
            return True, "已写入代码但最近一次验证未通过，继续推进修复与复验。"
        return False, "已有代码改动且最近验证通过，推进循环结束。"

    def _create_continuation_plan(self, conversation_id: str, source_plan: dict[str, Any]) -> dict[str, Any]:
        tools = self.tools.list()
        state = self.conversations.get(conversation_id)
        repository = state.get("repository") or source_plan.get("repository")
        sandbox = state.get("sandbox") or source_plan.get("sandbox")
        memory_snapshot = self.memory.snapshot(
            conversation_id,
            repository=repository,
            requirement=source_plan.get("requirement"),
            sandbox=sandbox,
        )
        matched_skills: list[dict[str, Any]] = []
        if self.skills:
            try:
                matched_skills = self.skills.peek(str(source_plan.get("requirement") or ""), repository)
            except Exception:
                matched_skills = []
        draft = self.tool_plan_drafter.draft_continuation(
            conversation_id=conversation_id,
            source_plan=source_plan,
            repository=repository,
            sandbox=sandbox,
            tools=tools,
            memory_snapshot=memory_snapshot,
            matched_skills=matched_skills,
        )
        if not draft.get("steps"):
            raise RuntimeError(str(draft.get("fallbackReason") or "推进计划没有可执行步骤。"))
        plan = self.tool_call_plans.create_plan(
            conversation_id=conversation_id,
            requirement=str(source_plan.get("requirement") or ""),
            repository=repository,
            sandbox=sandbox,
            tools=tools,
            requested_steps=draft.get("steps"),
            generation={
                "source": "continuation",
                "rawResponse": draft.get("rawResponse"),
                "fallbackReason": draft.get("fallbackReason"),
                "summary": draft.get("summary"),
            },
            audits=[draft["audit"]] if draft.get("audit") else [],
            continuation_of_plan_id=str(source_plan.get("id") or ""),
            continuation_sequence=int(source_plan.get("continuationSequence") or 0) + 1,
        )
        review = self.roles.review_tool_plan(
            plan, conversation_id, memory_snapshot=memory_snapshot, prefer_rules=self._plan_is_read_only(plan)
        )
        plan = self.tool_call_plans.append_audit(conversation_id, review, plan["id"])
        self.events.append(
            conversation_id,
            "agent.role.reviewer",
            {
                "verdict": review["verdict"],
                "summary": review.get("summary"),
                "recommendation": review.get("recommendation"),
                "findings": review["findings"],
                "planId": plan["id"],
                "continuationOfPlanId": source_plan.get("id"),
                "continuationSequence": plan.get("continuationSequence"),
            },
            actor="agent",
        )
        self.events.append(
            conversation_id,
            "continuation_loop.plan.ready_for_confirmation",
            {
                "sourcePlanId": source_plan.get("id"),
                "continuationPlanId": plan.get("id"),
                "continuationSequence": plan.get("continuationSequence"),
                "summary": draft.get("summary"),
            },
            actor="agent",
        )
        return plan

    def _repair_stop_reason(self, plan: dict[str, Any]) -> str:
        has_failed_step = any(step.get("status") == "failed" for step in plan.get("steps", []) if isinstance(step, dict))
        if plan.get("status") != "failed" and not has_failed_step:
            return "当前计划没有失败步骤，不需要生成修复计划。"
        policy = plan.get("repairPolicy") if isinstance(plan.get("repairPolicy"), dict) else {}
        if policy.get("requiresUserConfirmation") and not policy.get("autoAllowed"):
            return str(policy.get("reason") or "当前失败需要用户先处理权限、配置或需求澄清。")
        if int(plan.get("repairSequence") or 0) >= int(policy.get("maxTotalRepairSteps") or 8):
            return "自动修复已达到总链路上限，需要人工审查。"
        if policy.get("countsTowardCodeRepairLimit") and int(plan.get("repairAttempt") or 0) >= int(policy.get("maxCodeRepairAttempts") or 3):
            return "代码修复次数达到上限，需要人工审查。"
        return "当前失败暂不适合自动生成修复计划。"
