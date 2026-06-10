from __future__ import annotations

import json
from typing import Any

from server_py.audit.plan_auditor import PlanAuditor
from server_py.core.json_io import now_iso
from server_py.memory.preflight_service import PreflightService
from server_py.models.ark_client import ArkClient
from server_py.observability.metrics import MetricStore


class PlanningAgent:
    def __init__(self, preflight: PreflightService, client: ArkClient, auditor: PlanAuditor, metrics: MetricStore) -> None:
        self.preflight = preflight
        self.client = client
        self.auditor = auditor
        self.metrics = metrics

    def run(
        self,
        conversation_id: str,
        requirement: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
    ) -> dict[str, Any]:
        preflight = self.preflight.run(conversation_id, requirement, repository, sandbox)
        steps = [
            {
                "id": "preflight",
                "title": "预检",
                "detail": f"识别到 {len(preflight['matchedSkills'])} 个 Skill，{len(preflight['availableCommands'])} 个可用命令。",
                "status": "done",
            },
            {
                "id": "search-intent",
                "title": "搜索意图",
                "detail": self._search_intent_detail(preflight.get("searchIntent") or {}),
                "status": "done",
            },
        ]

        if not preflight["model"].get("enabled"):
            reply = f"模型还没有接通：{preflight['model'].get('unavailableReason')}。请先配置运行环境变量，然后重新发送需求。"
            audit = self.auditor.audit_plan(reply, preflight)
            return self._turn(conversation_id, "failed", preflight, reply, steps, [audit], preflight["model"].get("unavailableReason"))

        try:
            reply = self.client.complete(preflight["model"], self._messages(requirement, preflight))
            self.metrics.record_model_call(conversation_id, "planning", preflight["model"], self.client.last_metrics)
            audit = self.auditor.audit_plan(reply, preflight)
            return self._turn(
                conversation_id,
                "waiting_plan_confirmation",
                preflight,
                reply,
                [
                    *steps,
                    {
                        "id": "model",
                        "title": "模型调用",
                        "detail": f"{preflight['model']['displayName']} 已返回计划草案。",
                        "status": "done",
                    },
                ],
                [audit],
            )
        except Exception as error:
            reply = f"模型调用失败：{error}"
            audit = self.auditor.audit_plan(reply, preflight)
            return self._turn(conversation_id, "failed", preflight, reply, [*steps, {"id": "model", "title": "模型调用", "detail": str(error), "status": "failed"}], [audit], str(error))

    def _messages(self, requirement: str, preflight: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "你是一个本地全栈交付 Agent，产品形态参考 Codex。",
                        "你正在和真实用户对话，不要写评委导向、营销导向或自夸文案。",
                        "必须用中文回答。",
                        "你的回答必须让用户判断：你是否理解需求，是否需要澄清，下一步具体怎么执行。",
                        "你必须遵守用户请求匹配到的 Skill 内容。Skill 是流程约束，不是展示文案。",
                        "你必须遵守 memory.taskState 和 contextPack 中的任务状态机人工控制：暂停阶段不得推进，用户覆盖的下一步动作优先于默认流程。",
                        "不要声称已经修改代码，除非工具结果证明已经写入。",
                        "输出结构必须包含：需求确认、需要澄清、执行计划、风险与确认。",
                    ]
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "requirement": requirement,
                        "repository": preflight.get("repository"),
                        "sandbox": preflight.get("sandbox"),
                        "availableCommands": preflight.get("availableCommands"),
                        "matchedSkills": [
                            {
                                "id": skill.get("id"),
                                "name": skill.get("name"),
                                "description": skill.get("description"),
                                "runtime": skill.get("runtime"),
                                "content": skill.get("content", "")[:5000],
                            }
                            for skill in preflight.get("matchedSkills", [])
                        ],
                        "contextPack": preflight["memory"]["contextPack"],
                        "searchIntent": preflight.get("searchIntent"),
                        "taskLedger": preflight["memory"].get("taskLedger"),
                        "taskState": preflight["memory"].get("taskState"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]

    def _search_intent_detail(self, search_intent: dict[str, Any]) -> str:
        source = str(search_intent.get("source") or "rules")
        queries = search_intent.get("searchQueries")
        files = search_intent.get("fileHints")
        query_count = len(queries) if isinstance(queries, list) else 0
        file_count = len(files) if isinstance(files, list) else 0
        confidence = search_intent.get("confidence")
        if isinstance(confidence, int | float):
            confidence_text = f"，置信度 {confidence:.2f}"
        else:
            confidence_text = ""
        return f"{source} 生成 {query_count} 条检索线索、{file_count} 个文件提示{confidence_text}。"

    def _turn(
        self,
        conversation_id: str,
        phase: str,
        preflight: dict[str, Any],
        reply: str,
        steps: list[dict[str, Any]],
        audits: list[dict[str, Any]],
        blocked_reason: str | None = None,
    ) -> dict[str, Any]:
        turn = {
            "conversationId": conversation_id,
            "phase": phase,
            "preflight": preflight,
            "model": preflight["model"],
            "reply": reply,
            "steps": steps,
            "audits": audits,
            "createdAt": now_iso(),
        }
        if blocked_reason:
            turn["blockedReason"] = blocked_reason
        return turn
