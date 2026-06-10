from __future__ import annotations

from pathlib import Path
from typing import Any

from server_py.runtime.events import EventStore
from server_py.skills.registry import SkillRegistry


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

    def select(self, conversation_id: str, requirement: str) -> list[dict[str, Any]]:
        matched = self.registry.match(requirement)
        hydrated = [self._runtime_pack(skill, requirement) for skill in matched]
        self.events.append(
            conversation_id,
            "skill_runtime.selected",
            {
                "skillIds": [skill.get("id") for skill in hydrated],
                "count": len(hydrated),
                "contentBudget": self.content_budget,
            },
            actor="runtime",
        )
        return hydrated

    def _runtime_pack(self, skill: dict[str, Any], requirement: str) -> dict[str, Any]:
        content = str(skill.get("content", ""))
        constraints = self._extract_constraints(content)
        artifacts = self._discover_artifacts(skill)
        reason = self._selection_reason(skill, requirement)
        return {
            **skill,
            "content": content[: self.content_budget],
            "runtime": {
                "selectedReason": reason,
                "contentChars": min(len(content), self.content_budget),
                "truncated": len(content) > self.content_budget,
                "constraints": constraints,
                "references": artifacts["references"],
                "scripts": artifacts["scripts"],
            },
        }

    def _selection_reason(self, skill: dict[str, Any], requirement: str) -> str:
        if skill.get("id") in {"agent-delivery-flow", "repo-context"}:
            return "基础流程 Skill，默认启用。"
        text = requirement.lower()
        triggers = [str(item) for item in skill.get("triggers", [])]
        matched = [trigger for trigger in triggers if trigger.lower() in text]
        if matched:
            return f"需求命中触发词：{', '.join(matched[:5])}。"
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
