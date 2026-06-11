from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import WORKSPACE_ROOT


# 同仓库多会话并发写长期库是真实场景(FastAPI 线程池);
# read-modify-write 必须串行化,否则后写覆盖先写丢数据。
_STORE_LOCK = threading.Lock()

LONG_TERM_LIMIT = 800
PROMOTED_KINDS = {"repo", "decision", "failure", "delivery", "preview", "skill"}
PROMOTED_TAGS = {"instructions", "failure", "decision", "repair", "rollback", "checkpoint", "skill"}


class LongTermMemoryStore:
    """Workspace-level memory.

    Conversation memory stays local to a task. Long-term memory stores stable
    project facts, user decisions, repeated failures and delivery evidence that
    should influence future conversations.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or WORKSPACE_ROOT / "memory" / "long-term-memory.json"

    def namespace_for(self, repository: dict[str, Any] | None) -> str:
        repo_source = self._repo_source(repository)
        if not repo_source:
            return "workspace"
        digest = hashlib.sha1(repo_source.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"repo_{digest}"

    def list(self, repository: dict[str, Any] | None = None, include_workspace: bool = True) -> list[dict[str, Any]]:
        items = read_json(self.path, [])
        if not isinstance(items, list):
            return []
        namespace = self.namespace_for(repository)
        repo_source = self._repo_source(repository)
        allowed = {namespace}
        if include_workspace:
            allowed.add("workspace")
        return [
            item
            for item in items
            if isinstance(item, dict)
            and not item.get("forgotten")
            and self._belongs_to_namespace(item, allowed, repo_source)
        ]

    def all_items(self) -> list[dict[str, Any]]:
        items = read_json(self.path, [])
        return items if isinstance(items, list) else []

    def purge_conversation(self, conversation_id: str) -> int:
        """删除会话时连带物理清除它写入长期库的条目。

        用户删会话的意图就是"这次的痕迹别留着"——坏会话(幻觉路径、
        失败方案)的长期记忆若不清,会继续污染同仓库的后续会话。"""
        with _STORE_LOCK:
            items = self.all_items()
            kept = [item for item in items if str(item.get("conversationId") or "") != conversation_id]
            removed = len(items) - len(kept)
            if removed:
                write_json(self.path, kept)
            return removed

    def upsert_manual(
        self,
        *,
        conversation_id: str,
        repository: dict[str, Any] | None,
        title: str,
        content: str,
        kind: str = "decision",
        tags: list[str] | None = None,
        item_id: str | None = None,
        pinned: bool = False,
        importance: float = 2.8,
    ) -> dict[str, Any]:
        cleaned_title = title.strip()
        cleaned_content = content.strip()
        if not cleaned_title:
            raise RuntimeError("记忆标题不能为空。")
        if not cleaned_content:
            raise RuntimeError("记忆内容不能为空。")

        with _STORE_LOCK:
            items = self.all_items()
            by_id = {str(item.get("id")): item for item in items if item.get("id")}
            repo_source = self._repo_source(repository)
            namespace = self.namespace_for(repository)
            now = now_iso()
            target_id = item_id or self._manual_id(namespace, cleaned_title, cleaned_content)
            existing = by_id.get(target_id, {})
            before = self._review_snapshot(existing) if existing else None
            tag_set = {str(tag).strip() for tag in tags or [] if str(tag).strip()}
            tag_set.update({"long-term", "manual"})
            source_phase = self._source_phase(kind.strip() or "decision", tag_set, manual=True)
            item = {
                **existing,
                "id": target_id,
                "conversationId": conversation_id,
                "namespace": namespace,
                "repoSource": repo_source,
                "repoHead": str((repository or {}).get("head") or ""),
                "scope": "repository" if repo_source else "workspace",
                "kind": kind.strip() or "decision",
                "title": cleaned_title[:200],
                "content": cleaned_content[-5000:],
                "sourcePath": str(self.path),
                "tags": sorted(tag_set),
                "importance": max(0.1, min(float(importance or 2.8), 5.0)),
                "pinned": bool(pinned),
                "forgotten": False,
                "manual": True,
                "sourcePhase": source_phase,
                "firstSeenAt": existing.get("firstSeenAt") or now,
                "lastSeenAt": now,
                "updatedAt": now,
                "useCount": int(existing.get("useCount") or 0),
                "sourceEntryId": existing.get("sourceEntryId") or target_id,
            }
            patch = self._manual_patch(
                items=items,
                target_id=target_id,
                before=before,
                after=self._review_snapshot(item),
                namespace=namespace,
                repo_source=repo_source,
                created_at=now,
            )
            history = existing.get("patchHistory") if isinstance(existing.get("patchHistory"), list) else []
            item["lastPatch"] = patch
            item["patchHistory"] = [*history, patch][-20:]
            by_id[target_id] = item
            updated = list(by_id.values())
            updated.sort(key=lambda value: (bool(value.get("pinned")), float(value.get("importance") or 1), str(value.get("lastSeenAt") or "")), reverse=True)
            write_json(self.path, updated[:LONG_TERM_LIMIT])
            return item

    def review_manual(
        self,
        *,
        repository: dict[str, Any] | None,
        title: str,
        content: str,
        kind: str = "decision",
        tags: list[str] | None = None,
        item_id: str | None = None,
        pinned: bool = False,
        importance: float = 2.8,
    ) -> dict[str, Any]:
        cleaned_title = title.strip()
        cleaned_content = content.strip()
        items = self.all_items()
        by_id = {str(item.get("id")): item for item in items if item.get("id")}
        repo_source = self._repo_source(repository)
        namespace = self.namespace_for(repository)
        target_id = item_id or self._manual_id(namespace, cleaned_title, cleaned_content)
        existing = by_id.get(target_id, {})
        before = self._review_snapshot(existing) if existing else None
        tag_set = {str(tag).strip() for tag in tags or [] if str(tag).strip()}
        tag_set.update({"long-term", "manual"})
        source_phase = self._source_phase(kind.strip() or "decision", tag_set, manual=True)
        after = self._review_snapshot(
            {
                **existing,
                "title": cleaned_title[:200],
                "content": cleaned_content[-5000:],
                "kind": kind.strip() or "decision",
                "tags": sorted(tag_set),
                "pinned": bool(pinned),
                "importance": max(0.1, min(float(importance or 2.8), 5.0)),
                "namespace": namespace,
                "scope": "repository" if repo_source else "workspace",
                "repoSource": repo_source,
                "sourcePhase": source_phase,
            }
        )
        return {
            "itemId": target_id,
            "namespace": namespace,
            "patch": self._manual_patch(
                items=items,
                target_id=target_id,
                before=before,
                after=after,
                namespace=namespace,
                repo_source=repo_source,
                created_at=now_iso(),
            ),
        }

    def upsert_from_entries(
        self,
        conversation_id: str,
        entries: list[dict[str, Any]],
        repository: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        with _STORE_LOCK:
            return self._upsert_from_entries_locked(conversation_id, entries, repository)

    def _upsert_from_entries_locked(
        self,
        conversation_id: str,
        entries: list[dict[str, Any]],
        repository: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        current = self.all_items()
        by_id = {str(item.get("id")): item for item in current if item.get("id")}
        repo_source = self._repo_source(repository)
        repo_head = str((repository or {}).get("head") or "")
        namespace = self.namespace_for(repository)
        now = now_iso()

        for entry in entries:
            if not self._should_promote(entry):
                continue
            item_id = self._long_term_id(entry, repo_source)
            existing = by_id.get(item_id, {})
            promoted = {
                **existing,
                "id": item_id,
                "conversationId": conversation_id,
                "namespace": namespace,
                "repoSource": repo_source,
                "repoHead": repo_head,
                "scope": "repository" if repo_source else "workspace",
                "kind": entry.get("kind"),
                "title": entry.get("title"),
                "content": str(entry.get("content") or "")[-5000:],
                "sourcePath": entry.get("sourcePath"),
                "tags": sorted(set([*(entry.get("tags") or []), "long-term"])),
                "importance": max(float(entry.get("importance") or entry.get("weight") or 1.0), self._importance(entry)),
                "pinned": bool(existing.get("pinned")) or self._auto_pin(entry),
                "forgotten": bool(existing.get("forgotten", False)),
                "sourcePhase": self._source_phase(str(entry.get("kind") or ""), {str(tag) for tag in entry.get("tags", [])}),
                "firstSeenAt": existing.get("firstSeenAt") or now,
                "lastSeenAt": now,
                "useCount": int(existing.get("useCount") or 0),
                "sourceEntryId": entry.get("id"),
            }
            by_id[item_id] = promoted

        items = list(by_id.values())
        items.sort(key=lambda item: (bool(item.get("pinned")), float(item.get("importance") or 1), str(item.get("lastSeenAt") or "")), reverse=True)
        write_json(self.path, items[:LONG_TERM_LIMIT])
        return self.list(repository)

    def mark_used(self, item_ids: list[str]) -> None:
        if not item_ids:
            return
        with _STORE_LOCK:
            self._mark_used_locked(item_ids)

    def _mark_used_locked(self, item_ids: list[str]) -> None:
        used = set(item_ids)
        changed = False
        items = self.all_items()
        for item in items:
            if item.get("id") in used:
                item["lastUsedAt"] = now_iso()
                item["useCount"] = int(item.get("useCount") or 0) + 1
                changed = True
        if changed:
            write_json(self.path, items)

    def pin(self, item_id: str, pinned: bool = True) -> dict[str, Any] | None:
        return self._set_flag(item_id, "pinned", pinned)

    def forget(self, item_id: str, forgotten: bool = True) -> dict[str, Any] | None:
        return self._set_flag(item_id, "forgotten", forgotten)

    def _set_flag(self, item_id: str, key: str, value: bool) -> dict[str, Any] | None:
        with _STORE_LOCK:
            items = self.all_items()
            updated = None
            for item in items:
                if item.get("id") == item_id:
                    item[key] = value
                    item["updatedAt"] = now_iso()
                    updated = item
                    break
            if updated:
                write_json(self.path, items)
            return updated

    def _repo_source(self, repository: dict[str, Any] | None) -> str:
        return str((repository or {}).get("source") or "").strip().lower().replace("\\", "/")

    def _belongs_to_namespace(self, item: dict[str, Any], allowed: set[str], repo_source: str) -> bool:
        namespace = str(item.get("namespace") or "")
        if namespace:
            return namespace in allowed

        # Backward compatibility for memories created before namespace support.
        item_repo_source = str(item.get("repoSource") or "").strip().lower().replace("\\", "/")
        if not item_repo_source:
            return "workspace" in allowed
        return bool(repo_source and item_repo_source == repo_source)

    def _should_promote(self, entry: dict[str, Any]) -> bool:
        kind = str(entry.get("kind") or "")
        tags = {str(tag) for tag in entry.get("tags", [])}
        importance = float(entry.get("importance") or entry.get("weight") or 1.0)
        if kind == "requirement":
            return False
        if kind in PROMOTED_KINDS:
            return True
        if tags & PROMOTED_TAGS:
            return True
        return importance >= 2.4

    def _importance(self, entry: dict[str, Any]) -> float:
        kind = str(entry.get("kind") or "")
        tags = {str(tag) for tag in entry.get("tags", [])}
        base = {
            "repo": 2.4,
            "decision": 2.6,
            "failure": 2.8,
            "delivery": 2.0,
            "preview": 1.8,
            "skill": 2.0,
            "agent": 1.1,
        }.get(kind, 1.0)
        if "instructions" in tags:
            base += 1.0
        if "rollback" in tags or "checkpoint" in tags:
            base += 0.6
        if "failure" in tags or "repair" in tags:
            base += 0.5
        return min(base, 5.0)

    def _auto_pin(self, entry: dict[str, Any]) -> bool:
        tags = {str(tag) for tag in entry.get("tags", [])}
        return "instructions" in tags

    def _review_snapshot(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": str(item.get("title") or ""),
            "content": str(item.get("content") or ""),
            "kind": str(item.get("kind") or "decision"),
            "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
            "pinned": bool(item.get("pinned")),
            "importance": float(item.get("importance") or 1.0),
            "namespace": str(item.get("namespace") or ""),
            "scope": str(item.get("scope") or ""),
            "repoSource": str(item.get("repoSource") or ""),
            "sourcePhase": str(item.get("sourcePhase") or ""),
        }

    def _manual_patch(
        self,
        *,
        items: list[dict[str, Any]],
        target_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any],
        namespace: str,
        repo_source: str,
        created_at: str,
    ) -> dict[str, Any]:
        changed_fields = self._changed_fields(before, after)
        conflicts = self._manual_conflicts(items, target_id, before, after, namespace, repo_source)
        operation = "update" if before else "create"
        return {
            "operation": operation,
            "summary": self._patch_summary(operation, changed_fields, conflicts),
            "changedFields": changed_fields,
            "before": before,
            "after": after,
            "conflicts": conflicts,
            "createdAt": created_at,
        }

    def _changed_fields(self, before: dict[str, Any] | None, after: dict[str, Any]) -> list[str]:
        if not before:
            return sorted(after.keys())
        fields = ["title", "content", "kind", "tags", "pinned", "importance", "scope", "namespace", "repoSource", "sourcePhase"]
        return [field for field in fields if before.get(field) != after.get(field)]

    def _source_phase(self, kind: str, tags: set[str], manual: bool = False) -> str:
        if "model-memory-patch" in tags:
            return "模型记忆草案"
        if "memory-patch" in tags:
            return "记忆整理"
        if "runtime" in tags or "task-state" in tags:
            return "任务状态机"
        if "repair" in tags or kind == "failure":
            return "验证与修复"
        if kind == "preview":
            return "预览验证"
        if kind == "delivery":
            return "交付"
        if kind == "skill":
            return "Skill 路由"
        if kind == "repo":
            return "仓库画像"
        if manual:
            return "用户手动维护"
        if kind == "decision":
            return "用户决策"
        return "上下文召回"

    def _manual_conflicts(
        self,
        items: list[dict[str, Any]],
        target_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any],
        namespace: str,
        repo_source: str,
    ) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        if before and before.get("namespace") and before.get("namespace") != namespace:
            conflicts.append(
                {
                    "type": "namespace_mismatch",
                    "severity": "warning",
                    "summary": "正在从另一个仓库命名空间编辑这条长期记忆。",
                    "evidence": {"before": before.get("namespace"), "after": namespace},
                }
            )

        normalized_title = self._normalize_text(after.get("title"))
        normalized_content = self._normalize_text(after.get("content"))
        for item in items:
            if item.get("id") == target_id or item.get("forgotten"):
                continue
            item_namespace = str(item.get("namespace") or "")
            item_repo_source = str(item.get("repoSource") or "").strip().lower().replace("\\", "/")
            same_scope = item_namespace == namespace or (not item_namespace and item_repo_source == repo_source)
            if not same_scope:
                continue
            other_title = self._normalize_text(item.get("title"))
            if normalized_title and normalized_title == other_title:
                conflicts.append(
                    {
                        "type": "duplicate_title",
                        "severity": "warning",
                        "summary": "同一仓库命名空间里已经存在同名长期记忆。",
                        "evidence": {"itemId": item.get("id"), "title": item.get("title")},
                    }
                )
                continue
            other_content = self._normalize_text(item.get("content"))
            if normalized_content and other_content and self._content_overlap(normalized_content, other_content) >= 0.82:
                conflicts.append(
                    {
                        "type": "content_overlap",
                        "severity": "info",
                        "summary": "发现内容高度相似的长期记忆，后续可合并。",
                        "evidence": {"itemId": item.get("id"), "title": item.get("title")},
                    }
                )
        return conflicts[:5]

    def _patch_summary(self, operation: str, changed_fields: list[str], conflicts: list[dict[str, Any]]) -> str:
        action = "新增" if operation == "create" else "更新"
        fields = "、".join(changed_fields[:6]) if changed_fields else "无字段变化"
        if len(changed_fields) > 6:
            fields += f" 等 {len(changed_fields)} 项"
        suffix = f"，发现 {len(conflicts)} 个冲突提示" if conflicts else ""
        return f"{action}长期记忆：{fields}{suffix}。"

    def _normalize_text(self, value: Any) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def _content_overlap(self, left: str, right: str) -> float:
        left_terms = set(left.split())
        right_terms = set(right.split())
        if not left_terms or not right_terms:
            return 0.0
        return len(left_terms & right_terms) / max(len(left_terms | right_terms), 1)

    def _long_term_id(self, entry: dict[str, Any], repo_source: str) -> str:
        raw = "\n".join(
            [
                repo_source,
                str(entry.get("kind") or ""),
                str(entry.get("title") or ""),
                str(entry.get("content") or "")[:1200],
            ]
        )
        digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:14]
        return f"lt_{digest}"

    def _manual_id(self, namespace: str, title: str, content: str) -> str:
        raw = "\n".join([namespace, title, content[:1200]])
        digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:14]
        return f"lt_manual_{digest}"
