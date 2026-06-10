from __future__ import annotations

import json
import platform
from typing import Any

# 注入模型上下文的沙盒平台约束:模型默认倾向 Unix 命令,Windows 上会直接失败。
SANDBOX_PLATFORM_RULE = (
    f"沙盒运行在 {platform.system()} 上。"
    + (
        "禁止使用 Unix 专有命令（find/grep/ls/cat/rm/sed/awk 等）；"
        "目录与文件检索用 code.search_files / code.read_file 工具完成，"
        "需要 shell 时用 PowerShell 兼容命令（Get-ChildItem、Select-String）或 npm 脚本。"
        if platform.system() == "Windows"
        else "优先使用 POSIX 兼容命令或 npm 脚本。"
    )
)

from server_py.audit.plan_auditor import PlanAuditor
from server_py.agent.preview_assertions import build_preview_assertions
from server_py.memory.memory_service import slim_memory_for_model
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
            steps, truncate_note = self._truncate_at_contentless_write(steps)
            steps, command_note = self._normalize_test_commands(steps, repository)
            notes = [note for note in (truncate_note, command_note) if note]
            audit = self.auditor.audit_structured_tool_plan(steps, tools, notes=notes or None)
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
            steps, repair_truncate_note = self._truncate_at_contentless_write(steps)
            steps, repair_command_note = self._normalize_test_commands(steps, repository)
            context_violation = self._patch_context_violation(steps, read_files, sandbox)
            if context_violation:
                return self._repair_rejected_model_plan(
                    conversation_id=conversation_id,
                    reason=context_violation,
                    tools=tools,
                    raw_response=raw_response,
                    summary=str(parsed.get("summary") or ""),
                )
            repair_notes = [note for note in (repair_truncate_note, repair_command_note) if note]
            audit = self.auditor.audit_structured_tool_plan(
                steps, tools, notes=repair_notes or None, context_preloaded=bool(read_files)
            )
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

    def draft_continuation(
        self,
        conversation_id: str,
        source_plan: dict[str, Any],
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        tools: list[dict[str, Any]],
        memory_snapshot: dict[str, Any] | None = None,
        matched_skills: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """上一轮计划成功完成但需求尚未落地时，基于已收集证据起草下一阶段计划。

        典型链路：侦察(搜索/diff) -> 读取目标文件 -> apply_patch + 验证。
        与修复计划共用同一条护栏：只能 patch 已读取过完整内容的文件。
        """
        model = self.models.get_default_model() if self.models else None
        if not model or not model.get("enabled"):
            return self._continuation_fallback(conversation_id, "模型不可用，使用确定性读取计划继续推进。", source_plan, tools)

        try:
            allowed_tools = self._repair_allowed_tools(tools)
            read_files = self._collected_read_files(source_plan)
            search_hits = self._collected_search_hits(source_plan)
            raw_response = self.client.complete(
                model,
                self._continuation_messages(
                    source_plan=source_plan,
                    repository=repository,
                    sandbox=sandbox,
                    tools=allowed_tools,
                    memory_snapshot=memory_snapshot,
                    read_files=read_files,
                    search_hits=search_hits,
                    matched_skills=matched_skills or [],
                ),
            )
            self.metrics.record_model_call(conversation_id, "continuation_tool_plan", model, self.client.last_metrics)
            parsed = self._parse_json(raw_response)
            steps = parsed.get("steps") if isinstance(parsed.get("steps"), list) else []
            steps, truncate_note = self._truncate_at_contentless_write(steps)
            steps, command_note = self._normalize_test_commands(steps, repository)
            context_violation = self._patch_context_violation(steps, read_files, sandbox)
            if context_violation:
                fallback = self._continuation_fallback(conversation_id, context_violation, source_plan, tools)
                fallback["rawResponse"] = raw_response
                return fallback
            notes = [note for note in (truncate_note, command_note) if note]
            audit = self.auditor.audit_structured_tool_plan(
                steps, tools, notes=notes or None, context_preloaded=bool(read_files)
            )
            if audit["verdict"] == "blocked":
                fallback = self._continuation_fallback(
                    conversation_id, "模型返回的推进计划未通过工具审计，已回退确定性读取计划。", source_plan, tools
                )
                fallback["rawResponse"] = raw_response
                return fallback
            return {
                "source": "continuation",
                "steps": steps,
                "rawResponse": raw_response,
                "audit": audit,
                "fallbackReason": None,
                "summary": str(parsed.get("summary") or ""),
            }
        except Exception as error:
            return self._continuation_fallback(conversation_id, f"推进计划生成失败：{error}", source_plan, tools)

    def _continuation_messages(
        self,
        source_plan: dict[str, Any],
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        tools: list[dict[str, Any]],
        memory_snapshot: dict[str, Any] | None,
        read_files: list[dict[str, Any]],
        search_hits: list[dict[str, Any]],
        matched_skills: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        executed_steps = [
            {
                "toolId": step.get("toolId"),
                "title": step.get("title"),
                "input": step.get("input"),
                "result": self._compact_result(step.get("result")),
            }
            for step in source_plan.get("steps", [])
            if isinstance(step, dict)
        ]
        patch_rule = (
            "readFiles 中已有完整文件内容。本轮应直接产出 code.apply_patch（完整文件内容写入）+ verification.run，"
            "不要再重复搜索或重复读取同一文件。code.apply_patch 的每个 relativePath 必须来自 readFiles。"
            if read_files
            else "当前还没有读取任何文件内容。禁止生成 code.apply_patch；本轮应优先 code.read_file 读取 searchHits 中最相关的目标文件（一次读全，不超过 5 个）。"
        )
        return [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "你是本地代码 Agent 的推进计划生成器：上一轮计划已成功完成，但需求还没有真正落地为代码改动。",
                        "你的目标是用最少的轮次完成需求：读取必要文件 -> 写入修改 -> 运行验证。",
                        "只输出 JSON，不要输出 Markdown，不要解释。",
                        "JSON 顶层必须是对象，包含 summary 和 steps。",
                        "每个 step 必须包含 toolId、title、purpose、input。",
                        "toolId 只能从 allowedTools 中选择。",
                        patch_rule,
                        "code.apply_patch 的 input 必须是结构化 changes：",
                        '{"reason":"为什么这样改","changes":[{"relativePath":"文件路径","action":"write","content":"完整文件内容"}]}',
                        "新增文件同样使用 changes（relativePath 为新路径，content 为完整内容），新增文件不要求出现在 readFiles。",
                        "完成写入后必须安排 verification.run 步骤（input 用 {}，运行时会按仓库栈选择验证命令）。",
                        SANDBOX_PLATFORM_RULE,
                        "必须遵守 skillRuntime 中的约束与变更清单（changeChecklist），不要遗漏需求要求的测试文件。",
                        "必须遵守 memory.taskState：用户暂停的阶段不得推进；用户覆盖的下一步动作优先。",
                        "写入仍会等待用户确认，不要假设自动执行。",
                    ]
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "requirement": source_plan.get("requirement"),
                        "sourcePlan": {
                            "id": source_plan.get("id"),
                            "status": source_plan.get("status"),
                            "continuationSequence": source_plan.get("continuationSequence", 0),
                            "executedSteps": executed_steps,
                            "evidence": source_plan.get("evidence"),
                        },
                        "searchHits": search_hits,
                        "readFiles": read_files,
                        "patchPolicy": {
                            "canPatchNow": bool(read_files),
                            "allowedPatchTargets": [item["relativePath"] for item in read_files],
                            "rule": "code.apply_patch 只能修改 readFiles 中已有完整内容的文件；新增文件除外。",
                        },
                        "repository": repository,
                        "sandbox": sandbox,
                        "memory": slim_memory_for_model(memory_snapshot),
                        "skillRuntime": [
                            {
                                "id": skill.get("id"),
                                "name": skill.get("name"),
                                "kind": skill.get("kind"),
                                "constraints": (skill.get("runtime") or {}).get("constraints", []),
                                "pattern": (skill.get("runtime") or {}).get("pattern", {}),
                            }
                            for skill in matched_skills
                        ],
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
                            "summary": "说明本轮推进什么。",
                            "steps": [
                                {
                                    "toolId": "code.read_file",
                                    "title": "读取目标文件",
                                    "purpose": "获得完整内容后下一轮直接写入。",
                                    "input": {"relativePath": "frontend/src/routes/Article/Article.jsx", "maxBytes": 40000},
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]

    def _truncate_at_contentless_write(self, steps: list[Any]) -> tuple[list[dict[str, Any]], str | None]:
        """截断没有实际内容的写入步骤及其后续。

        模型常在还没读到文件内容时就排入空的 write/patch 步骤；直接执行会写出
        空文件。截断后由推进循环基于真实读取结果起草带内容的下一轮写入计划。
        """
        kept: list[dict[str, Any]] = []
        for step in steps if isinstance(steps, list) else []:
            if not isinstance(step, dict):
                continue
            tool_id = str(step.get("toolId") or "")
            payload = step.get("input") if isinstance(step.get("input"), dict) else {}
            if tool_id == "code.write_file" and not str(payload.get("content") or "").strip():
                return kept, (
                    f"步骤「{step.get('title')}」的 code.write_file 没有文件内容，已截断该步骤及其后续；"
                    "本轮先完成读取，下一轮会基于真实文件内容生成写入计划。"
                )
            if tool_id == "code.apply_patch":
                changes = payload.get("changes") or payload.get("files")
                has_content = isinstance(changes, list) and any(
                    isinstance(change, dict) and str(change.get("content") or "").strip() for change in changes
                )
                if not has_content:
                    return kept, (
                        f"步骤「{step.get('title')}」的 code.apply_patch 没有实际变更内容，已截断该步骤及其后续；"
                        "本轮先完成读取，下一轮会基于真实文件内容生成写入计划。"
                    )
            kept.append(step)
        return kept, None

    def _collected_search_hits(self, source_plan: dict[str, Any]) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        seen: set[str] = set()
        for step in source_plan.get("steps", []):
            if not isinstance(step, dict) or step.get("toolId") != "code.search_files":
                continue
            result = step.get("result") if isinstance(step.get("result"), dict) else {}
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            for match in data.get("matches", []) if isinstance(data.get("matches"), list) else []:
                path = str((match or {}).get("path") or "").strip()
                if path and path not in seen:
                    hits.append({"path": path, "reason": str((match or {}).get("reason") or "")[:120]})
                    seen.add(path)
                if len(hits) >= 20:
                    return hits
        return hits

    def _continuation_fallback(
        self,
        conversation_id: str,
        reason: str,
        source_plan: dict[str, Any],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        # 确定性兜底：读取侦察阶段命中的候选文件，保证链路不停摆。
        steps: list[dict[str, Any]] = []
        for hit in self._collected_search_hits(source_plan)[:4]:
            steps.append(
                {
                    "toolId": "code.read_file",
                    "title": f"读取候选文件 {hit['path']}",
                    "purpose": "获得完整文件内容，下一轮才允许生成 patch。",
                    "input": {"relativePath": hit["path"], "maxBytes": 40000},
                }
            )
        audit = self.auditor.audit_structured_tool_plan(steps, tools, fallback_reason=reason)
        return {
            "source": "continuation",
            "steps": steps,
            "rawResponse": "",
            "audit": audit,
            "fallbackReason": reason,
            "conversationId": conversation_id,
            "summary": "模型推进计划不可用，先读取候选文件收集上下文。",
        }

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
                "input": {"query": "提炼后的 2-5 个关键词", "maxResults": 12},
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
                        SANDBOX_PLATFORM_RULE,
                        "验证优先使用 verification.run（input 用 {}，运行时会按仓库栈选择验证命令并产出结构化报告）。",
                        "如果直接用 command.run 跑 vitest 测试，必须使用 `npm test -- --run`，避免 watch 模式挂起。",
                        "code.search_files 的 query 必须是 2-5 个提炼后的关键词，不能把整段需求文本当 query。",
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
                        "memory": slim_memory_for_model(memory_snapshot),
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
            "如果 readFiles 已经包含失败的测试文件或被测源码，本轮必须直接产出 code.apply_patch 修复 + 复跑验证，"
            "不允许再生成纯读取计划——重复读取会耗尽修复次数。"
            "判断修复方向时以需求原文为准：实现符合需求而测试断言错误时改测试，反之改实现。"
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
                        SANDBOX_PLATFORM_RULE,
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
                        "memory": slim_memory_for_model(memory_snapshot),
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
                        "memory": slim_memory_for_model(memory_snapshot),
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

    def _patch_context_violation(
        self,
        steps: list[dict[str, Any]],
        read_files: list[dict[str, Any]],
        sandbox: dict[str, Any] | None = None,
    ) -> str | None:
        patch_steps = [step for step in steps if isinstance(step, dict) and step.get("toolId") == "code.apply_patch"]
        if not patch_steps:
            return None
        allowed_targets = {str(item.get("relativePath") or "").replace("\\", "/") for item in read_files}
        for step in patch_steps:
            input_payload = step.get("input") if isinstance(step.get("input"), dict) else {}
            changes = input_payload.get("changes") or input_payload.get("files")
            if not isinstance(changes, list) or not changes:
                return "模型生成的 code.apply_patch 缺少 changes，系统已回退为证据收集计划。"
            for change in changes:
                if not isinstance(change, dict):
                    return "模型生成的 code.apply_patch changes 格式错误，系统已回退为证据收集计划。"
                relative_path = str(change.get("relativePath") or "").replace("\\", "/")
                if relative_path in allowed_targets:
                    continue
                if self._is_new_file(relative_path, sandbox):
                    # 沙盒中不存在的文件视为新建，不要求先读取。
                    continue
                return f"模型尝试 patch 未读取过的既有文件：{relative_path}，系统已回退为证据收集计划。"
        return None

    def _is_new_file(self, relative_path: str, sandbox: dict[str, Any] | None) -> bool:
        repo_path = (sandbox or {}).get("repoPath")
        if not repo_path or not relative_path:
            return False
        try:
            from pathlib import Path

            root = Path(str(repo_path)).resolve()
            target = (root / relative_path).resolve()
            if root != target and root not in target.parents:
                return False
            return not target.exists()
        except OSError:
            return False

    def _normalize_test_commands(
        self,
        steps: list[dict[str, Any]],
        repository: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """裸 `npm test` 在 vitest 仓库会进入 watch 模式挂死，统一补 `-- --run`。"""
        scripts = (repository or {}).get("scripts") if isinstance((repository or {}).get("scripts"), dict) else {}
        test_script = str(scripts.get("test") or "").lower()
        if "vitest" not in test_script or "--run" in test_script:
            return steps, None
        note = None
        for step in steps:
            if not isinstance(step, dict) or step.get("toolId") != "command.run":
                continue
            payload = step.get("input") if isinstance(step.get("input"), dict) else {}
            command = str(payload.get("command") or "").strip()
            if command in {"npm test", "npm run test"}:
                payload["command"] = f"{command} -- --run"
                step["input"] = payload
                note = "已把裸 `npm test` 规范化为 `npm test -- --run`，避免 vitest watch 模式挂起。"
        return steps, note

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
