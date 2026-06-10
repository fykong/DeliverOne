from __future__ import annotations

from typing import Any

from server_py.memory.memory_service import MemoryService
from server_py.memory.search_intent import SearchIntentService
from server_py.models.model_config import ModelConfigService
from server_py.skills.runtime import SkillRuntime


class PreflightService:
    def __init__(
        self,
        model_config: ModelConfigService,
        skills: SkillRuntime,
        memory: MemoryService,
        search_intent: SearchIntentService | None = None,
    ) -> None:
        self.model_config = model_config
        self.skills = skills
        self.memory = memory
        self.search_intent = search_intent

    def run(
        self,
        conversation_id: str,
        requirement: str | None,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
    ) -> dict[str, Any]:
        model = self.model_config.get_default_model()
        matched_skills = self.skills.select(conversation_id, requirement or "")
        available_commands = repository.get("scripts", {}) if repository else {}
        required_confirmations: list[str] = []

        if requirement and requirement.strip():
            self.memory.record_requirement(conversation_id, requirement)
        self.memory.capture_repository(conversation_id, repository, sandbox)
        self.memory.record_matched_skills(conversation_id, matched_skills)
        initial_memory = self.memory.snapshot(conversation_id, repository, requirement, matched_skills, sandbox=sandbox)
        search_intent = (
            self.search_intent.generate(
                conversation_id=conversation_id,
                requirement=requirement,
                repository=repository,
                sandbox=sandbox,
                model=model,
                memory_snapshot=initial_memory,
                available_commands=available_commands,
            )
            if self.search_intent
            else {}
        )
        memory = self.memory.snapshot(conversation_id, repository, requirement, matched_skills, search_intent=search_intent, sandbox=sandbox)

        if not sandbox:
            required_confirmations.append("需要先为当前对话创建沙盒。")
        if not model.get("enabled"):
            required_confirmations.append(f"当前默认模型不可用：{model.get('unavailableReason') or '未知原因'}")

        return {
            "conversationId": conversation_id,
            "repository": repository,
            "sandbox": sandbox,
            "model": model,
            "matchedSkills": matched_skills,
            "memory": memory,
            "searchIntent": search_intent,
            "requiredConfirmations": required_confirmations,
            "availableCommands": available_commands,
        }
