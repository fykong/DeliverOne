from __future__ import annotations

from typing import Any

from server_py.core.json_io import read_json
from server_py.core.paths import AGENT_SKILLS_PATH, PROJECT_ROOT


class SkillRegistry:
    def __init__(self) -> None:
        loaded = read_json(AGENT_SKILLS_PATH, [])
        self._skills: list[dict[str, Any]] = loaded if isinstance(loaded, list) else []

    def list(self) -> list[dict[str, Any]]:
        return [self._with_absolute_path(skill) for skill in self._skills]

    def get(self, skill_id: str) -> dict[str, Any] | None:
        for skill in self._skills:
            if skill.get("id") == skill_id:
                record = self._with_absolute_path(skill)
                path = record.get("absoluteSkillPath")
                if path:
                    skill_file = PROJECT_ROOT / record["skillPath"]
                    record["content"] = skill_file.read_text(encoding="utf-8", errors="ignore") if skill_file.exists() else ""
                return record
        return None

    def match(self, requirement: str) -> list[dict[str, Any]]:
        text = requirement.lower()
        matched: list[dict[str, Any]] = []
        for skill in self._skills:
            triggers = [str(item).lower() for item in skill.get("triggers", [])]
            always_on = skill.get("id") in {"agent-delivery-flow", "repo-context"}
            if always_on or any(token in text for token in triggers):
                matched.append(self._with_content(skill))
        return matched

    def _with_absolute_path(self, skill: dict[str, Any]) -> dict[str, Any]:
        path = skill.get("skillPath")
        if not path:
            return skill
        absolute = (PROJECT_ROOT / path).resolve()
        return {**skill, "skillPath": path, "absoluteSkillPath": str(absolute)}

    def _with_content(self, skill: dict[str, Any]) -> dict[str, Any]:
        record = self._with_absolute_path(skill)
        path = record.get("skillPath")
        if not path:
            return record
        skill_file = PROJECT_ROOT / path
        record["content"] = skill_file.read_text(encoding="utf-8", errors="ignore") if skill_file.exists() else ""
        return record
