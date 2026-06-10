from __future__ import annotations

import json
from typing import Any

from server_py.core.json_io import now_iso
from server_py.memory.preflight_service import PreflightService
from server_py.models.ark_client import ArkClient


class ExecutorAgent:
    def __init__(self, preflight: PreflightService, client: ArkClient) -> None:
        self.preflight = preflight
        self.client = client

    def prepare(
        self,
        conversation_id: str,
        requirement: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        preflight = self.preflight.run(conversation_id, requirement, repository, sandbox)
        steps = [
            {
                "id": "executor-preflight",
                "title": "执行预检",
                "detail": f"已加载 {len(preflight['matchedSkills'])} 个流程 Skill 和 {len(tools)} 个工具定义。",
                "status": "done",
            }
        ]

        if not sandbox:
            reply = "当前对话还没有沙盒仓库，执行阶段已阻断。请先接入本地路径或 GitHub 仓库。"
            return self._turn(conversation_id, "execution_blocked", preflight, reply, steps, "缺少沙盒。")

        if not preflight["model"].get("enabled"):
            reply = f"模型不可用：{preflight['model'].get('unavailableReason')}。执行阶段不能继续。"
            return self._turn(conversation_id, "execution_blocked", preflight, reply, steps, preflight["model"].get("unavailableReason"))

        reply = self.client.complete(preflight["model"], self._messages(requirement, preflight, tools))
        return self._turn(
            conversation_id,
            "execution_ready",
            preflight,
            reply,
            [
                *steps,
                {
                    "id": "executor-plan",
                    "title": "执行方案生成",
                    "detail": "ExecutorAgent 已基于流程 Skill、工具目录和当前沙盒上下文生成下一步执行方案。",
                    "status": "done",
                },
            ],
        )

    def _messages(self, requirement: str, preflight: dict[str, Any], tools: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "你是本地全栈交付系统的 ExecutorAgent。",
                        "必须使用中文。",
                        "你现在只负责生成执行方案和工具调用边界，不直接声称已经修改代码。",
                        "所有修改必须通过工具完成，优先使用 code.apply_patch 进行多文件修改。",
                        "写入前必须有 checkpoint；非可信命令必须请求用户确认。",
                        "你必须遵守 matchedSkills 里的 SKILL.md 内容。",
                        "输出必须包含：执行目标、拟调用工具、修改文件边界、验证命令、回退策略、需要用户确认的事项。",
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
                        "tools": tools,
                        "matchedSkills": [
                            {
                                "id": skill.get("id"),
                                "name": skill.get("name"),
                                "description": skill.get("description"),
                                "content": skill.get("content", "")[:5000],
                            }
                            for skill in preflight.get("matchedSkills", [])
                        ],
                        "contextPack": preflight["memory"]["contextPack"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]

    def _turn(
        self,
        conversation_id: str,
        phase: str,
        preflight: dict[str, Any],
        reply: str,
        steps: list[dict[str, Any]],
        blocked_reason: str | None = None,
    ) -> dict[str, Any]:
        turn = {
            "conversationId": conversation_id,
            "phase": phase,
            "preflight": preflight,
            "model": preflight["model"],
            "reply": reply,
            "steps": steps,
            "audits": [],
            "createdAt": now_iso(),
        }
        if blocked_reason:
            turn["blockedReason"] = blocked_reason
        return turn
