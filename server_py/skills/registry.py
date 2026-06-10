from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from server_py.core.json_io import read_json
from server_py.core.paths import AGENT_SKILLS_PATH, PROJECT_ROOT, SKILLS_CATALOG_ROOT

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

# 需求模式 Skill 在 frontmatter 中声明的结构化字段，运行时会原样透传给
# Clarifier / Planner / ToolPlanDrafter。新增字段只需要扩展这个列表。
PATTERN_FIELDS = (
    "clarifyChecklist",
    "antiPatterns",
    "locateStrategy",
    "changeChecklist",
    "verification",
    "acceptance",
)


class SkillRegistry:
    """File-first skill registry.

    每个 Skill 是 `server_py/skills/catalog/<id>/SKILL.md`（YAML frontmatter +
    正文）。新增一种需求模式 = 新增一个目录和一个 SKILL.md 文件，注册器按
    mtime 指纹热加载，不需要改任何主干代码，也不需要重启后端。
    `config/agent-skills.json` 仅作为旧版兼容入口；id 冲突时以 SKILL.md 为准。
    """

    def __init__(self) -> None:
        self._skills: list[dict[str, Any]] = []
        self._fingerprint: tuple[Any, ...] | None = None
        self._reload_if_changed()

    def list(self) -> list[dict[str, Any]]:
        self._reload_if_changed()
        return [self._with_absolute_path(skill) for skill in self._skills]

    def get(self, skill_id: str) -> dict[str, Any] | None:
        self._reload_if_changed()
        for skill in self._skills:
            if skill.get("id") == skill_id:
                return self._with_content(skill)
        return None

    def match(self, requirement: str, context_text: str = "") -> list[dict[str, Any]]:
        self._reload_if_changed()
        text = f"{requirement}\n{context_text}".lower()
        matched: list[dict[str, Any]] = []
        for skill in self._skills:
            triggers = [str(item).lower() for item in skill.get("triggers", [])]
            hits = [token for token in triggers if token and token in text]
            if self._always_on(skill) or hits:
                record = self._with_content(skill)
                record["matchedTriggers"] = hits
                matched.append(record)
        return matched

    def _always_on(self, skill: dict[str, Any]) -> bool:
        if "alwaysOn" in skill:
            return bool(skill.get("alwaysOn"))
        # 旧版 JSON 注册的基础流程 Skill 没有 alwaysOn 字段，保持原有默认启用行为。
        return skill.get("id") in {"agent-delivery-flow", "repo-context"}

    def _catalog_files(self) -> list[Path]:
        if not SKILLS_CATALOG_ROOT.exists():
            return []
        return sorted(SKILLS_CATALOG_ROOT.glob("*/SKILL.md"))

    def _current_fingerprint(self) -> tuple[Any, ...]:
        entries: list[tuple[str, int]] = []
        try:
            entries.append((str(AGENT_SKILLS_PATH), AGENT_SKILLS_PATH.stat().st_mtime_ns))
        except OSError:
            entries.append((str(AGENT_SKILLS_PATH), 0))
        for path in self._catalog_files():
            try:
                entries.append((str(path), path.stat().st_mtime_ns))
            except OSError:
                continue
        return tuple(entries)

    def _reload_if_changed(self) -> None:
        fingerprint = self._current_fingerprint()
        if fingerprint == self._fingerprint:
            return
        self._fingerprint = fingerprint
        self._skills = self._load()

    def _load(self) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        for path in self._catalog_files():
            record = self._parse_skill_file(path)
            if record and record.get("id"):
                by_id[str(record["id"])] = record
        legacy = read_json(AGENT_SKILLS_PATH, [])
        if isinstance(legacy, list):
            for item in legacy:
                if isinstance(item, dict) and item.get("id") and str(item["id"]) not in by_id:
                    by_id[str(item["id"])] = {
                        "kind": "process",
                        "registrationSource": "config/agent-skills.json",
                        **item,
                    }
        ordered = sorted(
            by_id.values(),
            key=lambda skill: (0 if self._always_on(skill) else 1, str(skill.get("id"))),
        )
        return ordered

    def _parse_skill_file(self, path: Path) -> dict[str, Any] | None:
        if yaml is None:
            return None
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
        match = _FRONTMATTER_PATTERN.match(raw.lstrip("﻿"))
        if not match:
            return None
        try:
            metadata = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            return None
        if not isinstance(metadata, dict) or not metadata.get("id"):
            return None
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        record: dict[str, Any] = {
            "kind": "process",
            "riskLevel": "medium",
            "requiresConfirmation": False,
            "triggers": [],
            "tools": [],
            **metadata,
            "skillPath": relative,
            "registrationSource": "catalog-frontmatter",
        }
        record.setdefault("name", record["id"])
        record.setdefault("description", "")
        return record

    def _with_absolute_path(self, skill: dict[str, Any]) -> dict[str, Any]:
        path = skill.get("skillPath")
        if not path:
            return dict(skill)
        absolute = (PROJECT_ROOT / path).resolve()
        return {**skill, "skillPath": path, "absoluteSkillPath": str(absolute)}

    def _with_content(self, skill: dict[str, Any]) -> dict[str, Any]:
        record = self._with_absolute_path(skill)
        path = record.get("skillPath")
        if not path:
            return record
        skill_file = PROJECT_ROOT / path
        raw = skill_file.read_text(encoding="utf-8", errors="ignore") if skill_file.exists() else ""
        # 正文注入模型时不重复 frontmatter，结构化字段已在 record 顶层。
        record["content"] = _FRONTMATTER_PATTERN.sub("", raw.lstrip("﻿"), count=1)
        return record
