from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from server_py.agent.preview_assertions import build_preview_assertions, merge_preview_assertions
from server_py.conversations.store import ConversationStore
from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import conversation_root
from server_py.memory.memory_service import MemoryService
from server_py.runtime.events import EventStore
from server_py.tools.types import ToolContext, ToolRunner


PLAN_FILE = "tool-call-plan.json"
SOURCE_FILE_EXTENSIONS = (
    ".css",
    ".html",
    ".js",
    ".jsx",
    ".mjs",
    ".py",
    ".ts",
    ".tsx",
    ".vue",
    ".yml",
    ".yaml",
)
DEFAULT_REPAIR_POLICY = {
    "failureClass": "unknown",
    "severity": "major",
    "autoAllowed": True,
    "countsTowardCodeRepairLimit": False,
    "requiresUserConfirmation": False,
    "maxCodeRepairAttempts": 3,
    "maxTotalRepairSteps": 8,
    "reason": "按保守修复策略继续读取证据并重新验证。",
}


class ToolCallPlanService:
    """Reviewable tool plan with Codex-inspired checkpoints and repair loop."""

    def __init__(self, events: EventStore, conversations: ConversationStore, memory: MemoryService) -> None:
        self.events = events
        self.conversations = conversations
        self.memory = memory

    def create_plan(
        self,
        conversation_id: str,
        requirement: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        tools: list[dict[str, Any]],
        requested_steps: list[dict[str, Any]] | None = None,
        generation: dict[str, Any] | None = None,
        audits: list[dict[str, Any]] | None = None,
        repair_of_plan_id: str | None = None,
        repair_attempt: int | None = None,
        repair_sequence: int | None = None,
        repair_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool_map = {tool["id"]: tool for tool in tools}
        steps = self._normalize_requested_steps(requested_steps or [], tool_map)
        if not steps:
            steps = self._default_steps(requirement, repository, tool_map)
        steps = self._enrich_preview_assertion_steps(steps, requirement)

        plan = {
            "id": f"plan_{uuid4().hex[:10]}",
            "conversationId": conversation_id,
            "requirement": requirement,
            "status": "waiting_confirmation",
            "repository": repository,
            "sandbox": sandbox,
            "steps": steps,
            "evidence": {
                "checkpoints": [],
                "diffFiles": [],
                "verificationResults": [],
                "previewResults": [],
                "toolResults": [],
            },
            "generation": generation or {"source": "heuristic", "fallbackReason": None},
            "audits": audits or [],
            "reusedCodexMechanisms": [
                "ExecPolicy decision gate",
                "sandbox-scoped tool execution",
                "checkpoint-before-write",
                "tool begin/end event stream",
                "Verifier-driven repair loop",
            ],
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
        }
        if repair_of_plan_id:
            plan["repairOfPlanId"] = repair_of_plan_id
        if repair_attempt is not None:
            plan["repairAttempt"] = repair_attempt
        if repair_sequence is not None:
            plan["repairSequence"] = repair_sequence
        if repair_policy:
            plan["repairPolicy"] = repair_policy

        self._save(plan)
        self.conversations.record_tool_call_plan(conversation_id, plan)
        self.events.append(conversation_id, "tool_plan.created", {"planId": plan["id"], "stepCount": len(steps)}, actor="agent")
        return plan

    def get_plan(self, conversation_id: str) -> dict[str, Any] | None:
        return read_json(conversation_root(conversation_id) / PLAN_FILE, None)

    def sync_latest_reports(self, conversation_id: str, plan_id: str | None = None) -> dict[str, Any] | None:
        try:
            plan = self._require_plan(conversation_id, plan_id)
        except RuntimeError:
            return None

        root = conversation_root(conversation_id)
        changed = False
        verification_report = read_json(root / "delivery" / "verification-report.json", None)
        if isinstance(verification_report, dict):
            changed = self._append_verification_report(plan, verification_report, "manual-verification") or changed
        preview_report = read_json(root / "preview" / "smoke-report.json", None)
        if isinstance(preview_report, dict):
            changed = self._append_preview_report(plan, preview_report, "manual-preview") or changed
        if not changed:
            return plan

        plan["updatedAt"] = now_iso()
        self._save(plan)
        self.conversations.record_tool_call_plan(conversation_id, plan)
        self.events.append(
            conversation_id,
            "tool_plan.evidence.synced",
            {
                "planId": plan.get("id"),
                "verificationResults": len(plan.get("evidence", {}).get("verificationResults", [])),
                "previewResults": len(plan.get("evidence", {}).get("previewResults", [])),
            },
            actor="runtime",
        )
        return plan

    def append_audit(self, conversation_id: str, audit: dict[str, Any], plan_id: str | None = None) -> dict[str, Any]:
        plan = self._require_plan(conversation_id, plan_id)
        plan.setdefault("audits", []).append(audit)
        if audit.get("source") == "Verifier":
            if audit.get("repairPolicy"):
                plan["repairPolicy"] = audit["repairPolicy"]
            if audit.get("failureClass"):
                plan["failureClass"] = audit["failureClass"]
            if audit.get("repairScope"):
                plan["repairScope"] = audit["repairScope"]
        plan["updatedAt"] = now_iso()
        self._save(plan)
        self.conversations.record_tool_call_plan(conversation_id, plan)
        self.conversations.record_audit(conversation_id, audit)
        return plan

    def approve_plan(self, conversation_id: str, plan_id: str | None = None) -> dict[str, Any]:
        plan = self._require_plan(conversation_id, plan_id)
        if plan["status"] not in {"waiting_confirmation", "approved"}:
            raise RuntimeError(f"当前计划状态不能确认：{plan['status']}")
        blocked_review = self._latest_blocked_review(plan)
        if blocked_review:
            title = blocked_review.get("summary") or "Reviewer 阻断了当前工具计划。"
            raise RuntimeError(f"{title} 请重新生成计划或调整后再确认。")
        plan["status"] = "approved"
        plan["approvedAt"] = now_iso()
        plan["updatedAt"] = now_iso()
        self._save(plan)
        self.conversations.record_tool_call_plan(conversation_id, plan)
        self.events.append(conversation_id, "tool_plan.approved", {"planId": plan["id"]}, actor="user")
        return plan

    def edit_plan(
        self,
        conversation_id: str,
        operation: str,
        plan_id: str | None = None,
        step_id: str | None = None,
        reason: str | None = None,
        title: str | None = None,
        purpose: str | None = None,
        input_payload: dict[str, Any] | None = None,
        target_order: int | None = None,
    ) -> dict[str, Any]:
        plan = self._require_plan(conversation_id, plan_id)
        if plan["status"] == "running":
            raise RuntimeError("工具计划正在执行，不能编辑。")
        if plan["status"] == "completed":
            raise RuntimeError("工具计划已经完成，不能继续编辑。")
        if not step_id:
            raise RuntimeError("编辑工具计划需要 stepId。")

        op = operation.strip()
        step = self._require_step(plan, step_id)
        before = self._step_edit_snapshot(step)

        if op == "skip_step":
            if step.get("status") in {"running", "completed"}:
                raise RuntimeError("运行中或已完成的步骤不能禁用。")
            step["status"] = "skipped"
            step["disabled"] = True
            step["disabledReason"] = reason or "用户在审查工具计划时禁用了该步骤。"
        elif op == "restore_step":
            if step.get("status") != "skipped":
                raise RuntimeError("只有已禁用步骤可以恢复。")
            step["status"] = "pending"
            step["disabled"] = False
            step.pop("disabledReason", None)
        elif op == "update_step":
            if step.get("status") in {"running", "completed"}:
                raise RuntimeError("运行中或已完成的步骤不能修改。")
            if title is not None:
                step["title"] = title.strip() or step["title"]
            if purpose is not None:
                step["purpose"] = purpose.strip()
            if input_payload is not None:
                step["input"] = input_payload
        elif op == "move_step":
            if target_order is None:
                raise RuntimeError("移动步骤需要 targetOrder。")
            self._move_step(plan, step_id, target_order)
        else:
            raise RuntimeError(f"不支持的工具计划编辑操作：{operation}")

        step["updatedAt"] = now_iso()
        edit_record = {
            "operation": op,
            "stepId": step_id,
            "reason": reason,
            "before": before,
            "after": self._step_edit_snapshot(step),
            "createdAt": now_iso(),
        }
        plan.setdefault("editHistory", []).append(edit_record)
        plan["status"] = "waiting_confirmation" if plan.get("status") in {"approved", "failed", "waiting_approval"} else plan.get("status")
        plan["updatedAt"] = now_iso()
        self._save(plan)
        self.conversations.record_tool_call_plan(conversation_id, plan)
        self.events.append(conversation_id, "tool_plan.edited", {"planId": plan["id"], **edit_record}, actor="user")
        return plan

    def rewrite_plan(
        self,
        conversation_id: str,
        tools: list[dict[str, Any]],
        requested_steps: list[dict[str, Any]],
        instruction: str,
        generation: dict[str, Any] | None = None,
        audits: list[dict[str, Any]] | None = None,
        plan_id: str | None = None,
    ) -> dict[str, Any]:
        plan = self._require_plan(conversation_id, plan_id)
        if plan["status"] == "running":
            raise RuntimeError("工具计划正在执行，不能重写。")
        if plan["status"] == "completed":
            raise RuntimeError("工具计划已经完成，不能重写。")
        if not instruction.strip():
            raise RuntimeError("重写工具计划需要用户修改意见。")

        tool_map = {tool["id"]: tool for tool in tools}
        steps = self._normalize_requested_steps(requested_steps, tool_map)
        if not steps:
            raise RuntimeError("模型没有返回可执行的工具步骤，计划保持不变。")
        steps = self._enrich_preview_assertion_steps(steps, plan.get("requirement", ""))
        before = {
            "stepCount": len(plan.get("steps", [])),
            "steps": [self._step_edit_snapshot(step) for step in plan.get("steps", []) if isinstance(step, dict)],
        }
        plan["steps"] = steps
        plan["status"] = "waiting_confirmation"
        plan["generation"] = generation or {"source": "rewrite", "summary": instruction}
        plan.setdefault("audits", []).extend(audits or [])
        edit_record = {
            "operation": "rewrite_plan",
            "stepId": None,
            "reason": instruction.strip(),
            "before": before,
            "after": {
                "stepCount": len(steps),
                "steps": [self._step_edit_snapshot(step) for step in steps],
            },
            "createdAt": now_iso(),
        }
        plan.setdefault("editHistory", []).append(edit_record)
        plan["updatedAt"] = now_iso()
        self._save(plan)
        self.conversations.record_tool_call_plan(conversation_id, plan)
        self.events.append(
            conversation_id,
            "tool_plan.rewritten",
            {"planId": plan["id"], "instruction": instruction.strip(), "stepCount": len(steps), "generation": plan["generation"]},
            actor="agent",
        )
        self.events.append(conversation_id, "tool_plan.edited", {"planId": plan["id"], **edit_record}, actor="user")
        return plan

    def create_repair_plan(
        self,
        conversation_id: str,
        source_plan: dict[str, Any],
        tools: list[dict[str, Any]],
        requested_steps: list[dict[str, Any]] | None = None,
        generation: dict[str, Any] | None = None,
        audits: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        failed_steps = [step for step in source_plan.get("steps", []) if isinstance(step, dict) and step.get("status") == "failed"]
        if source_plan.get("status") not in {"failed", "waiting_approval"} and not failed_steps:
            raise RuntimeError("当前工具计划没有失败步骤，不能生成修复计划。")

        policy = self._latest_repair_policy(source_plan)
        self._guard_repair_policy(conversation_id, source_plan, policy)

        repair_sequence = int(source_plan.get("repairSequence") or 0) + 1
        previous_code_attempt = int(source_plan.get("repairAttempt") or 0)
        counts_code = bool(policy.get("countsTowardCodeRepairLimit"))
        repair_attempt = previous_code_attempt + (1 if counts_code else 0)
        failure_text = self._failure_text(failed_steps)
        failed_summary = self._failed_summary(failed_steps)
        repair_steps = requested_steps or self._default_repair_steps(source_plan, failed_summary, policy, tools)
        repair_steps = self._ensure_failure_context_steps(repair_steps, source_plan, failure_text, tools)
        repair_steps = self._ensure_repair_verification_step(repair_steps, source_plan)
        repair_steps = self._ensure_repair_preview_step(repair_steps, source_plan, tools)

        plan = self.create_plan(
            conversation_id=conversation_id,
            requirement=f"第 {repair_sequence} 次修复上一轮失败：{failed_summary}",
            repository=source_plan.get("repository"),
            sandbox=source_plan.get("sandbox"),
            tools=tools,
            requested_steps=repair_steps,
            generation=generation
            or {
                "source": "repair-loop",
                "fallbackReason": "失败后生成确定性修复诊断计划。",
                "summary": policy.get("reason"),
            },
            audits=audits or [],
            repair_of_plan_id=source_plan.get("id"),
            repair_attempt=repair_attempt,
            repair_sequence=repair_sequence,
            repair_policy=policy,
        )
        plan["repairSource"] = self._repair_source_summary(source_plan, failed_steps, failed_summary, policy)
        plan["updatedAt"] = now_iso()
        self._save(plan)
        self.conversations.record_tool_call_plan(conversation_id, plan)
        self.events.append(
            conversation_id,
            "repair_loop.plan.created",
            {
                "sourcePlanId": source_plan.get("id"),
                "repairPlanId": plan["id"],
                "repairAttempt": repair_attempt,
                "repairSequence": repair_sequence,
                "failureClass": policy.get("failureClass"),
                "countsTowardCodeRepairLimit": counts_code,
                "failedStepCount": len(failed_steps),
            },
            actor="agent",
        )
        return plan

    def execute_plan(self, conversation_id: str, tools: ToolRunner, plan_id: str | None = None) -> dict[str, Any]:
        plan = self._require_plan(conversation_id, plan_id)
        if plan["status"] not in {"approved", "running", "waiting_approval"}:
            raise RuntimeError("工具调用计划必须先由用户确认。")
        sandbox = plan.get("sandbox")
        if not sandbox:
            raise RuntimeError("工具调用计划缺少沙盒，不能执行。")

        plan["status"] = "running"
        plan["startedAt"] = plan.get("startedAt") or now_iso()
        plan["updatedAt"] = now_iso()
        self._save(plan)
        self.events.append(conversation_id, "tool_plan.execution.begin", {"planId": plan["id"], "stepCount": len(plan["steps"])}, actor="runtime")

        context = ToolContext(
            conversation_id=conversation_id,
            sandbox_id=sandbox["id"],
            repo_path=sandbox["repoPath"],
            user_initiated=True,
        )

        for step in plan["steps"]:
            if step.get("status") == "completed":
                continue
            if step.get("status") == "skipped":
                self.events.append(
                    conversation_id,
                    "tool_plan.step.skipped",
                    {"planId": plan["id"], "stepId": step["id"], "title": step.get("title"), "reason": step.get("disabledReason")},
                    actor="runtime",
                )
                continue
            if step.get("status") not in {"pending", "failed", "waiting_approval"}:
                continue
            self._execute_step(plan, step, tools, context)
            self._save(plan)
            self.conversations.record_tool_call_plan(conversation_id, plan)
            if step["status"] in {"failed", "waiting_approval"}:
                plan["status"] = step["status"]
                plan["updatedAt"] = now_iso()
                self._save(plan)
                self.events.append(
                    conversation_id,
                    "tool_plan.execution.paused",
                    {"planId": plan["id"], "stepId": step["id"], "status": step["status"]},
                    actor="runtime",
                )
                return plan

        plan["status"] = "completed"
        plan["completedAt"] = now_iso()
        plan["updatedAt"] = now_iso()
        self._save(plan)
        self.conversations.record_tool_call_plan(conversation_id, plan)
        self.memory.record_decision(conversation_id, "工具计划已执行", f"计划 {plan['id']} 已完成 {len(plan['steps'])} 个步骤。")
        self.events.append(conversation_id, "tool_plan.execution.end", {"planId": plan["id"], "status": plan["status"]}, actor="runtime")
        return plan

    def _execute_step(self, plan: dict[str, Any], step: dict[str, Any], tools: ToolRunner, context: ToolContext) -> None:
        conversation_id = plan["conversationId"]
        step["status"] = "running"
        step["startedAt"] = now_iso()
        step["updatedAt"] = now_iso()
        self.events.append(
            conversation_id,
            "tool_plan.step.begin",
            {"planId": plan["id"], "stepId": step["id"], "toolId": step["toolId"], "title": step["title"]},
            actor="runtime",
        )

        payload = dict(step.get("input") or {})
        if step.get("requiresApproval"):
            payload["approved"] = True

        step_context = ToolContext(
            conversation_id=context.conversation_id,
            sandbox_id=context.sandbox_id,
            repo_path=context.repo_path,
            plan_id=plan["id"],
            step_id=step["id"],
            sandbox_mode=context.sandbox_mode,
            approval_mode=context.approval_mode,
            user_initiated=context.user_initiated,
        )
        result = tools.run(step["toolId"], payload, step_context)
        step["result"] = result
        step["summary"] = result.get("summary", "")
        step["updatedAt"] = now_iso()

        if result.get("needsApproval"):
            step["status"] = "waiting_approval"
            self.memory.record_failure(conversation_id, f"工具步骤等待审批：{step['title']}", result.get("summary", "需要用户审批。"), "tool-plan")
        elif result.get("ok"):
            step["status"] = "completed"
            step["completedAt"] = now_iso()
        else:
            step["status"] = "failed"
            step["completedAt"] = now_iso()
            self.memory.record_failure(conversation_id, f"工具步骤失败：{step['title']}", result.get("summary", "工具调用失败。"), "tool-plan")

        self._merge_evidence(plan, step, result)
        self.events.append(
            conversation_id,
            "tool_plan.step.end",
            {"planId": plan["id"], "stepId": step["id"], "toolId": step["toolId"], "status": step["status"], "summary": step["summary"]},
            actor="runtime",
        )

    def _merge_evidence(self, plan: dict[str, Any], step: dict[str, Any], result: dict[str, Any]) -> None:
        evidence = plan.setdefault("evidence", {})
        evidence.setdefault("toolResults", []).append(
            {"stepId": step["id"], "toolId": step["toolId"], "ok": result.get("ok", False), "summary": result.get("summary", "")}
        )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        checkpoint = data.get("checkpoint")
        if isinstance(checkpoint, dict):
            evidence.setdefault("checkpoints", []).append({"stepId": step["id"], "checkpointId": checkpoint.get("id"), "label": checkpoint.get("label")})
            step["checkpointId"] = checkpoint.get("id")
        diff = data.get("diff") if isinstance(data.get("diff"), dict) else data if "files" in data else {}
        diff_files = diff.get("files") if isinstance(diff, dict) else None
        if isinstance(diff_files, list):
            known = set(evidence.setdefault("diffFiles", []))
            for file_path in diff_files:
                if file_path not in known:
                    evidence["diffFiles"].append(file_path)
                    known.add(file_path)
            step["diffFiles"] = diff_files
        if step["toolId"] == "command.run":
            evidence.setdefault("verificationResults", []).append(
                {
                    "stepId": step["id"],
                    "command": data.get("command"),
                    "exitCode": data.get("exitCode"),
                    "ok": result.get("ok", False),
                    "summary": result.get("summary", ""),
                }
            )
        if step["toolId"] == "verification.run":
            self._append_verification_report(plan, data, step["id"])
        if step["toolId"] == "browser.preview_smoke":
            self._append_preview_report(plan, data, step["id"], result.get("summary", ""))
            self.memory.record_preview_smoke(plan["conversationId"], data)

    def _append_verification_report(self, plan: dict[str, Any], report: dict[str, Any], step_id: str) -> bool:
        evidence = plan.setdefault("evidence", {})
        results = report.get("results") if isinstance(report.get("results"), list) else []
        if not results:
            return False
        target = evidence.setdefault("verificationResults", [])
        known = {
            (
                str(item.get("stepId") or ""),
                str(item.get("command") or ""),
                str(item.get("reportPath") or ""),
                str(item.get("phase") or ""),
            )
            for item in target
            if isinstance(item, dict)
        }
        changed = False
        for item in results:
            if not isinstance(item, dict):
                continue
            entry = {
                "stepId": step_id,
                "phase": item.get("phase"),
                "command": item.get("command"),
                "exitCode": item.get("exitCode"),
                "ok": bool(item.get("ok")),
                "summary": item.get("summary") or report.get("summary", ""),
                "durationMs": item.get("durationMs"),
                "timedOut": bool(item.get("timedOut")),
                "stdoutTail": item.get("stdoutTail"),
                "stderrTail": item.get("stderrTail"),
                "reportPath": report.get("reportPath"),
                "source": "verification-report",
                "generatedAt": report.get("generatedAt"),
            }
            key = (
                str(entry.get("stepId") or ""),
                str(entry.get("command") or ""),
                str(entry.get("reportPath") or ""),
                str(entry.get("phase") or ""),
            )
            if key in known:
                continue
            target.append(entry)
            known.add(key)
            changed = True
        return changed

    def _append_preview_report(self, plan: dict[str, Any], report: dict[str, Any], step_id: str, fallback_summary: str = "") -> bool:
        evidence = plan.setdefault("evidence", {})
        target = evidence.setdefault("previewResults", [])
        report_path = report.get("reportPath")
        generated_at = report.get("generatedAt")
        url = report.get("url")
        for item in target:
            if not isinstance(item, dict):
                continue
            if report_path and item.get("reportPath") == report_path:
                return False
            if generated_at and item.get("generatedAt") == generated_at and item.get("url") == url:
                return False

        screenshot = report.get("screenshot") if isinstance(report.get("screenshot"), dict) else {}
        runtime_dom = report.get("runtimeDom") if isinstance(report.get("runtimeDom"), dict) else {}
        browser_console = report.get("browserConsole") if isinstance(report.get("browserConsole"), dict) else {}
        quality = report.get("quality") if isinstance(report.get("quality"), dict) else {}
        preview_evidence = {
            "stepId": step_id,
            "url": url,
            "ok": bool(report.get("ok")),
            "summary": report.get("summary") or fallback_summary,
            "failureClass": quality.get("failureClass"),
            "httpStatus": report.get("httpStatus"),
            "htmlTitle": report.get("htmlTitle"),
            "htmlBytes": report.get("htmlBytes") or 0,
            "runtimeDomOk": bool(runtime_dom.get("ok")),
            "runtimeDomPath": runtime_dom.get("path"),
            "runtimeDomBytes": runtime_dom.get("bytes") or 0,
            "runtimeDomVisibleTextLength": runtime_dom.get("visibleTextLength") or 0,
            "consoleErrorCount": browser_console.get("errorCount") or 0,
            "consoleReliable": bool(browser_console.get("reliable")),
            "consoleErrors": browser_console.get("errors") if isinstance(browser_console.get("errors"), list) else [],
            "assertions": report.get("assertions") if isinstance(report.get("assertions"), dict) else None,
            "screenshotOk": bool(screenshot.get("ok")),
            "screenshotPath": screenshot.get("path"),
            "reportPath": report_path,
            "quality": quality or None,
            "source": "preview-smoke-report",
            "generatedAt": generated_at,
        }
        target.append(preview_evidence)
        return True

    def _normalize_requested_steps(self, steps: list[dict[str, Any]], tool_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, raw_step in enumerate(steps, start=1):
            tool_id = str(raw_step.get("toolId", "")).strip()
            if not tool_id:
                raise RuntimeError("工具计划步骤缺少 toolId。")
            tool = tool_map.get(tool_id)
            if not tool:
                raise RuntimeError(f"工具不存在：{tool_id}")
            input_payload = raw_step.get("input") if isinstance(raw_step.get("input"), dict) else {}
            normalized.append(self._step(index, tool, input_payload, raw_step.get("title"), raw_step.get("purpose")))
        return normalized

    def _default_steps(self, requirement: str, repository: dict[str, Any] | None, tool_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        defaults: list[tuple[str, dict[str, Any], str, str]] = [
            ("code.search_files", {"query": requirement, "maxResults": 12}, "定位相关文件", "先找出和需求相关的候选文件，作为后续读写范围。"),
        ]
        if (repository or {}).get("packageManager") == "npm":
            defaults.append(("code.read_file", {"relativePath": "package.json", "maxBytes": 40000}, "读取项目脚本", "读取 package.json，确认可用 scripts 和技术栈。"))
        if (repository or {}).get("sourceType") == "github":
            defaults.append(("github.inspect_repository", {}, "检查 GitHub 仓库", "确认当前沙盒对应的 GitHub remote、branch 和 HEAD。"))
        defaults.extend(
            [
                ("command.run", {"command": "git status --short", "timeoutSeconds": 20}, "检查沙盒状态", "确认当前对话沙盒内是否已有未交付改动。"),
                ("code.git_diff", {}, "检查当前 Diff", "读取当前 sandbox diff，避免覆盖已有改动。"),
            ]
        )
        verification = self._select_verification_command(repository)
        if verification:
            defaults.append(("command.run", {"command": verification, "timeoutSeconds": 180}, "运行验证命令", "按仓库已有脚本运行一次最小验证，留下可审查证据。"))
        steps = []
        for index, (tool_id, input_payload, title, purpose) in enumerate(defaults, start=1):
            tool = tool_map.get(tool_id)
            if tool:
                steps.append(self._step(index, tool, input_payload, title, purpose))
        return steps

    def _enrich_preview_assertion_steps(self, steps: list[dict[str, Any]], requirement: str) -> list[dict[str, Any]]:
        hints = build_preview_assertions(requirement)
        if not hints.get("enabled"):
            return steps
        for step in steps:
            if not isinstance(step, dict) or step.get("toolId") != "browser.preview_smoke":
                continue
            input_payload = step.get("input") if isinstance(step.get("input"), dict) else {}
            step["input"] = merge_preview_assertions(input_payload, hints)
            step["acceptanceHints"] = hints
        return steps

    def _ensure_failure_context_steps(
        self,
        steps: list[dict[str, Any]],
        source_plan: dict[str, Any],
        failure_text: str,
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tool_ids = {tool.get("id") for tool in tools}
        if "code.read_file" not in tool_ids:
            return steps
        existing_reads = {
            str((step.get("input") or {}).get("relativePath") or "").replace("\\", "/")
            for step in steps
            if isinstance(step, dict) and step.get("toolId") == "code.read_file"
        }
        candidates = self._candidate_failure_files(source_plan, failure_text, existing_only=True)
        additions = []
        for relative_path in candidates:
            if relative_path in existing_reads:
                continue
            additions.append(
                {
                    "toolId": "code.read_file",
                    "title": f"读取失败文件：{relative_path}",
                    "purpose": "从验证日志或 diff 中定位到的失败文件，修复前必须读取真实内容。",
                    "input": {"relativePath": relative_path, "maxBytes": 80000},
                }
            )
            existing_reads.add(relative_path)
            if len(additions) >= 3:
                break
        if not additions:
            return steps

        insert_at = 0
        for index, step in enumerate(steps):
            if step.get("toolId") in {"code.git_diff", "code.search_files"}:
                insert_at = index + 1
        return [*steps[:insert_at], *additions, *steps[insert_at:]]

    def _default_repair_steps(
        self,
        source_plan: dict[str, Any],
        failed_summary: str,
        policy: dict[str, Any],
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tool_ids = {tool.get("id") for tool in tools}
        steps: list[dict[str, Any]] = []
        failure_class = str(policy.get("failureClass") or "unknown")
        if "code.git_diff" in tool_ids:
            steps.append(
                {
                    "toolId": "code.git_diff",
                    "title": "复查当前 Diff",
                    "purpose": "修复前确认沙盒里已经有哪些改动，避免覆盖有效工作。",
                    "input": {},
                }
            )
        if "code.search_files" in tool_ids:
            steps.append(
                {
                    "toolId": "code.search_files",
                    "title": "定位失败相关文件",
                    "purpose": "根据失败摘要重新搜索候选文件，为下一步读取或 patch 做准备。",
                    "input": {"query": failed_summary[:500], "maxResults": 12},
                }
            )
        if failure_class == "environment" and (source_plan.get("repository") or {}).get("packageManager") == "npm":
            if "code.read_file" in tool_ids:
                steps.append(
                    {
                        "toolId": "code.read_file",
                        "title": "读取依赖配置",
                        "purpose": "确认 package.json 中脚本和依赖版本，判断是缺安装、脚本缺失还是版本冲突。",
                        "input": {"relativePath": "package.json", "maxBytes": 40000},
                    }
                )
            if "command.run" in tool_ids:
                steps.append(
                    {
                        "toolId": "command.run",
                        "title": "修复依赖环境",
                        "purpose": "在当前对话沙盒中安装依赖或恢复缺失依赖，原始仓库不会被修改。",
                        "input": {"command": "npm install", "timeoutSeconds": 600},
                    }
                )
        elif "code.read_file" in tool_ids:
            candidate = self._first_failed_relative_file(source_plan) or "package.json"
            steps.append(
                {
                    "toolId": "code.read_file",
                    "title": "读取失败相关文件",
                    "purpose": "拿到足够代码上下文后再决定是否生成 patch。",
                    "input": {"relativePath": candidate, "maxBytes": 80000},
                }
            )
        return steps

    def _ensure_repair_verification_step(self, steps: list[dict[str, Any]], source_plan: dict[str, Any]) -> list[dict[str, Any]]:
        if any(self._is_verification_step(step) for step in steps if isinstance(step, dict)):
            return steps
        verification = self._select_verification_command(source_plan.get("repository"), source_plan)
        if not verification:
            return steps
        return [
            *steps,
            {
                "toolId": "command.run",
                "title": "复跑验证",
                "purpose": "执行修复后复跑失败命令或仓库最小验证，决定是否继续下一轮修复。",
                "input": {"command": verification, "timeoutSeconds": 180},
            },
        ]

    def _ensure_repair_preview_step(
        self,
        steps: list[dict[str, Any]],
        source_plan: dict[str, Any],
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tool_ids = {tool.get("id") for tool in tools}
        if "browser.preview_smoke" not in tool_ids:
            return steps
        preview = self._latest_preview_result(source_plan)
        if not preview:
            return steps
        assertions = preview.get("assertions") if isinstance(preview.get("assertions"), dict) else {}
        url = str(preview.get("url") or "")
        port = self._preview_port(url)
        if not port:
            return steps

        expected_texts = assertions.get("expectedTexts") if isinstance(assertions.get("expectedTexts"), list) else []
        required_selectors = assertions.get("requiredSelectors") if isinstance(assertions.get("requiredSelectors"), list) else []
        preview_input = {
            "port": port,
            "path": self._preview_path(url),
            "timeoutSeconds": 30,
            "expectedTexts": expected_texts,
            "requiredSelectors": required_selectors,
        }

        enriched_steps: list[dict[str, Any]] = []
        found_preview_step = False
        for step in steps:
            if isinstance(step, dict) and step.get("toolId") == "browser.preview_smoke":
                found_preview_step = True
                input_payload = step.get("input") if isinstance(step.get("input"), dict) else {}
                step = {**step, "input": merge_preview_assertions(input_payload, {"expectedTexts": expected_texts, "requiredSelectors": required_selectors})}
            enriched_steps.append(step)
        if found_preview_step:
            return enriched_steps

        return [
            *enriched_steps,
            {
                "toolId": "browser.preview_smoke",
                "title": "复跑预览验收",
                "purpose": "修复后复跑上一轮页面断言、控制台、DOM 和截图验证，确认页面不只是能打开，而是满足验收点。",
                "input": preview_input,
            },
        ]

    def _latest_preview_result(self, source_plan: dict[str, Any]) -> dict[str, Any] | None:
        evidence = source_plan.get("evidence") if isinstance(source_plan.get("evidence"), dict) else {}
        preview_results = evidence.get("previewResults") if isinstance(evidence.get("previewResults"), list) else []
        for item in reversed(preview_results):
            if isinstance(item, dict):
                return item
        for step in reversed(source_plan.get("steps", [])):
            if not isinstance(step, dict) or step.get("toolId") != "browser.preview_smoke":
                continue
            result = step.get("result") if isinstance(step.get("result"), dict) else {}
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            if data:
                return data
        return None

    def _preview_port(self, url: str) -> int | None:
        try:
            parsed = urlparse(url)
        except ValueError:
            return None
        return parsed.port

    def _preview_path(self, url: str) -> str:
        try:
            parsed = urlparse(url)
        except ValueError:
            return "/"
        path = parsed.path or "/"
        if parsed.query:
            return f"{path}?{parsed.query}"
        return path

    def _select_verification_command(self, repository: dict[str, Any] | None, source_plan: dict[str, Any] | None = None) -> str | None:
        failed_command = self._failed_verification_command(source_plan)
        if failed_command:
            return failed_command
        scripts = (repository or {}).get("scripts")
        if isinstance(scripts, dict) and scripts:
            for script_name in ("typecheck", "lint", "test", "build"):
                if script_name in scripts:
                    return f"npm run {script_name}"
        return None

    def _failed_verification_command(self, source_plan: dict[str, Any] | None) -> str | None:
        if not source_plan:
            return None
        for step in source_plan.get("steps", []):
            if not isinstance(step, dict) or step.get("toolId") != "command.run":
                continue
            if step.get("status") != "failed":
                continue
            command = str((step.get("input") or {}).get("command") or "").strip()
            if command and self._looks_like_verification_command(command):
                return command
        return None

    def _is_verification_step(self, step: dict[str, Any]) -> bool:
        if step.get("toolId") != "command.run":
            return False
        command = str((step.get("input") or {}).get("command") or "").strip()
        return self._looks_like_verification_command(command)

    def _looks_like_verification_command(self, command: str) -> bool:
        normalized = command.lower()
        markers = ["npm run typecheck", "npm run lint", "npm run test", "npm test", "npm run build", "pytest", "ruff", "mypy", "pnpm test", "yarn test"]
        return any(marker in normalized for marker in markers)

    def _first_failed_relative_file(self, source_plan: dict[str, Any]) -> str | None:
        candidates = self._candidate_failure_files(source_plan, self._failure_text(self._failed_steps(source_plan)), existing_only=True)
        return candidates[0] if candidates else None

    def _candidate_failure_files(self, source_plan: dict[str, Any], failure_text: str, existing_only: bool = False) -> list[str]:
        candidates: list[str] = []

        for step in self._failed_steps(source_plan):
            diff_files = step.get("diffFiles")
            if isinstance(diff_files, list):
                candidates.extend(str(item) for item in diff_files if isinstance(item, str))
            input_payload = step.get("input") if isinstance(step.get("input"), dict) else {}
            relative_path = input_payload.get("relativePath")
            if isinstance(relative_path, str):
                candidates.append(relative_path)

        candidates.extend(self._extract_paths_from_text(failure_text))
        repo_path = None
        sandbox = source_plan.get("sandbox") if isinstance(source_plan.get("sandbox"), dict) else {}
        if isinstance(sandbox, dict):
            repo_path = sandbox.get("repoPath")
        return self._normalize_candidate_files(candidates, repo_path=repo_path, existing_only=existing_only)

    def _extract_paths_from_text(self, text: str) -> list[str]:
        patterns = [
            r"(?P<path>(?:[A-Za-z0-9_.@-]+[\\/])+[A-Za-z0-9_.@-]+\.(?:tsx|ts|jsx|js|mjs|py|vue|css|html|ya?ml))(?::\d+(?::\d+)?)?",
            r"(?P<path>(?:[A-Za-z0-9_.@-]+[\\/])+[A-Za-z0-9_.@-]+\.(?:tsx|ts|jsx|js|mjs|py|vue|css|html|ya?ml))\(\d+,\d+\)",
            r"File \"(?P<path>[^\"]+\.(?:py|js|ts|tsx|jsx|mjs))\", line \d+",
            r"(?P<path>\b[A-Za-z0-9_.@-]+\.(?:tsx|ts|jsx|js|mjs|py|vue|css|html|ya?ml))(?::\d+(?::\d+)?)?",
        ]
        paths: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                paths.append(match.group("path"))
        return paths

    def _normalize_candidate_files(self, paths: list[str], repo_path: Any = None, existing_only: bool = False) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        repo_root = Path(str(repo_path)).resolve() if repo_path else None
        repo_prefixes = self._repo_prefixes(repo_root)
        for raw_path in paths:
            path = str(raw_path or "").strip().strip("'\"`")
            if not path:
                continue
            path = path.replace("\\", "/")
            path = re.sub(r"^\./", "", path)
            path = re.sub(r"^[A-Za-z]:/", "", path)
            path = self._strip_repo_prefix(path, repo_prefixes)
            if "workspace/conversations/" in path and "/repo/" in path:
                path = path.rsplit("/repo/", 1)[-1]
            if path.startswith("/") or ".." in path.split("/"):
                continue
            if "/node_modules/" in f"/{path}/" or "/dist/" in f"/{path}/" or "/build/" in f"/{path}/":
                continue
            if not path.lower().endswith(SOURCE_FILE_EXTENSIONS):
                continue
            if existing_only and repo_root and not (repo_root / path).exists():
                continue
            if path not in seen:
                normalized.append(path)
                seen.add(path)
        return normalized

    def _repo_prefixes(self, repo_root: Path | None) -> list[str]:
        if not repo_root:
            return []
        raw = str(repo_root).replace("\\", "/").strip("/")
        without_drive = re.sub(r"^[A-Za-z]:/", "", raw).strip("/")
        prefixes = [raw]
        if without_drive and without_drive != raw:
            prefixes.append(without_drive)
        return [prefix for prefix in prefixes if prefix]

    def _strip_repo_prefix(self, path: str, prefixes: list[str]) -> str:
        candidate = path.strip("/")
        for prefix in prefixes:
            prefix = prefix.strip("/")
            if candidate == prefix:
                return ""
            if candidate.startswith(f"{prefix}/"):
                return candidate[len(prefix) + 1 :]
            marker = f"/{prefix}/"
            wrapped = f"/{candidate}"
            if marker in wrapped:
                return wrapped.split(marker, 1)[-1]
        return candidate

    def _latest_repair_policy(self, source_plan: dict[str, Any]) -> dict[str, Any]:
        if isinstance(source_plan.get("repairPolicy"), dict):
            return {**DEFAULT_REPAIR_POLICY, **source_plan["repairPolicy"]}
        for audit in reversed(source_plan.get("audits", [])):
            if isinstance(audit, dict) and isinstance(audit.get("repairPolicy"), dict):
                return {**DEFAULT_REPAIR_POLICY, **audit["repairPolicy"]}
        return dict(DEFAULT_REPAIR_POLICY)

    def _guard_repair_policy(self, conversation_id: str, source_plan: dict[str, Any], policy: dict[str, Any]) -> None:
        failure_class = str(policy.get("failureClass") or "unknown")
        if policy.get("requiresUserConfirmation") and not policy.get("autoAllowed"):
            reason = policy.get("reason") or f"{failure_class} 类型失败需要先处理配置、权限或需求澄清。"
            self.events.append(conversation_id, "repair_loop.waiting_human", {"sourcePlanId": source_plan.get("id"), "reason": reason, "failureClass": failure_class}, actor="agent")
            raise RuntimeError(reason)

        source_sequence = int(source_plan.get("repairSequence") or 0)
        max_total = int(policy.get("maxTotalRepairSteps") or DEFAULT_REPAIR_POLICY["maxTotalRepairSteps"])
        if source_sequence >= max_total:
            reason = f"自动修复已达到总步数上限 {max_total}，需要人工审查失败证据后继续。"
            self.events.append(conversation_id, "repair_loop.stopped", {"sourcePlanId": source_plan.get("id"), "reason": reason, "repairSequence": source_sequence}, actor="agent")
            raise RuntimeError(reason)

        previous_code_attempt = int(source_plan.get("repairAttempt") or 0)
        max_code = int(policy.get("maxCodeRepairAttempts") or DEFAULT_REPAIR_POLICY["maxCodeRepairAttempts"])
        if policy.get("countsTowardCodeRepairLimit") and previous_code_attempt >= max_code:
            reason = f"代码修复已达到 {max_code} 次上限，需要人工审查 diff、日志和方向后继续。"
            self.events.append(conversation_id, "repair_loop.stopped", {"sourcePlanId": source_plan.get("id"), "reason": reason, "repairAttempt": previous_code_attempt}, actor="agent")
            raise RuntimeError(reason)

    def _failed_summary(self, failed_steps: list[dict[str, Any]]) -> str:
        if not failed_steps:
            return "工具执行后需要复查证据。"
        lines = []
        for step in failed_steps:
            result = step.get("result") if isinstance(step.get("result"), dict) else {}
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            summary = step.get("summary") or result.get("summary") or ""
            stderr_tail = str(data.get("stderrTail") or data.get("stderr") or "").strip()
            stdout_tail = str(data.get("stdoutTail") or data.get("stdout") or "").strip()
            detail = stderr_tail or stdout_tail
            if detail:
                summary = f"{summary}；日志：{detail[:500]}"
            lines.append(f"{step.get('title')}: {summary}")
        return "\n".join(f"- {line}" for line in lines)

    def _failed_steps(self, source_plan: dict[str, Any]) -> list[dict[str, Any]]:
        return [step for step in source_plan.get("steps", []) if isinstance(step, dict) and step.get("status") == "failed"]

    def _repair_source_summary(
        self,
        source_plan: dict[str, Any],
        failed_steps: list[dict[str, Any]],
        failed_summary: str,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        verifier = self._latest_audit(source_plan, "Verifier")
        return {
            "planId": source_plan.get("id"),
            "status": source_plan.get("status"),
            "summary": failed_summary,
            "failureClass": policy.get("failureClass") or source_plan.get("failureClass") or "unknown",
            "verifierVerdict": verifier.get("verdict") if verifier else None,
            "verifierSummary": verifier.get("summary") if verifier else None,
            "failedSteps": [
                {
                    "id": step.get("id"),
                    "order": step.get("order"),
                    "title": step.get("title"),
                    "toolId": step.get("toolId"),
                    "summary": step.get("summary") or ((step.get("result") or {}).get("summary") if isinstance(step.get("result"), dict) else ""),
                }
                for step in failed_steps[:6]
            ],
        }

    def _latest_audit(self, plan: dict[str, Any], source: str) -> dict[str, Any] | None:
        for audit in reversed(plan.get("audits", [])):
            if isinstance(audit, dict) and audit.get("source") == source:
                return audit
        return None

    def _failure_text(self, failed_steps: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for step in failed_steps:
            result = step.get("result") if isinstance(step.get("result"), dict) else {}
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            input_payload = step.get("input") if isinstance(step.get("input"), dict) else {}
            parts.extend(
                [
                    str(step.get("title") or ""),
                    str(step.get("summary") or ""),
                    str(result.get("summary") or ""),
                    str(input_payload.get("command") or ""),
                    str(input_payload.get("relativePath") or ""),
                    str(data.get("command") or ""),
                    str(data.get("stdoutTail") or data.get("stdout") or ""),
                    str(data.get("stderrTail") or data.get("stderr") or ""),
                ]
            )
        return "\n".join(part for part in parts if part)

    def _step(self, order: int, tool: dict[str, Any], input_payload: dict[str, Any], title: Any, purpose: Any) -> dict[str, Any]:
        risk_level = tool.get("riskLevel", "unknown")
        requires_approval = risk_level in {"command", "external", "dangerous"} or bool(tool.get("requiresCheckpoint"))
        return {
            "id": f"step_{order:02d}_{uuid4().hex[:6]}",
            "order": order,
            "kind": "tool",
            "toolId": tool["id"],
            "title": str(title or tool.get("name") or tool["id"]),
            "purpose": str(purpose or tool.get("description") or ""),
            "input": input_payload,
            "riskLevel": risk_level,
            "requiresApproval": requires_approval,
            "requiresCheckpoint": bool(tool.get("requiresCheckpoint")),
            "status": "pending",
            "createdAt": now_iso(),
        }

    def _require_plan(self, conversation_id: str, plan_id: str | None = None) -> dict[str, Any]:
        plan = self.get_plan(conversation_id)
        if not plan:
            raise RuntimeError("当前对话还没有工具调用计划。")
        if plan_id and plan.get("id") != plan_id:
            raise RuntimeError("工具调用计划 id 不匹配。")
        return plan

    def _require_step(self, plan: dict[str, Any], step_id: str) -> dict[str, Any]:
        for step in plan.get("steps", []):
            if isinstance(step, dict) and step.get("id") == step_id:
                return step
        raise RuntimeError("工具计划步骤不存在。")

    def _step_edit_snapshot(self, step: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": step.get("id"),
            "order": step.get("order"),
            "title": step.get("title"),
            "purpose": step.get("purpose"),
            "input": step.get("input"),
            "status": step.get("status"),
            "disabled": step.get("disabled", False),
        }

    def _move_step(self, plan: dict[str, Any], step_id: str, target_order: int) -> None:
        steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
        if not steps:
            raise RuntimeError("当前工具计划没有步骤。")
        current_index = next((index for index, step in enumerate(steps) if step.get("id") == step_id), None)
        if current_index is None:
            raise RuntimeError("工具计划步骤不存在。")
        target_index = max(0, min(int(target_order) - 1, len(steps) - 1))
        step = steps.pop(current_index)
        steps.insert(target_index, step)
        for index, item in enumerate(steps, start=1):
            item["order"] = index
        plan["steps"] = steps

    def _latest_blocked_review(self, plan: dict[str, Any]) -> dict[str, Any] | None:
        for audit in reversed(plan.get("audits", [])):
            if not isinstance(audit, dict):
                continue
            if audit.get("source") == "Reviewer":
                return audit if audit.get("verdict") == "blocked" else None
        return None

    def _save(self, plan: dict[str, Any]) -> None:
        plan["updatedAt"] = now_iso()
        write_json(conversation_root(plan["conversationId"]) / PLAN_FILE, plan)
