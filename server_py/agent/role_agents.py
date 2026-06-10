from __future__ import annotations

import json
from typing import Any

from server_py.core.json_io import now_iso
from server_py.models.ark_client import ArkClient
from server_py.models.model_config import ModelConfigService
from server_py.observability.metrics import MetricStore


class AgentRoleSuite:
    """模型驱动的 Clarifier / Reviewer / Verifier。

    三个角色都优先让当前默认模型返回可解析 JSON；如果模型不可用、返回非法
    JSON，或者字段不完整，就回退到确定性规则。确定性规则仍作为安全兜底，
    会和模型审计结果合并，避免模型误放行危险计划。
    """

    def __init__(
        self,
        client: ArkClient | None = None,
        metrics: MetricStore | None = None,
        models: ModelConfigService | None = None,
    ) -> None:
        self.client = client
        self.metrics = metrics
        self.models = models

    def clarify(
        self,
        requirement: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        conversation_id: str | None = None,
        memory_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fallback = self._record(
            "clarification",
            "Clarifier",
            self._clarify_rules(requirement, repository, sandbox),
            summary="已完成需求清晰度检查。",
            recommendation="如果存在阻断问题，需要先补齐仓库、沙盒或需求边界。",
            model_source="rules",
        )
        return self._run_model_role(
            conversation_id=conversation_id,
            metric_source="role_clarifier",
            stage="clarification",
            source="Clarifier",
            fallback=fallback,
            task="判断用户需求是否足够明确。不明确时必须生成具体追问，并说明为什么不能进入工具计划。",
            payload={
                "requirement": requirement,
                "repository": repository,
                "sandbox": sandbox,
                "memory": memory_snapshot,
                "hardRules": [
                    "缺少沙盒时不能进入代码写入链路。",
                    "需求过短或只说优化、调整、不好看时，需要追问目标页面、验收标准和不改动范围。",
                    "只输出 JSON，不要输出 Markdown。",
                ],
            },
        )

    def review_tool_plan(
        self,
        plan: dict[str, Any],
        conversation_id: str | None = None,
        memory_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fallback = self._record(
            "planning",
            "Reviewer",
            self._review_rules(plan),
            summary="已完成工具计划安全审查。",
            recommendation="工具计划必须先读上下文、检查 diff；写入步骤必须有 checkpoint。",
            model_source="rules",
        )
        return self._run_model_role(
            conversation_id=conversation_id,
            metric_source="role_reviewer",
            stage="planning",
            source="Reviewer",
            fallback=fallback,
            task="审查工具计划是否安全、是否读取上下文、是否包含 diff/checkpoint/验证。发现阻断时必须给出原因。",
            payload={
                "plan": self._compact_plan(plan),
                "memory": memory_snapshot,
                "hardRules": [
                    "空计划必须 blocked。",
                    "写入步骤必须 requiresCheckpoint=true。",
                    "计划至少要有 diff 检查，否则给 warning。",
                    "Reviewer blocked 时用户不能直接执行计划。",
                ],
            },
        )

    def verify_execution(
        self,
        plan: dict[str, Any] | None,
        conversation_id: str | None = None,
        memory_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        verify_findings = self._verify_rules(plan)
        fallback = self._record(
            "post_verify",
            "Verifier",
            verify_findings,
            summary="已完成执行结果验证。",
            recommendation="失败时进入修复循环；通过时继续交付包和回退点审查。",
            model_source="rules",
        )
        fallback.update(self._repair_policy_from_plan(plan, verify_findings))
        return self._run_model_role(
            conversation_id=conversation_id,
            metric_source="role_verifier",
            stage="post_verify",
            source="Verifier",
            fallback=fallback,
            task="基于工具结果、验证输出、diff 和审计记录判断执行是否通过；失败时给出修复方向。",
            payload={
                "plan": self._compact_plan(plan) if plan else None,
                "memory": memory_snapshot,
                "hardRules": [
                    "存在 failed 步骤时必须 blocked。",
                    "工具结果缺失时至少 warning。",
                    "计划完成但没有 diff 时给 warning，除非需求只是检查。",
                    "前端、页面、UI、预览相关任务必须检查 previewResults；有截图失败、HTTP 失败或 HTML 为空时不能判定交付可靠。",
                    "运行后 DOM 读取失败、运行后可见文本过少、浏览器控制台存在错误时，不能直接判定前端交付可靠。",
                    "如果 previewResults 中 assertions.enabled=true 且 assertions.ok=false，必须判定为未满足验收。",
                    "如果 previewResults 通过，应把截图路径、HTML 标题、运行后 DOM、控制台错误数和报告路径作为交付证据。",
                    "失败时必须给出下一轮修复建议。",
                    "失败时必须输出 failureClass 和 repairPolicy。",
                    "failureClass 只能是 environment、code、plan、requirement、external、unknown。",
                    "依赖未安装、命令不存在、版本冲突属于 environment，不消耗代码修复次数。",
                    "类型错误、lint、测试断言、运行时报错属于 code，消耗代码修复次数。",
                    "读文件不够、工具计划选错属于 plan，应重新规划，不消耗代码修复次数。",
                    "需求方向冲突或验收标准不清属于 requirement，必须停下澄清。",
                    "API key、网络权限、外部 MCP 授权失败属于 external，必须请求配置或授权。",
                ],
            },
        )

    def _run_model_role(
        self,
        conversation_id: str | None,
        metric_source: str,
        stage: str,
        source: str,
        fallback: dict[str, Any],
        task: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        model = self._default_model()
        if not model:
            fallback["fallbackReason"] = "模型不可用，使用确定性规则。"
            return fallback

        try:
            raw_response = self.client.complete(model, self._messages(source, task, payload))
            if conversation_id and self.metrics:
                self.metrics.record_model_call(conversation_id, metric_source, model, self.client.last_metrics)
            parsed = self._parse_json(raw_response)
            model_record = self._record_from_model(stage, source, parsed, model, raw_response)
            merged = self._merge_safety_findings(model_record, fallback)
            merged["modelSource"] = "model"
            if fallback["findings"]:
                merged["ruleFindings"] = fallback["findings"]
            return merged
        except Exception as error:
            fallback["fallbackReason"] = f"模型角色 JSON 解析失败，已回退规则：{error}"
            return fallback

    def _messages(self, source: str, task: str, payload: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        f"你是本地代码交付 Agent 的 {source} 角色。",
                        "必须用中文思考并输出。",
                        "只输出 JSON，不要输出 Markdown，不要添加解释性前后缀。",
                        "JSON 顶层必须是对象。",
                        "字段：verdict=pass|warning|blocked，summary，findings，recommendation，questions。",
                        "Verifier 失败时还要输出 failureClass、repairScope、repairPolicy。",
                        "findings 是数组，每项包含 id、title、detail、severity=info|warning|error。",
                        "repairPolicy 包含 failureClass、severity、autoAllowed、countsTowardCodeRepairLimit、requiresUserConfirmation、maxCodeRepairAttempts、maxTotalRepairSteps、reason。",
                        "blocked 表示不能进入下一阶段；warning 表示可继续但必须提示风险；pass 表示可继续。",
                        "必须遵守 payload.memory.taskState：用户暂停阶段时给 blocked，用户覆盖下一步动作时按覆盖动作审查。",
                    ]
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": task,
                        "payload": payload,
                        "expectedJson": {
                            "verdict": "warning",
                            "summary": "一句话说明角色结论。",
                            "findings": [
                                {
                                    "id": "example",
                                    "title": "问题标题",
                                    "detail": "具体原因和影响。",
                                    "severity": "warning",
                                }
                            ],
                            "recommendation": "下一步建议。",
                            "questions": ["如果需要用户澄清，列出具体问题。"],
                            "failureClass": "code",
                            "repairScope": "test-failure",
                            "repairPolicy": {
                                "failureClass": "code",
                                "severity": "major",
                                "autoAllowed": True,
                                "countsTowardCodeRepairLimit": True,
                                "requiresUserConfirmation": False,
                                "maxCodeRepairAttempts": 3,
                                "maxTotalRepairSteps": 8,
                                "reason": "说明为什么可以继续自动修复。",
                            },
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]

    def _default_model(self) -> dict[str, Any] | None:
        if not self.client or not self.models:
            return None
        model = self.models.get_default_model()
        return model if model.get("enabled") else None

    def _parse_json(self, raw_response: str) -> dict[str, Any]:
        text = raw_response.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise RuntimeError("角色模型返回的不是 JSON 对象。")
        return parsed

    def _record_from_model(
        self,
        stage: str,
        source: str,
        parsed: dict[str, Any],
        model: dict[str, Any],
        raw_response: str,
    ) -> dict[str, Any]:
        findings = self._sanitize_findings(parsed.get("findings"))
        verdict = self._normalize_verdict(parsed.get("verdict"), findings)
        return {
            "id": f"role_{source.lower()}_{now_iso()}",
            "stage": stage,
            "source": source,
            "verdict": verdict,
            "summary": str(parsed.get("summary") or ""),
            "recommendation": str(parsed.get("recommendation") or ""),
            "questions": [str(item) for item in parsed.get("questions", []) if isinstance(item, str)],
            "failureClass": self._normalize_failure_class(parsed.get("failureClass")),
            "repairScope": str(parsed.get("repairScope") or ""),
            "repairPolicy": self._normalize_repair_policy(parsed.get("repairPolicy"), parsed.get("failureClass")),
            "findings": findings,
            "model": {
                "id": model.get("id"),
                "displayName": model.get("displayName"),
                "provider": model.get("provider"),
            },
            "rawResponse": raw_response,
            "reusedFrom": ["Codex planning gate", "Codex reviewer/verifier separation"],
            "createdAt": now_iso(),
        }

    def _merge_safety_findings(self, model_record: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        merged = dict(model_record)
        findings = list(model_record.get("findings") or [])
        known = {finding.get("id") for finding in findings}
        for finding in fallback.get("findings", []):
            if finding.get("id") not in known:
                findings.append(finding)
                known.add(finding.get("id"))
        merged["findings"] = findings
        merged["verdict"] = self._strictest_verdict(model_record.get("verdict"), fallback.get("verdict"), findings)
        if not merged.get("summary"):
            merged["summary"] = fallback.get("summary", "")
        if not merged.get("recommendation"):
            merged["recommendation"] = fallback.get("recommendation", "")
        if not merged.get("repairPolicy") and fallback.get("repairPolicy"):
            merged["repairPolicy"] = fallback["repairPolicy"]
        if (not merged.get("failureClass") or merged.get("failureClass") == "unknown") and fallback.get("failureClass"):
            merged["failureClass"] = fallback["failureClass"]
        if not merged.get("repairScope") and fallback.get("repairScope"):
            merged["repairScope"] = fallback["repairScope"]
        return merged

    def _strictest_verdict(self, model_verdict: Any, fallback_verdict: Any, findings: list[dict[str, Any]]) -> str:
        if any(finding.get("severity") == "error" for finding in findings):
            return "blocked"
        if model_verdict == "blocked" or fallback_verdict == "blocked":
            return "blocked"
        if model_verdict == "warning" or fallback_verdict == "warning" or findings:
            return "warning"
        return "pass"

    def _normalize_verdict(self, raw: Any, findings: list[dict[str, Any]]) -> str:
        value = str(raw or "").strip().lower()
        if value in {"pass", "warning", "blocked"}:
            return self._strictest_verdict(value, "pass", findings)
        if any(finding.get("severity") == "error" for finding in findings):
            return "blocked"
        return "warning" if findings else "pass"

    def _sanitize_findings(self, raw_findings: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_findings, list):
            return []
        findings: list[dict[str, Any]] = []
        for index, item in enumerate(raw_findings, start=1):
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity") or "warning").lower()
            if severity not in {"info", "warning", "error"}:
                severity = "warning"
            findings.append(
                self._finding(
                    str(item.get("id") or f"model-finding-{index}"),
                    str(item.get("title") or "模型审计发现"),
                    str(item.get("detail") or ""),
                    severity,
                )
            )
        return findings

    def _clarify_rules(
        self,
        requirement: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        text = requirement.strip()
        if len(text) < 12:
            findings.append(self._finding("requirement-too-short", "需求过短", "需求信息不足，建议先追问目标、范围和验收标准。", "warning"))
        if not repository:
            findings.append(self._finding("missing-repository", "缺少仓库", "还没有接入仓库，不能进入代码交付链路。", "warning"))
        if not sandbox:
            findings.append(self._finding("missing-sandbox", "缺少沙盒", "每个对话必须先创建独立沙盒，写入只能发生在沙盒内。", "error"))
        if any(word in text for word in ["优化", "调整", "改一下", "不好看"]) and not any(word in text for word in ["验收", "具体", "文件", "页面"]):
            findings.append(self._finding("ambiguous-change", "需求边界可能不清", "需求包含泛化修改词，建议确认目标页面、验收标准和不希望改动的范围。", "warning"))
        return findings

    def _review_rules(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        steps = plan.get("steps", []) if isinstance(plan.get("steps"), list) else []
        if not steps:
            findings.append(self._finding("empty-plan", "工具计划为空", "没有可审查的工具步骤。", "error"))
        active_steps = [step for step in steps if isinstance(step, dict) and step.get("status") != "skipped" and not step.get("disabled")]
        if steps and not active_steps:
            findings.append(self._finding("no-active-step", "没有可执行步骤", "所有工具步骤都已被禁用，确认执行后不会产生有效证据。", "error"))
        has_diff_check = any(step.get("toolId") == "code.git_diff" for step in active_steps)
        if not has_diff_check:
            findings.append(self._finding("missing-diff-check", "缺少 Diff 检查", "工具计划应包含 diff 检查，避免覆盖已有沙盒改动。", "warning"))
        write_steps = [step for step in active_steps if step.get("riskLevel") == "write"]
        if write_steps and not any(step.get("requiresCheckpoint") for step in write_steps):
            findings.append(self._finding("write-without-checkpoint", "写入缺少 checkpoint", "写入步骤必须绑定 checkpoint。", "error"))
        return findings

    def _verify_rules(self, plan: dict[str, Any] | None) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        if not plan:
            return [self._finding("missing-plan", "缺少工具计划", "没有可验证的工具计划。", "error")]

        evidence = plan.get("evidence", {}) if isinstance(plan.get("evidence"), dict) else {}
        failed_steps = [step for step in plan.get("steps", []) if isinstance(step, dict) and step.get("status") == "failed"]
        if failed_steps:
            findings.append(self._finding("failed-steps", "存在失败步骤", f"{len(failed_steps)} 个工具步骤失败，应进入修复循环。", "error"))
        if not evidence.get("toolResults"):
            findings.append(self._finding("missing-tool-results", "缺少工具结果", "执行后没有工具结果证据。", "warning"))
        if plan.get("status") == "completed" and not evidence.get("diffFiles"):
            findings.append(self._finding("no-diff-after-complete", "没有代码变更", "计划完成但没有 diff 文件，可能只是检查流程。", "warning"))
        return findings

    def _repair_policy_from_plan(self, plan: dict[str, Any] | None, findings: list[dict[str, Any]]) -> dict[str, Any]:
        if not findings:
            return {
                "failureClass": "unknown",
                "repairScope": "",
                "repairPolicy": {
                    "failureClass": "unknown",
                    "severity": "minor",
                    "autoAllowed": False,
                    "countsTowardCodeRepairLimit": False,
                    "requiresUserConfirmation": False,
                    "maxCodeRepairAttempts": 3,
                    "maxTotalRepairSteps": 8,
                    "reason": "当前没有失败，不需要修复。",
                },
            }
        failure_class, scope, reason = self._classify_failure(plan)
        auto_allowed = failure_class in {"environment", "code", "plan", "unknown"}
        requires_user_confirmation = failure_class in {"requirement", "external"}
        counts_code = failure_class == "code"
        severity = "blocked" if failure_class in {"requirement", "external"} else ("major" if failure_class in {"code", "environment"} else "minor")
        return {
            "failureClass": failure_class,
            "repairScope": scope,
            "repairPolicy": {
                "failureClass": failure_class,
                "severity": severity,
                "autoAllowed": auto_allowed,
                "countsTowardCodeRepairLimit": counts_code,
                "requiresUserConfirmation": requires_user_confirmation,
                "maxCodeRepairAttempts": 3,
                "maxTotalRepairSteps": 8,
                "reason": reason,
            },
        }

    def _classify_failure(self, plan: dict[str, Any] | None) -> tuple[str, str, str]:
        if not plan:
            return "plan", "missing-plan", "缺少可验证计划，应该重新规划。"
        failed_steps = [step for step in plan.get("steps", []) if isinstance(step, dict) and step.get("status") == "failed"]
        text = "\n".join(self._step_failure_text(step) for step in failed_steps).lower()
        if any(marker in text for marker in ["api key", "apikey", "authorization", "unauthorized", "forbidden", "permission", "mcp", "network", "econnrefused", "timeout"]):
            return "external", "external-or-permission", "失败与外部服务、权限、网络或 MCP 授权有关，需要配置或授权后继续。"
        if any(marker in text for marker in ["cannot find module", "module not found", "command not found", "not recognized", "enoent", "eresolve", "npm err", "pnpm", "yarn", "missing script", "vite: not found", "dependency"]):
            return "environment", "dependency-or-script", "失败更像依赖、脚本或版本环境问题，应先在沙盒内修复环境，不消耗代码修复次数。"
        if any(marker in text for marker in ["ambiguous", "requirement", "acceptance", "用户", "需求", "验收"]):
            return "requirement", "requirement-boundary", "失败指向需求边界或验收标准不清，需要先澄清方向。"
        if any(marker in text for marker in ["no such file", "file not found", "unknown tool", "工具不存在", "缺少", "empty-plan"]):
            return "plan", "plan-or-context", "失败更像计划或上下文不足，应重新读上下文并生成更具体的计划。"
        if any(marker in text for marker in ["typescript", "tsc", "eslint", "lint", "test", "assert", "failed", "syntax", "type error", "traceback", "exception"]):
            return "code", "code-or-test", "失败来自代码、类型、lint、测试或运行时错误，应生成代码修复。"
        return "unknown", "general-repair", "无法精确分类，但可以继续读取证据并生成保守修复计划。"

    def _step_failure_text(self, step: dict[str, Any]) -> str:
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        parts = [
            str(step.get("title") or ""),
            str(step.get("summary") or ""),
            str(result.get("summary") or ""),
            str(data.get("command") or ""),
            str(data.get("stdout") or data.get("stdoutTail") or ""),
            str(data.get("stderr") or data.get("stderrTail") or ""),
        ]
        return "\n".join(parts)

    def _normalize_failure_class(self, value: Any) -> str:
        normalized = str(value or "unknown").strip().lower()
        if normalized in {"environment", "code", "plan", "requirement", "external", "unknown"}:
            return normalized
        return "unknown"

    def _normalize_repair_policy(self, raw_policy: Any, fallback_class: Any) -> dict[str, Any] | None:
        if not isinstance(raw_policy, dict):
            return None
        failure_class = self._normalize_failure_class(raw_policy.get("failureClass") or fallback_class)
        severity = str(raw_policy.get("severity") or "major").strip().lower()
        if severity not in {"minor", "major", "blocked"}:
            severity = "major"
        return {
            "failureClass": failure_class,
            "severity": severity,
            "autoAllowed": bool(raw_policy.get("autoAllowed", failure_class in {"environment", "code", "plan", "unknown"})),
            "countsTowardCodeRepairLimit": bool(raw_policy.get("countsTowardCodeRepairLimit", failure_class == "code")),
            "requiresUserConfirmation": bool(raw_policy.get("requiresUserConfirmation", failure_class in {"requirement", "external"})),
            "maxCodeRepairAttempts": int(raw_policy.get("maxCodeRepairAttempts") or 3),
            "maxTotalRepairSteps": int(raw_policy.get("maxTotalRepairSteps") or 8),
            "reason": str(raw_policy.get("reason") or ""),
        }

    def _record(
        self,
        stage: str,
        source: str,
        findings: list[dict[str, Any]],
        summary: str = "",
        recommendation: str = "",
        model_source: str = "rules",
    ) -> dict[str, Any]:
        return {
            "id": f"role_{source.lower()}_{now_iso()}",
            "stage": stage,
            "source": source,
            "verdict": "blocked" if any(item["severity"] == "error" for item in findings) else ("warning" if findings else "pass"),
            "summary": summary,
            "recommendation": recommendation,
            "questions": [],
            "failureClass": "unknown",
            "repairScope": "",
            "findings": findings,
            "modelSource": model_source,
            "reusedFrom": ["Codex planning gate", "Codex reviewer/verifier separation"],
            "createdAt": now_iso(),
        }

    def _finding(self, finding_id: str, title: str, detail: str, severity: str) -> dict[str, Any]:
        return {"id": finding_id, "title": title, "detail": detail, "severity": severity}

    def _compact_plan(self, plan: dict[str, Any] | None) -> dict[str, Any] | None:
        if not plan:
            return None
        return {
            "id": plan.get("id"),
            "status": plan.get("status"),
            "requirement": plan.get("requirement"),
            "repairOfPlanId": plan.get("repairOfPlanId"),
            "repairAttempt": plan.get("repairAttempt"),
            "generation": plan.get("generation"),
            "evidence": plan.get("evidence"),
            "audits": plan.get("audits", [])[-6:],
            "steps": [
                {
                    "id": step.get("id"),
                    "order": step.get("order"),
                    "toolId": step.get("toolId"),
                    "title": step.get("title"),
                    "purpose": step.get("purpose"),
                    "riskLevel": step.get("riskLevel"),
                    "requiresCheckpoint": step.get("requiresCheckpoint"),
                    "status": step.get("status"),
                    "summary": step.get("summary"),
                    "input": step.get("input"),
                    "result": self._compact_result(step.get("result")),
                }
                for step in plan.get("steps", [])
                if isinstance(step, dict)
            ],
        }

    def _compact_result(self, result: Any) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {
            "ok": result.get("ok"),
            "summary": result.get("summary"),
            "needsApproval": result.get("needsApproval"),
            "stdoutTail": data.get("stdoutTail"),
            "stderrTail": data.get("stderrTail"),
            "exitCode": data.get("exitCode"),
            "diffFiles": (data.get("diff") or {}).get("files") if isinstance(data.get("diff"), dict) else data.get("files"),
            "reportPath": data.get("reportPath"),
            "htmlTitle": data.get("htmlTitle"),
            "htmlBytes": data.get("htmlBytes"),
            "runtimeDom": data.get("runtimeDom") if isinstance(data.get("runtimeDom"), dict) else None,
            "browserConsole": data.get("browserConsole") if isinstance(data.get("browserConsole"), dict) else None,
            "assertions": data.get("assertions") if isinstance(data.get("assertions"), dict) else None,
            "screenshot": data.get("screenshot") if isinstance(data.get("screenshot"), dict) else None,
            "quality": data.get("quality") if isinstance(data.get("quality"), dict) else None,
            "verificationResults": data.get("results") if isinstance(data.get("results"), list) else None,
        }
