from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import WORKSPACE_ROOT
from server_py.memory.long_term_store import LongTermMemoryStore


SECTIONS = [
    "constraints",
    "decisions",
    "knownFailures",
    "repairRecipes",
    "verificationRecipes",
    "uiPreferences",
    "doNotRepeat",
]

SECTION_LABELS = {
    "constraints": "项目约束",
    "decisions": "用户决策",
    "knownFailures": "已知失败",
    "repairRecipes": "修复策略",
    "verificationRecipes": "验证策略",
    "uiPreferences": "界面偏好",
    "doNotRepeat": "不要重复",
}

SECTION_IMPORTANCE = {
    "constraints": 3.6,
    "uiPreferences": 3.4,
    "doNotRepeat": 3.3,
    "knownFailures": 3.2,
    "repairRecipes": 3.1,
    "decisions": 2.9,
    "verificationRecipes": 2.6,
}


class MemoryCurator:
    """Maintains source-backed, repository-scoped memory files.

    The Curator is the write gate for durable memory. A model can later produce
    proposed memory updates, but this class owns dedupe, namespace isolation,
    source evidence, markdown rendering and append-only audit events.
    """

    def __init__(
        self,
        root: Path | None = None,
        namespace_store: LongTermMemoryStore | None = None,
    ) -> None:
        self.root = root or WORKSPACE_ROOT / "memory"
        self.namespace_store = namespace_store or LongTermMemoryStore()

    def curate(
        self,
        conversation_id: str,
        entries: list[dict[str, Any]],
        patterns: list[dict[str, Any]],
        repository: dict[str, Any] | None,
    ) -> dict[str, Any]:
        namespace = self.namespace_store.namespace_for(repository)
        repo_source = str((repository or {}).get("source") or "")
        repo_dir = self._repo_dir(namespace)
        global_path = self.root / "global" / "user-preferences.json"
        event_log_path = self.root / "events" / "memory-events.jsonl"
        repo_memory_path = repo_dir / "repo-memory.json"
        repo_markdown_path = repo_dir / "repo-memory.md"
        repair_recipes_path = repo_dir / "repair-recipes.json"
        verification_recipes_path = repo_dir / "verification-recipes.json"

        repo_memory = self._default_repo_memory(namespace, repo_source)
        repo_memory.update(read_json(repo_memory_path, {}))
        repo_memory["namespace"] = namespace
        repo_memory["repoSource"] = repo_source
        repo_memory.setdefault("sections", {})
        for section in SECTIONS:
            repo_memory["sections"].setdefault(section, [])

        global_memory = self._default_global_memory()
        global_memory.update(read_json(global_path, {}))
        global_memory.setdefault("items", [])

        updates = self._updates_from_entries(conversation_id, entries, patterns, repository, namespace)
        new_events: list[dict[str, Any]] = []

        for update in updates:
            if update["scope"] == "workspace":
                changed = self._merge_item(global_memory["items"], update)
            else:
                changed = self._merge_item(repo_memory["sections"][update["section"]], update)
            if changed:
                new_events.append(
                    {
                        "id": self._event_id(update["id"], now_iso()),
                        "type": "memory.curated",
                        "conversationId": conversation_id,
                        "namespace": update["namespace"],
                        "scope": update["scope"],
                        "section": update["section"],
                        "itemId": update["id"],
                        "title": update["title"],
                        "evidenceIds": update.get("evidenceIds", []),
                        "createdAt": now_iso(),
                    }
                )

        repo_memory["updatedAt"] = now_iso()
        global_memory["updatedAt"] = now_iso()

        self._sort_sections(repo_memory)
        global_memory["items"] = self._sort_items(global_memory["items"])[:80]

        write_json(repo_memory_path, repo_memory)
        write_json(global_path, global_memory)
        write_json(repair_recipes_path, repo_memory["sections"]["repairRecipes"])
        write_json(verification_recipes_path, repo_memory["sections"]["verificationRecipes"])
        repo_markdown_path.parent.mkdir(parents=True, exist_ok=True)
        repo_markdown_path.write_text(self._markdown(repo_memory), encoding="utf-8")
        self._append_events(event_log_path, new_events)

        items = self.entries_for(repository)
        return {
            "namespace": namespace,
            "repoSource": repo_source,
            "repoMemoryPath": str(repo_memory_path),
            "repoMemoryMarkdownPath": str(repo_markdown_path),
            "repairRecipesPath": str(repair_recipes_path),
            "verificationRecipesPath": str(verification_recipes_path),
            "globalPreferencesPath": str(global_path),
            "eventLogPath": str(event_log_path),
            "counts": {
                **{section: len(repo_memory["sections"].get(section, [])) for section in SECTIONS},
                "globalPreferences": len(global_memory.get("items", [])),
                "total": len(items),
            },
            "items": items[:24],
            "updatedAt": repo_memory["updatedAt"],
        }

    def entries_for(self, repository: dict[str, Any] | None) -> list[dict[str, Any]]:
        namespace = self.namespace_store.namespace_for(repository)
        repo_memory_path = self._repo_dir(namespace) / "repo-memory.json"
        global_path = self.root / "global" / "user-preferences.json"
        repo_memory = read_json(repo_memory_path, {})
        global_memory = read_json(global_path, {})
        entries: list[dict[str, Any]] = []

        for section in SECTIONS:
            for item in (repo_memory.get("sections") or {}).get(section, []):
                entries.append(self._entry_from_curated_item(item, repo_memory_path, "repository"))

        for item in global_memory.get("items", []):
            entries.append(self._entry_from_curated_item(item, global_path, "workspace"))

        return [entry for entry in entries if entry.get("content")]

    def _updates_from_entries(
        self,
        conversation_id: str,
        entries: list[dict[str, Any]],
        patterns: list[dict[str, Any]],
        repository: dict[str, Any] | None,
        namespace: str,
    ) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = []
        repo_source = str((repository or {}).get("source") or "")
        for entry in entries:
            update = self._update_from_entry(conversation_id, entry, namespace, repo_source)
            if update:
                updates.append(update)
            if self._entry_should_create_do_not_repeat(entry):
                updates.append(
                    self._make_update(
                        conversation_id,
                        namespace,
                        repo_source,
                        "doNotRepeat",
                        str(entry.get("title") or "不要重复"),
                        str(entry.get("content") or ""),
                        entry,
                        0.76,
                    )
                )
            global_update = self._global_preference_update(conversation_id, entry, namespace)
            if global_update:
                updates.append(global_update)

        for pattern in patterns:
            update = self._update_from_pattern(conversation_id, pattern, namespace, repo_source)
            if update:
                updates.append(update)
        return updates

    def _update_from_entry(
        self,
        conversation_id: str,
        entry: dict[str, Any],
        namespace: str,
        repo_source: str,
    ) -> dict[str, Any] | None:
        kind = str(entry.get("kind") or "")
        tags = {str(tag) for tag in entry.get("tags", [])}
        content = str(entry.get("content") or "").strip()
        if not content or self._is_noise(content):
            return None

        section = ""
        title = str(entry.get("title") or kind or "记忆")
        confidence = 0.72

        if "instructions" in tags:
            section = "constraints"
            confidence = 0.88
        elif kind == "decision":
            section = "decisions"
            confidence = 0.82
        elif kind == "failure":
            section = "knownFailures"
            confidence = 0.8
        elif kind in {"delivery", "preview"} and self._looks_successful(content):
            section = "verificationRecipes"
            confidence = 0.7
        else:
            return None

        return self._make_update(conversation_id, namespace, repo_source, section, title, content, entry, confidence)

    def _global_preference_update(
        self,
        conversation_id: str,
        entry: dict[str, Any],
        namespace: str,
    ) -> dict[str, Any] | None:
        kind = str(entry.get("kind") or "")
        content = str(entry.get("content") or "").strip()
        if kind != "decision" or not self._looks_like_user_preference(content):
            return None
        return self._make_update(
            conversation_id,
            namespace,
            "",
            "uiPreferences",
            str(entry.get("title") or "用户偏好"),
            content,
            entry,
            0.78,
            scope="workspace",
        )

    def _update_from_pattern(
        self,
        conversation_id: str,
        pattern: dict[str, Any],
        namespace: str,
        repo_source: str,
    ) -> dict[str, Any] | None:
        outcome = str(pattern.get("outcome") or "")
        if outcome == "failure":
            section = "repairRecipes"
        elif outcome == "success":
            section = "verificationRecipes"
        else:
            return None
        content = str(pattern.get("content") or pattern.get("recommendedAction") or "")
        if not content.strip():
            return None
        return self._make_update(
            conversation_id,
            namespace,
            repo_source,
            section,
            str(pattern.get("title") or SECTION_LABELS[section]),
            content,
            pattern,
            0.74,
        )

    def _make_update(
        self,
        conversation_id: str,
        namespace: str,
        repo_source: str,
        section: str,
        title: str,
        content: str,
        source: dict[str, Any],
        confidence: float,
        scope: str = "repository",
    ) -> dict[str, Any]:
        item_id = self._item_id(namespace, section, title, content)
        return {
            "id": item_id,
            "namespace": namespace,
            "repoSource": repo_source,
            "conversationId": conversation_id,
            "section": section,
            "scope": scope,
            "title": title[:140],
            "content": content[-1800:],
            "evidenceIds": [str(source.get("id") or source.get("sourceEntryId") or item_id)],
            "sourcePaths": [str(source.get("sourcePath") or "")],
            "tags": sorted({"curated", section, *(source.get("tags") or [])}),
            "confidence": round(confidence, 3),
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
        }

    def _merge_item(self, items: list[dict[str, Any]], update: dict[str, Any]) -> bool:
        for item in items:
            if item.get("id") == update["id"]:
                item["updatedAt"] = now_iso()
                item["lastSeenAt"] = now_iso()
                item["seenCount"] = int(item.get("seenCount") or 1) + 1
                item["confidence"] = max(float(item.get("confidence") or 0), float(update.get("confidence") or 0))
                item["evidenceIds"] = sorted(set([*(item.get("evidenceIds") or []), *(update.get("evidenceIds") or [])]))
                item["sourcePaths"] = sorted(set([*(item.get("sourcePaths") or []), *(update.get("sourcePaths") or [])]))
                return False
        items.append({**update, "firstSeenAt": update["createdAt"], "lastSeenAt": update["updatedAt"], "seenCount": 1})
        return True

    def _sort_sections(self, repo_memory: dict[str, Any]) -> None:
        sections = repo_memory.setdefault("sections", {})
        for section in SECTIONS:
            sections[section] = self._sort_items(sections.get(section, []))[:80]

    def _sort_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            items,
            key=lambda item: (
                float(item.get("confidence") or 0),
                int(item.get("seenCount") or 0),
                str(item.get("lastSeenAt") or item.get("updatedAt") or ""),
            ),
            reverse=True,
        )

    def _entry_from_curated_item(self, item: dict[str, Any], source_path: Path, scope: str) -> dict[str, Any]:
        section = str(item.get("section") or "curated")
        return {
            "id": str(item.get("id") or ""),
            "kind": "curated",
            "title": f"{SECTION_LABELS.get(section, section)}：{item.get('title')}",
            "content": str(item.get("content") or ""),
            "sourcePath": str(source_path),
            "tags": sorted(set([*(item.get("tags") or []), "curated", section])),
            "scope": scope,
            "importance": SECTION_IMPORTANCE.get(section, 2.4),
            "pinned": section in {"constraints", "uiPreferences", "doNotRepeat"},
            "createdAt": item.get("createdAt"),
        }

    def _repo_dir(self, namespace: str) -> Path:
        return self.root / "repos" / namespace

    def _default_repo_memory(self, namespace: str, repo_source: str) -> dict[str, Any]:
        return {
            "version": 1,
            "namespace": namespace,
            "repoSource": repo_source,
            "sections": {section: [] for section in SECTIONS},
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
        }

    def _default_global_memory(self) -> dict[str, Any]:
        return {"version": 1, "scope": "workspace", "items": [], "createdAt": now_iso(), "updatedAt": now_iso()}

    def _markdown(self, repo_memory: dict[str, Any]) -> str:
        lines = [
            "# 仓库记忆",
            "",
            f"Namespace: `{repo_memory.get('namespace')}`",
            f"Repo: `{repo_memory.get('repoSource') or 'workspace'}`",
            f"Updated: `{repo_memory.get('updatedAt')}`",
            "",
        ]
        for section in SECTIONS:
            items = repo_memory.get("sections", {}).get(section, [])
            lines.extend([f"## {SECTION_LABELS[section]}", ""])
            if not items:
                lines.extend(["暂无。", ""])
                continue
            for item in items[:20]:
                lines.extend(
                    [
                        f"- **{item.get('title')}**",
                        f"  - 置信度：{item.get('confidence')}",
                        f"  - 证据：{', '.join(item.get('evidenceIds') or [])}",
                        f"  - 内容：{str(item.get('content') or '').replace(chr(10), ' ')[:500]}",
                    ]
                )
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _append_events(self, path: Path, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            for event in events:
                file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _item_id(self, namespace: str, section: str, title: str, content: str) -> str:
        digest = hashlib.sha1(f"{namespace}\n{section}\n{title}\n{content[:1200]}".encode("utf-8", errors="ignore")).hexdigest()[:14]
        return f"cur_{digest}"

    def _event_id(self, item_id: str, created_at: str) -> str:
        digest = hashlib.sha1(f"{item_id}\n{created_at}".encode("utf-8", errors="ignore")).hexdigest()[:14]
        return f"mem_evt_{digest}"

    def _looks_successful(self, content: str) -> bool:
        lowered = content.lower()
        return any(token in lowered for token in ["pass", "passed", "ok", "completed", "通过", "完成", "成功", "交付包"])

    def _is_noise(self, content: str) -> bool:
        """流程状态记录和占位符不是知识,绝不能进入策展记忆——
        它们重要度高还常被置顶,会把真实约束/偏好挤出召回窗口。"""
        head = content.strip()[:80]
        placeholder_prefixes = ("未发现", "暂无", "尚无", "没有检测到")
        process_markers = ("计划已确认", "工具计划已执行", "工具计划已生成", "已进入代码定位阶段", "checkpoint 门禁", "阶段完成", "执行结束")
        return head.startswith(placeholder_prefixes) or any(marker in content[:200] for marker in process_markers)

    def _looks_like_user_preference(self, content: str) -> bool:
        if self._is_noise(content):
            return False
        lowered = content.lower()
        keywords = ["中文", "简洁", "干净", "不要", "必须", "希望", "默认", "按钮", "页面", "配色", "用户"]
        ascii_keywords = ["ui", "ux", "simple", "clean", "chinese", "button", "layout", "default", "prefer", "must", "do not"]
        return any(keyword in content for keyword in keywords) or any(keyword in lowered for keyword in ascii_keywords)

    def _contains_negative_instruction(self, content: str) -> bool:
        lowered = content.lower()
        keywords = ["不要", "不能", "不需要", "避免", "禁止", "别再"]
        ascii_keywords = ["do not", "don't", "avoid", "never", "must not", "no longer"]
        return any(keyword in content for keyword in keywords) or any(keyword in lowered for keyword in ascii_keywords)

    def _entry_should_create_do_not_repeat(self, entry: dict[str, Any]) -> bool:
        kind = str(entry.get("kind") or "")
        content = str(entry.get("content") or "")
        return kind in {"decision", "failure"} and self._contains_negative_instruction(content)
