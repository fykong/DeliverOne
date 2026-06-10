from __future__ import annotations

from pathlib import Path
from typing import Any

from server_py.core.json_io import now_iso, write_json


class TaskLedgerService:
    """A compact, inspectable task state for the user and future model calls."""

    def update(
        self,
        path: Path,
        conversation_id: str,
        requirement: str | None,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        search_intent: dict[str, Any] | None,
        recall_items: list[dict[str, Any]],
        matched_skills: list[dict[str, Any]],
        signals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        intent = search_intent or {}
        runtime_signals = signals or {}
        ledger = {
            "conversationId": conversation_id,
            "status": self._status(requirement, repository, sandbox, runtime_signals),
            "activePhase": self._active_phase(requirement, repository, sandbox, runtime_signals),
            "currentUnderstanding": str(intent.get("summary") or requirement or "尚未形成任务理解。")[:1000],
            "repository": {
                "source": (repository or {}).get("source"),
                "branch": (repository or {}).get("branch"),
                "head": (repository or {}).get("head"),
                "sandboxPath": (sandbox or {}).get("repoPath"),
            },
            "searchIntent": {
                "source": intent.get("source") or "rules",
                "confidence": intent.get("confidence"),
                "searchQueries": self._list(intent.get("searchQueries"), 10),
                "fileHints": self._list(intent.get("fileHints"), 10),
                "memoryQueries": self._list(intent.get("memoryQueries"), 8),
                "riskHints": self._list(intent.get("riskHints"), 8),
                "verificationHints": self._list(intent.get("verificationHints"), 8),
                "fallbackReason": intent.get("fallbackReason"),
            },
            "contextUsed": [
                {
                    "id": item.get("id"),
                    "kind": item.get("kind"),
                    "title": item.get("title"),
                    "reason": item.get("reason"),
                    "score": item.get("score"),
                    "sourcePath": item.get("sourcePath"),
                }
                for item in recall_items[:12]
            ],
            "matchedSkills": [
                {
                    "id": skill.get("id"),
                    "name": skill.get("name"),
                    "reason": (skill.get("runtime") or {}).get("selectedReason"),
                }
                for skill in matched_skills[:8]
            ],
            "phases": self._phases(requirement, repository, sandbox, search_intent, recall_items, matched_skills, runtime_signals),
            "gates": self._gates(requirement, repository, sandbox, search_intent, recall_items, runtime_signals),
            "risks": self._risks(intent, recall_items),
            "blockers": self._blockers(requirement, repository, sandbox, intent),
            "nextSteps": self._next_steps(intent, bool(repository), bool(sandbox)),
            "editable": False,
            "editNote": "当前版本是可审查状态账本；后续会支持用户编辑阶段、调整步骤和写入审批意见。",
            "updatedAt": now_iso(),
            "path": str(path),
        }
        write_json(path, ledger)
        return ledger

    def _list(self, value: Any, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in result:
                result.append(text)
            if len(result) >= limit:
                break
        return result

    def _risks(self, intent: dict[str, Any], recall_items: list[dict[str, Any]]) -> list[str]:
        risks = self._list(intent.get("riskHints"), 8)
        if any(item.get("kind") == "failure" for item in recall_items):
            risks.append("存在相关失败记忆，需要优先读取失败证据。")
        if any(item.get("kind") == "curated" and "doNotRepeat" in item.get("tags", []) for item in recall_items):
            risks.append("存在不要重复的用户约束，需要在计划中显式规避。")
        return risks[:10]

    def _status(
        self,
        requirement: str | None,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        signals: dict[str, Any],
    ) -> str:
        if not repository or not sandbox:
            return "waiting_repository"
        if not requirement:
            return "waiting_requirement"
        if signals.get("hasDelivery"):
            return "delivery_ready"
        if signals.get("hasVerification") or signals.get("hasPreview"):
            return "verifying"
        if signals.get("checkpointCount"):
            return "executing"
        if signals.get("hasAgentTurn"):
            return "waiting_confirmation"
        return "planning"

    def _active_phase(
        self,
        requirement: str | None,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        signals: dict[str, Any],
    ) -> str:
        if not repository or not sandbox:
            return "sandbox"
        if not requirement:
            return "requirement"
        if signals.get("hasDelivery"):
            return "delivery"
        if signals.get("hasVerification") or signals.get("hasPreview"):
            return "verification"
        if signals.get("checkpointCount"):
            return "execution"
        if signals.get("hasAgentTurn"):
            return "tool-plan"
        return "plan"

    def _phases(
        self,
        requirement: str | None,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        search_intent: dict[str, Any] | None,
        recall_items: list[dict[str, Any]],
        matched_skills: list[dict[str, Any]],
        signals: dict[str, Any],
    ) -> list[dict[str, Any]]:
        has_repository = bool(repository and sandbox)
        has_requirement = bool((requirement or "").strip())
        has_intent = bool(search_intent)
        has_context = has_repository and bool(recall_items or matched_skills)
        has_plan = bool(signals.get("hasAgentTurn"))
        has_execution = bool(signals.get("checkpointCount"))
        has_verification = bool(signals.get("hasVerification") or signals.get("hasPreview"))
        has_delivery = bool(signals.get("hasDelivery"))
        rows = [
            ("requirement", "需求", has_requirement, "记录用户原始需求和澄清点。"),
            ("sandbox", "沙盒", has_repository, "当前对话必须有独立沙盒。"),
            ("context", "上下文", has_context, "读取仓库画像、记忆和 Skill。"),
            ("intent", "检索意图", has_intent, "拆出搜索线索、风险和验证提示。"),
            ("plan", "方案", has_plan, "生成模型方案并等待用户确认。"),
            ("tool-plan", "工具计划", has_execution, "生成可审查工具调用。"),
            ("execution", "执行", has_execution, "在沙盒中读写代码、运行命令。"),
            ("verification", "验证", has_verification, "运行 lint、测试、构建和预览检查。"),
            ("delivery", "交付", has_delivery, "生成 diff、报告、回退点和交付包。"),
        ]
        active = self._active_phase(requirement, repository, sandbox, signals)
        result: list[dict[str, Any]] = []
        for phase_id, title, done, description in rows:
            if done:
                status = "done"
            elif phase_id == active or (active == "plan" and phase_id == "plan"):
                status = "current"
            elif phase_id == "sandbox" and not has_repository:
                status = "blocked"
            else:
                status = "pending"
            result.append(
                {
                    "id": phase_id,
                    "title": title,
                    "status": status,
                    "description": description,
                }
            )
        return result

    def _gates(
        self,
        requirement: str | None,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        search_intent: dict[str, Any] | None,
        recall_items: list[dict[str, Any]],
        signals: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": "repository",
                "title": "仓库已接入",
                "status": "pass" if repository else "blocked",
                "detail": "Agent 只能在已接入仓库的沙盒里工作。",
            },
            {
                "id": "sandbox",
                "title": "对话沙盒已创建",
                "status": "pass" if sandbox else "blocked",
                "detail": "写入、命令、预览和回退都绑定当前对话沙盒。",
            },
            {
                "id": "requirement",
                "title": "需求已记录",
                "status": "pass" if (requirement or "").strip() else "pending",
                "detail": "后续计划必须能追溯到原始需求。",
            },
            {
                "id": "intent",
                "title": "搜索意图已生成",
                "status": "pass" if search_intent else "pending",
                "detail": "用于决定先读哪些文件和记忆。",
            },
            {
                "id": "context",
                "title": "上下文已召回",
                "status": "pass" if repository and sandbox and recall_items else "pending",
                "detail": "模型计划前应看到相关仓库、记忆和失败证据。",
            },
            {
                "id": "checkpoint",
                "title": "写入前回退点",
                "status": "pass" if signals.get("checkpointCount") else "pending",
                "detail": "写代码前必须有 checkpoint，支持单步和一键回退。",
            },
            {
                "id": "verification",
                "title": "验证证据",
                "status": "pass" if signals.get("hasVerification") or signals.get("hasPreview") else "pending",
                "detail": "交付前需要 lint、测试、构建或预览 smoke 证据。",
            },
        ]

    def _blockers(
        self,
        requirement: str | None,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        intent: dict[str, Any],
    ) -> list[str]:
        blockers: list[str] = []
        if not repository:
            blockers.append("尚未接入仓库。")
        if not sandbox:
            blockers.append("尚未创建当前对话沙盒。")
        if not (requirement or "").strip():
            blockers.append("尚未记录明确需求。")
        fallback_reason = intent.get("fallbackReason")
        if fallback_reason:
            blockers.append(f"搜索意图使用规则回退：{fallback_reason}。")
        return blockers[:8]

    def _next_steps(self, intent: dict[str, Any], has_repository: bool, has_sandbox: bool) -> list[str]:
        if not has_repository or not has_sandbox:
            return ["先接入仓库并创建当前对话沙盒。"]
        steps = ["读取仓库规则、相关记忆和候选文件。"]
        file_hints = self._list(intent.get("fileHints"), 4)
        if file_hints:
            steps.append(f"优先检查文件：{', '.join(file_hints)}。")
        search_queries = self._list(intent.get("searchQueries"), 3)
        if search_queries:
            steps.append(f"使用搜索意图定位代码：{'; '.join(search_queries)}。")
        verification = self._list(intent.get("verificationHints"), 4)
        if verification:
            steps.append(f"准备验证命令：{', '.join(verification)}。")
        steps.append("生成可审查方案，等待用户确认后再进入工具计划。")
        return steps[:6]
