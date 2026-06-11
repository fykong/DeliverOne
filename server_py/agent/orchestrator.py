from __future__ import annotations

from typing import Any

from server_py.agent.role_agents import AgentRoleSuite
from server_py.agent.tool_call_plan import ToolCallPlanService
from server_py.agent.tool_plan_drafter import ToolPlanDrafter
from server_py.agent.workflow import AgentWorkflow
from server_py.conversations.store import ConversationStore
from server_py.core.json_io import now_iso
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
        ask_service: Any | None = None,
        preview_smoke: Any | None = None,
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
        self.ask_service = ask_service
        self.preview_smoke = preview_smoke

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
        preview_smoke: Any = None,
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
        self.conversations.record_milestone(
            conversation_id, "托管模式已开启：自动确认方案与工具计划，直达提测；澄清问题与高危操作仍会停下。"
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
            outcome = "已完成" if summary["finished"] else ("需要人工接管" if summary["needsHuman"] else "已结束")
            self.conversations.record_milestone(
                conversation_id,
                f"托管模式{outcome}（{summary['rounds']} 轮，阶段：{summary['stage']}）。{summary['reason'] or ''}",
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
                        # 推进上限触发的停止是"被迫停",不是"做完了"——
                        # 阅读量任务实测:前端没写完却报"已完成",必须如实交还人工。
                        if self._continuation_stopped_at_cap(executed):
                            summary.update(needsHuman=True, stage="continuation-cap", reason=f"需求可能尚未全部完成：{reason}")
                            return finish(bundle)
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
                    if self._continuation_stopped_at_cap(plan):
                        summary.update(needsHuman=True, stage="continuation-cap", reason=f"需求可能尚未全部完成：{reason}")
                        return finish(self._bundle(conversation_id))
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

        # 页面级终检（visual gate）：预览进程在跑时，用浏览器断言确认页面真的
        # 出现了需求要求的可见内容（文案/选择器），截图与 DOM 留证。
        # 结果记录进 summary 与事件流；没有预览进程时如实标记 skipped——
        # 完成判定不只靠"代码能跑通"，能看页面时就看页面。
        if preview_smoke is not None:
            summary["visualGate"] = self._run_visual_gate(conversation_id, requirement, preview_smoke)

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
                    self.memory.record_solution(
                        conversation_id,
                        state.get("repository"),
                        requirement,
                        [str(item.get("path") if isinstance(item, dict) else item) for item in report.get("changedFiles", [])][:12],
                        f"托管交付：终检与验证门禁通过（{summary['rounds']} 轮）",
                        branch=record.get("branch"),
                        commit_sha=record.get("commitSha"),
                    )
                else:
                    summary["reason"] += "（验证门禁未通过，已生成交付包但未自动提测。）"
            except Exception as error:
                summary["reason"] += f"（交付产出失败：{error}）"

        return finish(self._bundle(conversation_id))

    def _run_visual_gate(self, conversation_id: str, requirement: str, preview_smoke: Any) -> dict[str, Any]:
        running = [
            process
            for process in self.processes.list()
            if process.get("conversationId") == conversation_id and process.get("status") == "running"
        ]
        if not running:
            return {
                "status": "skipped",
                "reason": "当前没有运行中的沙盒预览进程；完成判定基于真实单测与交付终检。先启动预览再跑任务即可启用页面级确认。",
            }
        try:
            from server_py.agent.preview_assertions import build_preview_assertions

            hints = build_preview_assertions(requirement, None)
            ports = running[0].get("ports") or [3000]
            self.events.append(conversation_id, "autopilot.visual_gate.begin", {"port": ports[0]}, actor="autopilot")
            report = preview_smoke.run(
                conversation_id,
                int(ports[0]),
                "/",
                timeout_seconds=45,
                expected_texts=[str(item) for item in hints.get("expectedTexts", [])],
                required_selectors=[str(item) for item in hints.get("requiredSelectors", [])],
            )
            assertions = report.get("assertions") if isinstance(report.get("assertions"), dict) else {}
            gate = {
                "status": "pass" if report.get("ok") else "fail",
                "summary": str(report.get("summary"))[:300],
                "assertions": assertions,
                "screenshotPath": (report.get("screenshot") or {}).get("path") if isinstance(report.get("screenshot"), dict) else None,
                "reportPath": report.get("reportPath"),
            }
            self.events.append(
                conversation_id,
                "autopilot.visual_gate.end",
                {"status": gate["status"], "summary": gate["summary"]},
                actor="autopilot",
            )
            return gate
        except Exception as error:
            return {"status": "error", "reason": f"页面级终检执行失败：{error}"}

    def _try_autostart_preview(self, conversation_id: str, plan: dict[str, Any]) -> dict[str, Any] | None:
        """写入后预览没在跑时自动启动(依赖已装好才启动,否则等不起)。"""
        import socket
        import time as _time
        from pathlib import Path as _Path

        sandbox = plan.get("sandbox") or self.conversations.get(conversation_id).get("sandbox")
        if not isinstance(sandbox, dict) or not sandbox.get("repoPath"):
            return None
        repo_root = _Path(str(sandbox["repoPath"]))
        if not (repo_root / "node_modules").exists():
            return None  # 首次安装要几分钟,不在验证环节里等
        try:
            from server_py.verification.stack_detector import StackDetector

            primary = (StackDetector().recommend_for_path(str(repo_root)).get("preview") or {}).get("primary") or {}
            command = str(primary.get("command") or "").strip()
            ports = [int(p) for p in (primary.get("ports") or [4500])]
            if not command:
                return None
            process = self.processes.start(
                conversation_id=conversation_id,
                sandbox_id=str(sandbox.get("id") or ""),
                command=command,
                cwd=str(repo_root),
                ports=ports,
            )
            self.events.append(
                conversation_id, "verification.visual.autostart", {"command": command, "ports": ports}, actor="runtime"
            )
            deadline = _time.time() + 60
            while _time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", ports[0]), timeout=2):
                        return {"ports": ports, "id": process.get("id"), "status": "running"}
                except OSError:
                    _time.sleep(2)
            return None
        except Exception:
            return None

    def _auto_visual_check_after_writes(self, conversation_id: str, plan: dict[str, Any]) -> bool:
        """计划写入过代码且预览在运行时,自动做页面级确认(截图+DOM+需求断言)。"""
        if not self.preview_smoke:
            return False
        wrote = any(
            isinstance(step, dict)
            and step.get("toolId") in {"code.apply_patch", "code.write_file"}
            and step.get("status") == "completed"
            for step in plan.get("steps", [])
        )
        if not wrote:
            return False
        already_checked = any(
            isinstance(step, dict) and step.get("toolId") == "browser.preview_smoke"
            for step in plan.get("steps", [])
        )
        if already_checked:
            return False
        running = [
            process
            for process in self.processes.list()
            if process.get("conversationId") == conversation_id
            and process.get("status") == "running"
            and process.get("ports")
        ]
        if not running:
            # 豆包终判必须"看到真实页面":预览没在跑就自动拉起来,
            # 而不是跳过视觉检查(阅读量任务实测:跳过=半成品被放行)。
            started = self._try_autostart_preview(conversation_id, plan)
            if started:
                running = [started]
            else:
                self.events.append(
                    conversation_id,
                    "verification.visual.skipped",
                    {"reason": "沙盒预览未运行且自动启动失败(通常是依赖未安装);手动启动预览后,每次代码写入会自动做页面级确认。"},
                    actor="runtime",
                )
                return False
        try:
            from server_py.agent.preview_assertions import build_preview_assertions

            hints = build_preview_assertions(str(plan.get("requirement") or ""), None)
            port = int(running[0]["ports"][0])
            self.events.append(conversation_id, "verification.visual.begin", {"port": port}, actor="runtime")
            report = self.preview_smoke.run(
                conversation_id,
                port,
                "/",
                timeout_seconds=45,
                expected_texts=[str(item) for item in hints.get("expectedTexts", [])],
                required_selectors=[str(item) for item in hints.get("requiredSelectors", [])],
            )
            self.events.append(
                conversation_id,
                "verification.visual.end",
                {"ok": bool(report.get("ok")), "summary": str(report.get("summary"))[:200]},
                actor="runtime",
            )
            return True
        except Exception as error:
            self.events.append(
                conversation_id,
                "verification.visual.failed",
                {"error": str(error)},
                actor="runtime",
            )
            return False

    def _answer_as_conversation(self, conversation_id: str, user_input: str, source: str) -> dict[str, Any]:
        self.events.append(
            conversation_id,
            "ask.auto_routed",
            {"source": source, "input": user_input[:200]},
            actor="runtime",
        )
        result = self.ask_service.answer(conversation_id, user_input)
        state = self.conversations.get(conversation_id)
        stamp = now_iso()
        state.setdefault("messages", []).append(
            {"id": f"msg_ask_{stamp}", "role": "user", "content": user_input, "createdAt": stamp}
        )
        state["messages"].append(
            {"id": f"msg_ans_{stamp}", "role": "agent", "content": result["reply"], "createdAt": stamp}
        )
        self.conversations.save(state)
        return {"ask": result}

    def _merge_clarification_answer(self, conversation_id: str, user_input: str) -> tuple[str, bool]:
        """用户对澄清追问的简短回答(编号/选项/补充),确定性合并回原始需求。"""
        state = self.conversations.get(conversation_id)
        turns = state.get("turns") if isinstance(state.get("turns"), list) else []
        last_turn = turns[-1] if turns else None
        if not isinstance(last_turn, dict) or last_turn.get("phase") != "clarification":
            return user_input, False
        if len(user_input) >= 200:
            # 长文本视为用户主动重述的完整需求,尊重原文。
            return user_input, False
        original = str(state.get("lastRequirement") or "").strip()
        if not original or original == user_input:
            return user_input, False
        questions: list[str] = []
        for audit in reversed(state.get("audits", [])):
            if isinstance(audit, dict) and audit.get("source") == "Clarifier" and audit.get("questions"):
                questions = [str(item) for item in audit.get("questions", [])][:6]
                break
        lines = ["原始需求：", original, ""]
        if questions:
            lines.append("上一轮澄清问题：")
            lines.extend(f"{index}. {question}" for index, question in enumerate(questions, start=1))
            lines.append("")
        lines.extend(
            [
                "用户对澄清问题的回答：",
                user_input,
                "",
                "请将回答合并进原始需求，作为一份完整需求来理解和执行；回答中的编号/选项对应上面的澄清问题。",
            ]
        )
        return "\n".join(lines), True

    def _autopilot_title(self, requirement: str) -> str:
        first_line = (requirement.splitlines() or [""])[0].strip()
        return first_line[:72] or "DeliverOne 托管交付"

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

        if action == "ask":
            question = (requirement or "").strip()
            if not question:
                raise RuntimeError("问题不能为空。")
            if not self.ask_service:
                raise RuntimeError("对话服务未配置。")
            self.events.append(conversation_id, "ask.message", {"content": question[:400]}, actor="user")
            result = self.ask_service.answer(conversation_id, question)
            # 对话不写入交付状态机,只追加到消息流,保持会话可回看。
            state = self.conversations.get(conversation_id)
            stamp = now_iso()
            state.setdefault("messages", []).append(
                {"id": f"msg_ask_{stamp}", "role": "user", "content": question, "createdAt": stamp}
            )
            state["messages"].append(
                {"id": f"msg_ans_{stamp}", "role": "agent", "content": result["reply"], "createdAt": stamp}
            )
            self.conversations.save(state)
            self.events.append(conversation_id, "ask.answer", {"modelSource": result.get("modelSource")}, actor="agent")
            return {"ask": result}

        if action == "submit_requirement":
            raw_input_text = (requirement or "").strip()
            if not raw_input_text:
                raise RuntimeError("需求不能为空。")
            # 意图判断完全交给模型(Clarifier 输出 inputIntent),不做关键词硬编码:
            # 平台的理念就是让模型自己判断,枚举不可能覆盖所有情况。
            # 上一轮是澄清追问时,用户可能只回编号或简短答案;确定性合并
            # 「原始需求+澄清问题+用户回答」,不依赖模型自行从记忆拼装。
            next_requirement, merged_from_clarification = self._merge_clarification_answer(
                conversation_id, raw_input_text
            )
            if merged_from_clarification:
                self.events.append(
                    conversation_id,
                    "clarification.answer.merged",
                    {"answer": raw_input_text[:300], "mergedChars": len(next_requirement)},
                    actor="runtime",
                )
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
            display_message = raw_input_text if merged_from_clarification else None
            # 用户输入是提问/闲聊而非开发需求时,自动转对话回答——
            # 用户不需要知道"提问"按钮的存在,发送给 Agent 也能自然对话。
            intent = str(clarification.get("inputIntent") or "development")
            if intent in {"question", "chitchat"} and self.ask_service:
                self.conversations.record_audit(conversation_id, clarification)
                return self._answer_as_conversation(conversation_id, raw_input_text, source=f"clarifier:{intent}")
            if clarification.get("verdict") == "blocked":
                # 需求不可执行时短路：不调用规划模型，直接把追问作为 Agent 回复送回对话。
                turn = self.workflow.clarification_turn(
                    conversation_id, next_requirement, repository, sandbox, clarification,
                    display_message=display_message,
                )
            else:
                turn = self.workflow.plan(
                    conversation_id, next_requirement, repository, sandbox, display_message=display_message
                )
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

            # lastRequirement 优先:它存的是澄清合并后的完整需求；approve_plan 时
            # 前端可能带上输入框残留的短回答,绝不能用它覆盖已合并的需求。
            plan_requirement = (state.get("lastRequirement") or requirement or "").strip()
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
            # 改完代码亲眼看运行结果:有运行中的预览时自动跑页面级 smoke,
            # 截图/DOM/需求断言进入证据,Verifier 据实判断而非"自认为完成"。
            if self._auto_visual_check_after_writes(conversation_id, plan):
                synced_plan = self.tool_call_plans.sync_latest_reports(conversation_id, plan["id"])
                if synced_plan:
                    plan = synced_plan
            verification_memory = self.memory.snapshot(
                conversation_id,
                repository=plan.get("repository"),
                requirement=plan.get("requirement"),
            )
            # 只读快审仅限"写入前的侦察":一旦会话里已有代码写入(存在 checkpoint),
            # 后续哪怕是只读复查也必须走模型完整验证——否则 requirementCompleted
            # 判断在收尾阶段消失,推进循环只能盲转到上限(阅读量任务实测踩过)。
            recon_only = self._plan_is_read_only(plan) and not self.checkpoints.list(conversation_id)
            verification = self.roles.verify_execution(
                plan, conversation_id, memory_snapshot=verification_memory, prefer_rules=recon_only
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
            # 先决定下一步(修复/推进/闭环),再让模型把整轮执行+下一步
            # 叙述成一段第一人称工作日志——碎片化的一句话里程碑对 PM 没有
            # 信息量。叙述持久化到消息流,模型不可用时回退确定性文本。
            steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
            done_count = sum(1 for step in steps if step.get("status") == "completed")
            failed_count = sum(1 for step in steps if step.get("status") == "failed")
            verdict_label = {"pass": "通过", "warning": "有风险，需审查", "blocked": "未通过，需要修复"}.get(
                str(verification.get("verdict")), str(verification.get("verdict"))
            )
            repair_plan, repair_loop = self._maybe_create_repair_plan(conversation_id, plan)
            continuation_plan, continuation_loop = (None, {"created": False}) if repair_plan else self._maybe_create_continuation_plan(
                conversation_id, plan
            )
            if repair_plan:
                loop_note = (
                    f"系统已自动生成修复计划 #{repair_plan.get('repairSequence')}"
                    f"（{len(repair_plan.get('steps') or [])} 步），等待用户在右侧确认执行。"
                )
            elif continuation_plan:
                loop_note = f"需求尚未完成，系统已生成推进计划（{len(continuation_plan.get('steps') or [])} 步），等待用户确认执行。"
            else:
                loop_note = str(continuation_loop.get("reason") or "本轮执行闭环结束。")
            fallback_text = (
                f"工具计划执行结束：{done_count} 步完成、{failed_count} 步失败。"
                f"Verifier：{verdict_label}。{verification.get('summary') or ''}\n{loop_note}"
            )
            narrative = self.roles.narrate_execution(plan, verification, loop_note, conversation_id) or fallback_text
            self.conversations.record_milestone(conversation_id, narrative)
            if repair_plan:
                return {
                    "tool_plan": repair_plan,
                    "executed_tool_plan": plan,
                    "repair_plan": repair_plan,
                    "repair_loop": repair_loop,
                    "narrative": narrative,
                }
            if continuation_plan:
                return {
                    "tool_plan": continuation_plan,
                    "executed_tool_plan": plan,
                    "repair_loop": repair_loop,
                    "continuation_loop": continuation_loop,
                    "narrative": narrative,
                }
            return {
                "tool_plan": plan,
                "executed_tool_plan": plan,
                "repair_loop": repair_loop,
                "continuation_loop": continuation_loop,
                "narrative": narrative,
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
            if source_plan.get("status") not in {"completed", "failed"}:
                raise RuntimeError("工具计划还在执行或等待确认，暂时不能推进。")
            # 用户手动点「继续推进」就是明确指令,不再用自动循环的终止判定拦它——
            # 环境修复产生的 diff + 验证绿会骗过机械判定,而用户看得到需求没完成。
            plan = self._create_continuation_plan(conversation_id, source_plan)
            self.conversations.record_milestone(
                conversation_id,
                f"已按用户指令生成推进计划（{len(plan.get('steps') or [])} 步），等待确认执行。",
            )
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
        ask: dict[str, Any] | None = None,
        narrative: str | None = None,
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
            "ask": ask,
            "narrative": narrative,
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
        if action in {"refresh", "submit_requirement", "ask"}:
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

    # 推进循环轮次上限:防自动循环失控的安全阀。到限即交还人工,
    # 不是质量判断——质量判断由 Verifier 的 requirementCompleted 负责。
    CONTINUATION_MAX_ROUNDS = 4

    def _continuation_stopped_at_cap(self, plan: dict[str, Any]) -> bool:
        """推进停止是否因轮次耗尽(被迫停)而非需求完成(自然停)。"""
        return int(plan.get("continuationSequence") or 0) >= self.CONTINUATION_MAX_ROUNDS

    def _should_create_continuation_plan(self, plan: dict[str, Any]) -> tuple[bool, str]:
        if plan.get("status") != "completed":
            return False, "计划未完成，不进入推进循环。"
        steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
        if any(step.get("status") == "failed" for step in steps):
            return False, "存在失败步骤，由修复循环处理。"
        sequence = int(plan.get("continuationSequence") or 0)
        if sequence >= self.CONTINUATION_MAX_ROUNDS:
            # 注意:这是"被迫停"不是"做完了"。调用方必须用 _continuation_stop_kind
            # 区分,绝不能解析这段中文文案。
            return False, f"推进轮次已达上限({self.CONTINUATION_MAX_ROUNDS})，需要人工接管或重新提需求。"
        # 优先采信 Verifier 对"需求是否真正落地"的模型判断:环境修复(装依赖、
        # 改 package.json)也会产生 diff 并让验证变绿,机械判定会在需求还没做时
        # 就宣布完成——这正是"自己认为完成就完成"的反例。
        verifier = next(
            (
                audit
                for audit in reversed(plan.get("audits") or [])
                if isinstance(audit, dict) and audit.get("source") == "Verifier"
            ),
            None,
        )
        if verifier and verifier.get("requirementCompleted") is False:
            return True, "Verifier 判断核心需求尚未落地，继续推进定位与写入。"
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
        # 宣布"完成"必须拿到模型的显式 True:requirementCompleted 为 None
        # (验证走了规则回退/模型解析失败/老审计)时,机械的"有 diff+验证绿"
        # 不足以证明需求落地——审计实锤过 None 漏洞会把半成品放行。
        if not verifier or verifier.get("requirementCompleted") is not True:
            return True, "缺少 Verifier 对需求完成度的显式确认，继续推进一轮复核验证。"
        return False, "已有代码改动、验证通过且 Verifier 确认需求已落地，推进循环结束。"

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
