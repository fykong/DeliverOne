from __future__ import annotations

import json
from typing import Any

from server_py.audit.plan_auditor import PlanAuditor
from server_py.agent.preview_assertions import build_preview_assertions
from server_py.models.ark_client import ArkClient
from server_py.models.model_config import ModelConfigService
from server_py.observability.metrics import MetricStore


class ToolPlanDrafter:
    """Ask the model for a reviewable JSON tool plan.

    If the model is unavailable or the JSON fails audit, the caller can fall
    back to the deterministic heuristic plan in ToolCallPlanService.
    """

    def __init__(
        self,
        client: ArkClient,
        auditor: PlanAuditor,
        metrics: MetricStore,
        models: ModelConfigService | None = None,
    ) -> None:
        self.client = client
        self.auditor = auditor
        self.metrics = metrics
        self.models = models

    def draft(
        self,
        conversation_id: str,
        requirement: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        tools: list[dict[str, Any]],
        previous_turn: dict[str, Any] | None,
    ) -> dict[str, Any]:
        preflight = (previous_turn or {}).get("preflight") if isinstance(previous_turn, dict) else None
        model = (preflight or {}).get("model") if isinstance(preflight, dict) else None
        if not model or not model.get("enabled"):
            return self._fallback(conversation_id, "模型不可用，使用确定性默认工具计划。", tools)

        try:
            raw_response = self.client.complete(
                model,
                self._messages(
                    requirement=requirement,
                    repository=repository,
                    sandbox=sandbox,
                    tools=tools,
                    matched_skills=(preflight or {}).get("matchedSkills", []),
                    previous_reply=(previous_turn or {}).get("reply", ""),
                    memory_snapshot=(preflight or {}).get("memory"),
                ),
            )
            self.metrics.record_model_call(conversation_id, "structured_tool_plan", model, self.client.last_metrics)
            parsed = self._parse_json(raw_response)
            steps = parsed.get("steps") if isinstance(parsed.get("steps"), list) else []
            audit = self.auditor.audit_structured_tool_plan(steps, tools)
            if audit["verdict"] == "blocked":
                return {
                    "source": "fallback",
                    "steps": [],
                    "rawResponse": raw_response,
                    "audit": audit,
                    "fallbackReason": "模型返回的结构化工具计划未通过审计，已回退到默认计划。",
                }
            return {
                "source": "model",
                "steps": steps,
                "rawResponse": raw_response,
                "audit": audit,
                "fallbackReason": None,
            }
        except Exception as error:
            return self._fallback(conversation_id, f"结构化工具计划生成失败：{error}", tools)

    def draft_repair(
        self,
        conversation_id: str,
        source_plan: dict[str, Any],
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        tools: list[dict[str, Any]],
        memory_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        model = self.models.get_default_model() if self.models else None
        if not model or not model.get("enabled"):
            return self._repair_fallback(conversation_id, "模型不可用，使用确定性修复诊断计划。", tools)

        try:
            repair_tools = self._repair_allowed_tools(tools)
            read_files = self._collected_read_files(source_plan)
            raw_response = self.client.complete(
                model,
                self._repair_messages(
                    source_plan=source_plan,
                    repository=repository,
                    sandbox=sandbox,
                    tools=repair_tools,
                    memory_snapshot=memory_snapshot,
                    read_files=read_files,
                ),
            )
            self.metrics.record_model_call(conversation_id, "repair_tool_plan", model, self.client.last_metrics)
            parsed = self._parse_json(raw_response)
            steps = parsed.get("steps") if isinstance(parsed.get("steps"), list) else []
            context_violation = self._patch_context_violation(steps, read_files)
            if context_violation:
                return self._repair_rejected_model_plan(
                    conversation_id=conversation_id,
                    reason=context_violation,
                    tools=tools,
                    raw_response=raw_response,
                    summary=str(parsed.get("summary") or ""),
                )
            audit = self.auditor.audit_structured_tool_plan(steps, tools)
            if audit["verdict"] == "blocked":
                return {
                    "source": "repair-loop",
                    "steps": [],
                    "rawResponse": raw_response,
                    "audit": audit,
                    "fallbackReason": "模型返回的修复计划未通过工具审计，已回退确定性修复诊断计划。",
                    "summary": str(parsed.get("summary") or ""),
                }
            return {
                "source": "repair-loop",
                "steps": steps,
                "rawResponse": raw_response,
                "audit": audit,
                "fallbackReason": None,
                "summary": str(parsed.get("summary") or ""),
            }
        except Exception as error:
            return self._repair_fallback(conversation_id, f"修复计划生成失败：{error}", tools)

    def rewrite(
        self,
        conversation_id: str,
        current_plan: dict[str, Any],
        instruction: str,
        tools: list[dict[str, Any]],
        memory_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        model = self.models.get_default_model() if self.models else None
        if not model or not model.get("enabled"):
            return self._rewrite_fallback(conversation_id, "模型不可用，无法根据用户意见重写工具计划。", tools)

        try:
            raw_response = self.client.complete(
                model,
                self._rewrite_messages(
                    current_plan=current_plan,
                    instruction=instruction,
                    tools=tools,
                    memory_snapshot=memory_snapshot,
                ),
            )
            self.metrics.record_model_call(conversation_id, "rewrite_tool_plan", model, self.client.last_metrics)
            parsed = self._parse_json(raw_response)
            steps = parsed.get("steps") if isinstance(parsed.get("steps"), list) else []
            audit = self.auditor.audit_structured_tool_plan(steps, tools)
            if audit["verdict"] == "blocked":
                return {
                    "source": "rewrite",
                    "steps": [],
                    "rawResponse": raw_response,
                    "audit": audit,
                    "fallbackReason": "模型重写后的工具计划未通过工具审计，请调整意见或手动编辑。",
                    "summary": str(parsed.get("summary") or ""),
                }
            return {
                "source": "rewrite",
                "steps": steps,
                "rawResponse": raw_response,
                "audit": audit,
                "fallbackReason": None,
                "summary": str(parsed.get("summary") or ""),
            }
        except Exception as error:
            return self._rewrite_fallback(conversation_id, f"工具计划重写失败：{error}", tools)

    def _messages(
        self,
        requirement: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        tools: list[dict[str, Any]],
        matched_skills: list[dict[str, Any]],
        previous_reply: str,
        memory_snapshot: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        preview_acceptance_hints = build_preview_assertions(requirement, memory_snapshot)
        expected_steps: list[dict[str, Any]] = [
            {
                "toolId": "code.search_files",
                "title": "定位相关文件",
                "purpose": "找到和需求相关的候选文件",
                "input": {"query": requirement, "maxResults": 12},
            }
        ]
        if any(tool.get("id") == "browser.preview_smoke" for tool in tools):
            expected_steps.append(
                {
                    "toolId": "browser.preview_smoke",
                    "title": "运行页面验收",
                    "purpose": "在沙盒预览端口已启动时，验证页面控制台、DOM、截图和明确验收断言。",
                    "input": {
                        "port": 3000,
                        "path": "/",
                        "expectedTexts": preview_acceptance_hints.get("expectedTexts", []),
                        "requiredSelectors": preview_acceptance_hints.get("requiredSelectors", []),
                    },
                }
            )
        return [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "你是一个本地代码 Agent 的工具计划生成器。",
                        "只输出 JSON，不要输出 Markdown，不要解释。",
                        "JSON 顶层必须是对象，包含 steps 数组。",
                        "每个 step 必须包含：toolId、title、purpose、input。",
                        "toolId 只能从 allowedTools 中选择。",
                        "计划必须先读上下文、定位文件、检查 diff，再考虑验证命令。",
                        "除非已经有足够文件内容，否则不要生成 code.write_file 或 code.apply_patch。",
                        "命令只能用于沙盒仓库，优先选择 package.json 中已有脚本。",
                        "如果仓库来自 GitHub，可以使用 github.inspect_repository 确认 remote、branch 和 HEAD。",
                        "必须遵守 memory.taskState：用户暂停的阶段不得生成推进该阶段的写入/命令步骤；用户覆盖的下一步动作优先。",
                        "只有当预览端口已启动或用户要求浏览器验证时，才使用 browser.preview_smoke。",
                        "如果使用 browser.preview_smoke，必须优先带上 previewAcceptanceHints.expectedTexts 和 previewAcceptanceHints.requiredSelectors。",
                        "browser.preview_smoke 不是只检查页面打开；它还要验证用户明确要求的可见文案和页面结构。",
                        "external. 开头的工具来自外部 MCP server；只有需求明确需要外部能力时才选择。",
                        "外部 MCP 工具可能传输上下文，必须在 purpose 中说明调用原因。",
                    ]
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "requirement": requirement,
                        "repository": repository,
                        "sandbox": sandbox,
                        "previousAgentPlan": previous_reply,
                        "memory": memory_snapshot,
                        "previewAcceptanceHints": preview_acceptance_hints,
                        "taskState": (memory_snapshot or {}).get("taskState") if isinstance(memory_snapshot, dict) else None,
                        "skillRuntime": [
                            {
                                "id": skill.get("id"),
                                "name": skill.get("name"),
                                "selectedReason": (skill.get("runtime") or {}).get("selectedReason"),
                                "constraints": (skill.get("runtime") or {}).get("constraints", []),
                            }
                            for skill in matched_skills
                        ],
                        "allowedTools": [
                            {
                                "id": tool.get("id"),
                                "source": tool.get("source", "internal"),
                                "mcpName": tool.get("mcpName"),
                                "description": tool.get("description"),
                                "riskLevel": tool.get("riskLevel"),
                                "requiresCheckpoint": tool.get("requiresCheckpoint"),
                                "inputSchema": tool.get("inputSchema"),
                            }
                            for tool in tools
                        ],
                        "expectedJson": {"steps": expected_steps},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]

    def _repair_messages(
        self,
        source_plan: dict[str, Any],
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        tools: list[dict[str, Any]],
        memory_snapshot: dict[str, Any] | None,
        read_files: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        failed_steps = [
            {
                "id": step.get("id"),
                "toolId": step.get("toolId"),
                "title": step.get("title"),
                "purpose": step.get("purpose"),
                "input": step.get("input"),
                "summary": step.get("summary"),
                "result": self._compact_result(step.get("result")),
            }
            for step in source_plan.get("steps", [])
            if isinstance(step, dict) and step.get("status") == "failed"
        ]
        patch_rule = (
            "当前已经有 readFiles 内容。只有当 code.apply_patch 的每个 relativePath 都来自 readFiles 时，才允许生成 patch。"
            if read_files
            else "当前没有任何已读取文件内容。禁止生成 code.apply_patch；必须先生成 code.search_files / code.read_file / command.run 收集证据。"
        )
        return [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "你是本地代码 Agent 的修复计划生成器。",
                        "只输出 JSON，不要输出 Markdown，不要解释。",
                        "JSON 顶层必须是对象，包含 summary 和 steps。",
                        "steps 中每个 step 必须包含 toolId、title、purpose、input。",
                        "toolId 只能从 allowedTools 中选择。",
                        "修复计划必须先读取失败证据和相关文件，再决定是否使用 code.apply_patch。",
                        "可以使用 code.apply_patch，但 input 必须是结构化 changes：",
                        '{"reason":"为什么这样修","changes":[{"relativePath":"文件路径","action":"write","content":"完整文件内容"}]}',
                        "第一版 patch 使用完整文件内容写入；如果没有足够上下文，不要生成 patch，先 read_file。",
                        patch_rule,
                        "不得对未读取过内容的既有文件生成完整文件 content。",
                        "如果 readFiles 里的内容不足以判断修复方式，只能继续读取更多文件或复跑验证。",
                        "写入仍会等待用户确认，不要假设会自动执行。",
                        "必须遵守 memory.taskState：用户暂停的阶段不得生成推进该阶段的修复写入/命令步骤；用户覆盖的下一步动作优先。",
                        "验证命令只能使用仓库已有脚本或失败计划中出现过的命令。",
                        "如果上一轮 browser.preview_smoke 的 assertions 失败，修复计划需要保留同一组断言并在修复后复跑预览验收。",
                    ]
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "sourcePlan": {
                            "id": source_plan.get("id"),
                            "status": source_plan.get("status"),
                            "requirement": source_plan.get("requirement"),
                            "repairAttempt": source_plan.get("repairAttempt"),
                            "evidence": source_plan.get("evidence"),
                            "failedSteps": failed_steps,
                            "audits": source_plan.get("audits", [])[-8:],
                        },
                        "readFiles": read_files,
                        "patchPolicy": {
                            "canPatchNow": bool(read_files),
                            "allowedPatchTargets": [item["relativePath"] for item in read_files],
                            "rule": "code.apply_patch 只能修改 readFiles 中已有完整内容的文件；没有 readFiles 时必须继续收集证据。",
                        },
                        "repository": repository,
                        "sandbox": sandbox,
                        "memory": memory_snapshot,
                        "taskState": (memory_snapshot or {}).get("taskState") if isinstance(memory_snapshot, dict) else None,
                        "allowedTools": [
                            {
                                "id": tool.get("id"),
                                "description": tool.get("description"),
                                "riskLevel": tool.get("riskLevel"),
                                "requiresCheckpoint": tool.get("requiresCheckpoint"),
                                "inputSchema": tool.get("inputSchema"),
                            }
                            for tool in tools
                        ],
                        "expectedJson": {
                            "summary": "说明失败原因和修复方向。",
                            "steps": [
                                {
                                    "toolId": "code.read_file",
                                    "title": "读取失败相关文件",
                                    "purpose": "拿到足够上下文后再写 patch。",
                                    "input": {"relativePath": "package.json", "maxBytes": 40000},
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]

    def _rewrite_messages(
        self,
        current_plan: dict[str, Any],
        instruction: str,
        tools: list[dict[str, Any]],
        memory_snapshot: dict[str, Any] | None,
    ) -> list[dict[str, str]]:
        preview_acceptance_hints = build_preview_assertions(current_plan.get("requirement", ""), memory_snapshot)
        current_steps = [
            {
                "toolId": step.get("toolId"),
                "title": step.get("title"),
                "purpose": step.get("purpose"),
                "input": step.get("input"),
                "status": step.get("status"),
                "disabled": step.get("disabled", False),
            }
            for step in current_plan.get("steps", [])
            if isinstance(step, dict)
        ]
        return [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "你是本地代码 Agent 的工具计划重写器。",
                        "只输出 JSON，不要输出 Markdown，不要解释。",
                        "JSON 顶层必须是对象，包含 summary 和 steps。",
                        "steps 是重写后的完整工具计划，不是增量 patch。",
                        "每个 step 必须包含 toolId、title、purpose、input。",
                        "toolId 只能从 allowedTools 中选择。",
                        "必须保留必要的上下文读取、diff 检查、checkpoint 前置要求和验证步骤。",
                        "用户要求删除某步时，可以直接不返回该步骤；用户要求禁用某步时，可以返回该步骤并让 title/purpose 说明禁用原因，但优先使用删减后的清晰计划。",
                        "不得为了迎合用户意见而移除安全检查、diff 检查、必要验证或 checkpoint 前置写入策略。",
                        "如果使用 browser.preview_smoke，必须带上 previewAcceptanceHints 中的断言。",
                        "命令只能用于当前对话沙盒仓库，优先使用 package.json 中已有脚本或当前计划已有命令。",
                        "external. 开头的工具来自 MCP，只有用户意见明确需要外部能力时才选择。",
                    ]
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "rewriteInstruction": instruction,
                        "currentPlan": {
                            "id": current_plan.get("id"),
                            "status": current_plan.get("status"),
                            "requirement": current_plan.get("requirement"),
                            "repository": current_plan.get("repository"),
                            "sandbox": current_plan.get("sandbox"),
                            "generation": current_plan.get("generation"),
                            "audits": current_plan.get("audits", [])[-6:],
                            "steps": current_steps,
                        },
                        "memory": memory_snapshot,
                        "taskState": (memory_snapshot or {}).get("taskState") if isinstance(memory_snapshot, dict) else None,
                        "previewAcceptanceHints": preview_acceptance_hints,
                        "allowedTools": [
                            {
                                "id": tool.get("id"),
                                "source": tool.get("source", "internal"),
                                "mcpName": tool.get("mcpName"),
                                "description": tool.get("description"),
                                "riskLevel": tool.get("riskLevel"),
                                "requiresCheckpoint": tool.get("requiresCheckpoint"),
                                "inputSchema": tool.get("inputSchema"),
                            }
                            for tool in tools
                        ],
                        "expectedJson": {
                            "summary": "说明如何根据用户意见重写了计划。",
                            "steps": current_steps[:2],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]

    def _parse_json(self, raw_response: str) -> dict[str, Any]:
        text = raw_response.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise RuntimeError("模型返回的工具计划不是 JSON 对象。")
        return parsed

    def _fallback(self, conversation_id: str, reason: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
        audit = self.auditor.audit_structured_tool_plan([], tools, fallback_reason=reason)
        return {
            "source": "fallback",
            "steps": [],
            "rawResponse": "",
            "audit": audit,
            "fallbackReason": reason,
            "conversationId": conversation_id,
        }

    def _repair_fallback(self, conversation_id: str, reason: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
        audit = self.auditor.audit_structured_tool_plan([], tools, fallback_reason=reason)
        return {
            "source": "repair-loop",
            "steps": [],
            "rawResponse": "",
            "audit": audit,
            "fallbackReason": reason,
            "conversationId": conversation_id,
            "summary": "模型修复计划不可用，系统会生成确定性诊断步骤。",
        }

    def _rewrite_fallback(self, conversation_id: str, reason: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
        audit = self.auditor.audit_structured_tool_plan([], tools, fallback_reason=reason)
        return {
            "source": "rewrite",
            "steps": [],
            "rawResponse": "",
            "audit": audit,
            "fallbackReason": reason,
            "conversationId": conversation_id,
            "summary": "模型未能重写工具计划，当前计划保持不变。",
        }

    def _repair_rejected_model_plan(
        self,
        conversation_id: str,
        reason: str,
        tools: list[dict[str, Any]],
        raw_response: str,
        summary: str,
    ) -> dict[str, Any]:
        audit = self.auditor.audit_structured_tool_plan([], tools, fallback_reason=reason)
        return {
            "source": "repair-loop",
            "steps": [],
            "rawResponse": raw_response,
            "audit": audit,
            "fallbackReason": reason,
            "conversationId": conversation_id,
            "summary": summary or "模型尝试在缺少文件内容时生成 patch，系统已回退为证据收集计划。",
        }

    def _repair_allowed_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        allowed_ids = {"code.search_files", "code.read_file", "code.apply_patch", "command.run", "code.git_diff", "browser.preview_smoke"}
        return [tool for tool in tools if tool.get("id") in allowed_ids]

    def _collected_read_files(self, source_plan: dict[str, Any]) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        seen: set[str] = set()
        for step in source_plan.get("steps", []):
            if not isinstance(step, dict) or step.get("toolId") != "code.read_file":
                continue
            if step.get("status") != "completed":
                continue
            result = step.get("result") if isinstance(step.get("result"), dict) else {}
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            relative_path = str(data.get("relativePath") or (step.get("input") or {}).get("relativePath") or "").strip()
            content = data.get("content")
            if not relative_path or not isinstance(content, str) or relative_path in seen:
                continue
            files.append(
                {
                    "relativePath": relative_path,
                    "content": content[:40000],
                    "truncated": bool(data.get("truncated")) or len(content) > 40000,
                }
            )
            seen.add(relative_path)
            if len(files) >= 5:
                break
        return files

    def _patch_context_violation(self, steps: list[dict[str, Any]], read_files: list[dict[str, Any]]) -> str | None:
        patch_steps = [step for step in steps if isinstance(step, dict) and step.get("toolId") == "code.apply_patch"]
        if not patch_steps:
            return None
        allowed_targets = {str(item.get("relativePath") or "").replace("\\", "/") for item in read_files}
        if not allowed_targets:
            return "模型在没有已读取文件内容时生成了 code.apply_patch，系统已回退为证据收集计划。"
        for step in patch_steps:
            input_payload = step.get("input") if isinstance(step.get("input"), dict) else {}
            changes = input_payload.get("changes") or input_payload.get("files")
            if not isinstance(changes, list) or not changes:
                return "模型生成的 code.apply_patch 缺少 changes，系统已回退为证据收集计划。"
            for change in changes:
                if not isinstance(change, dict):
                    return "模型生成的 code.apply_patch changes 格式错误，系统已回退为证据收集计划。"
                relative_path = str(change.get("relativePath") or "").replace("\\", "/")
                if relative_path not in allowed_targets:
                    return f"模型尝试 patch 未读取过的文件：{relative_path}，系统已回退为证据收集计划。"
        return None

    def _compact_result(self, result: Any) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {
            "ok": result.get("ok"),
            "summary": result.get("summary"),
            "needsApproval": result.get("needsApproval"),
            "exitCode": data.get("exitCode"),
            "command": data.get("command"),
            "stdoutTail": data.get("stdoutTail"),
            "stderrTail": data.get("stderrTail"),
        }
