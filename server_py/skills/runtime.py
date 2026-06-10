from __future__ import annotations

from pathlib import Path
from typing import Any

from server_py.runtime.events import EventStore
from server_py.skills.registry import PATTERN_FIELDS, SkillRegistry


class SkillRuntime:
    """Runtime layer over static skills.

    Registry owns the catalog. Runtime owns selection evidence, constraint
    extraction, content budgets, and future progressive loading hooks.
    """

    def __init__(self, registry: SkillRegistry, events: EventStore, content_budget: int = 5000) -> None:
        self.registry = registry
        self.events = events
        self.content_budget = content_budget

    def list(self) -> list[dict[str, Any]]:
        return self.registry.list()

    def get(self, skill_id: str) -> dict[str, Any] | None:
        return self.registry.get(skill_id)

    def peek(self, requirement: str, repository: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """无副作用版本的 select：不写事件，供 Clarifier 等角色提前读取模式指引。"""
        matched = self.registry.match(requirement, self._repository_context(repository))
        return [self._runtime_pack(skill, requirement) for skill in matched]

    def select(
        self,
        conversation_id: str,
        requirement: str,
        repository: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        context_text = self._repository_context(repository)
        matched = self.registry.match(requirement, context_text)
        hydrated = [self._runtime_pack(skill, requirement) for skill in matched]
        self.events.append(
            conversation_id,
            "skill_runtime.selected",
            {
                "skillIds": [skill.get("id") for skill in hydrated],
                "kinds": {str(skill.get("id")): skill.get("kind") for skill in hydrated},
                "count": len(hydrated),
                "contentBudget": self.content_budget,
            },
            actor="runtime",
        )
        return hydrated

    def _repository_context(self, repository: dict[str, Any] | None) -> str:
        if not isinstance(repository, dict):
            return ""
        parts = [
            str(repository.get("name") or ""),
            str(repository.get("source") or ""),
            str(repository.get("description") or ""),
        ]
        scripts = repository.get("scripts")
        if isinstance(scripts, dict):
            parts.extend(str(key) for key in scripts)
        return "\n".join(part for part in parts if part)

    def _runtime_pack(self, skill: dict[str, Any], requirement: str) -> dict[str, Any]:
        content = str(skill.get("content", ""))
        constraints = self._extract_constraints(content)
        artifacts = self._discover_artifacts(skill)
        reason = self._selection_reason(skill, requirement)
        pattern = {field: skill[field] for field in PATTERN_FIELDS if skill.get(field)}
        return {
            **skill,
            "content": content[: self.content_budget],
            "runtime": {
                "selectedReason": reason,
                "kind": skill.get("kind", "process"),
                "contentChars": min(len(content), self.content_budget),
                "truncated": len(content) > self.content_budget,
                "constraints": constraints,
                "pattern": pattern,
                "references": artifacts["references"],
                "scripts": artifacts["scripts"],
            },
        }

    def _selection_reason(self, skill: dict[str, Any], requirement: str) -> str:
        if skill.get("alwaysOn") or skill.get("id") in {"agent-delivery-flow", "repo-context"}:
            return "基础流程 Skill，默认启用。"
        matched = skill.get("matchedTriggers")
        if isinstance(matched, list) and matched:
            return f"需求命中触发词：{', '.join(str(item) for item in matched[:5])}。"
        text = requirement.lower()
        triggers = [str(item) for item in skill.get("triggers", [])]
        hits = [trigger for trigger in triggers if trigger.lower() in text]
        if hits:
            return f"需求命中触发词：{', '.join(hits[:5])}。"
        return "由运行时保守选择。"

    def _extract_constraints(self, content: str) -> list[str]:
        constraints: list[str] = []
        in_constraint_section = False
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                in_constraint_section = "限制" in line or "硬限制" in line
                continue
            if not in_constraint_section:
                continue
            if line.startswith(("-", "*")):
                constraints.append(line.lstrip("-* ").strip())
            elif len(line) <= 120:
                constraints.append(line)
            if len(constraints) >= 12:
                break
        return constraints

    def _discover_artifacts(self, skill: dict[str, Any]) -> dict[str, list[str]]:
        absolute_path = skill.get("absoluteSkillPath")
        if not absolute_path:
            return {"references": [], "scripts": []}
        root = Path(absolute_path).parent
        return {
            "references": self._list_child_files(root / "references"),
            "scripts": self._list_child_files(root / "scripts"),
        }

    def _list_child_files(self, root: Path) -> list[str]:
        if not root.exists() or not root.is_dir():
            return []
        files: list[str] = []
        for item in sorted(root.rglob("*")):
            if item.is_file():
                files.append(str(item.relative_to(root)).replace("\\", "/"))
            if len(files) >= 50:
                break
        return files
