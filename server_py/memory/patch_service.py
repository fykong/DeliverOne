from __future__ import annotations

import hashlib
import json
from typing import Any

from server_py.core.json_io import now_iso
from server_py.memory.memory_service import MemoryService
from server_py.models.ark_client import ArkClient
from server_py.models.model_config import ModelConfigService
from server_py.observability.metrics import MetricStore


class MemoryPatchService:
    """Model-assisted memory maintenance.

    The model only proposes durable memory updates. Applying a proposal still
    goes through LongTermMemoryStore so namespace isolation, conflict review and
    patch history stay in one place.
    """

    def __init__(
        self,
        client: ArkClient,
        models: ModelConfigService,
        memory: MemoryService,
        metrics: MetricStore | None = None,
    ) -> None:
        self.client = client
        self.models = models
        self.memory = memory
        self.metrics = metrics

    def draft(
        self,
        conversation_id: str,
        repository: dict[str, Any] | None,
        instruction: str = "",
        max_items: int = 4,
    ) -> dict[str, Any]:
        memory_snapshot = self.memory.snapshot(conversation_id, repository=repository)
        model = self.models.get_default_model()
        raw_response = ""
        fallback_reason = None
        source = "rules"
        proposed_items: list[dict[str, Any]] = []

        if model.get("enabled"):
            try:
                raw_response = self.client.complete(model, self._messages(memory_snapshot, instruction, max_items))
                if self.metrics:
                    self.metrics.record_model_call(conversation_id, "memory_patch", model, self.client.last_metrics)
                proposed_items = self._parse_items(raw_response)
                source = "model"
            except Exception as error:
                fallback_reason = str(error)
                proposed_items = []
        else:
            fallback_reason = model.get("unavailableReason") or "模型不可用"

        if not proposed_items:
            proposed_items = self._fallback_items(memory_snapshot, instruction, max_items)
            source = "rules" if source != "model" else "model-fallback"
            fallback_reason = fallback_reason or "模型没有返回可写入的记忆草案"

        candidates = self._review_candidates(proposed_items, repository, max_items)
        created_at = now_iso()
        draft_id = self._draft_id(conversation_id, created_at, candidates)
        namespace = self.memory.long_term_store.namespace_for(repository)
        return {
            "id": draft_id,
            "conversationId": conversation_id,
            "source": source,
            "namespace": namespace,
            "summary": self._summary(source, candidates, fallback_reason),
            "instruction": instruction,
            "rawResponse": raw_response,
            "fallbackReason": fallback_reason,
            "candidates": candidates,
            "createdAt": created_at,
        }

    def _messages(self, memory_snapshot: dict[str, Any], instruction: str, max_items: int) -> list[dict[str, str]]:
        payload = {
            "instruction": instruction,
            "taskLedger": memory_snapshot.get("taskLedger"),
            "searchIntent": memory_snapshot.get("searchIntent"),
            "recallItems": (memory_snapshot.get("recall") or {}).get("items", [])[:12],
            "longTermItems": (memory_snapshot.get("longTerm") or {}).get("items", [])[:20],
            "curatedItems": (memory_snapshot.get("curatedMemory") or {}).get("items", [])[:12],
        }
        return [
            {
                "role": "system",
                "content": (
                    "你是 DeliverOne 的 Memory Curator。"
                    "请只输出 JSON，不要输出 Markdown。"
                    "任务是从当前任务账本、召回记忆和长期记忆中，提出应该沉淀为长期记忆的草案。"
                    "不要重复已有长期记忆；不要写空泛总结；每条都必须能帮助后续 Agent 更稳定执行。"
                    "JSON 格式：{\"items\":[{\"title\":\"...\",\"content\":\"...\",\"kind\":\"decision|failure|skill|repo|delivery|preview\","
                    "\"tags\":[\"...\"],\"pinned\":true,\"importance\":3.0,\"reason\":\"为什么应该记住\"}]}。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"maxItems": max_items, "memory": payload}, ensure_ascii=False),
            },
        ]

    def _parse_items(self, raw_response: str) -> list[dict[str, Any]]:
        text = raw_response.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        payload = json.loads(text)
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def _fallback_items(self, memory_snapshot: dict[str, Any], instruction: str, max_items: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        task_ledger = memory_snapshot.get("taskLedger") if isinstance(memory_snapshot.get("taskLedger"), dict) else {}
        understanding = str(task_ledger.get("currentUnderstanding") or "").strip()
        if understanding:
            items.append(
                {
                    "title": "当前任务理解",
                    "content": understanding,
                    "kind": "decision",
                    "tags": ["task-ledger", "memory-patch"],
                    "pinned": False,
                    "importance": 2.6,
                    "reason": "任务账本里已有稳定理解，可作为后续上下文。",
                }
            )
        if instruction.strip():
            items.append(
                {
                    "title": "用户记忆维护指令",
                    "content": instruction.strip(),
                    "kind": "decision",
                    "tags": ["user-instruction", "memory-patch"],
                    "pinned": True,
                    "importance": 3.0,
                    "reason": "用户明确要求整理或维护长期记忆。",
                }
            )
        recall_items = (memory_snapshot.get("recall") or {}).get("items", [])
        for item in recall_items:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "")
            if kind not in {"decision", "failure", "delivery", "preview", "skill", "repo"}:
                continue
            content = str(item.get("content") or "").strip()
            title = str(item.get("title") or kind).strip()
            if not content or not title:
                continue
            items.append(
                {
                    "title": title[:120],
                    "content": content[:1600],
                    "kind": kind,
                    "tags": ["recall", "memory-patch", *(item.get("tags") or [])],
                    "pinned": bool(item.get("pinned")),
                    "importance": min(float(item.get("importance") or item.get("score") or 2.4), 5.0),
                    "reason": str(item.get("reason") or "召回结果显示这条信息对当前任务相关。"),
                }
            )
            if len(items) >= max_items:
                break
        return items[:max_items]

    def _review_candidates(self, items: list[dict[str, Any]], repository: dict[str, Any] | None, max_items: int) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        for raw in items:
            title = str(raw.get("title") or "").strip()
            content = str(raw.get("content") or "").strip()
            if not title or not content:
                continue
            title_key = title.lower()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            kind = str(raw.get("kind") or "decision").strip() or "decision"
            tags = [str(tag).strip() for tag in raw.get("tags", []) if str(tag).strip()] if isinstance(raw.get("tags"), list) else []
            tags = sorted(set([*tags, "model-memory-patch"]))
            candidate = {
                "id": self._candidate_id(title, content),
                "title": title[:180],
                "content": content[-4000:],
                "kind": kind,
                "tags": tags,
                "pinned": bool(raw.get("pinned", False)),
                "importance": max(0.1, min(float(raw.get("importance") or 2.8), 5.0)),
                "reason": str(raw.get("reason") or "模型建议沉淀为长期记忆。")[:500],
                "source": str(raw.get("source") or "memory-patch"),
            }
            candidate["review"] = self.memory.long_term_store.review_manual(repository=repository, **self._review_input(candidate))
            candidates.append(candidate)
            if len(candidates) >= max_items:
                break
        return candidates

    def _review_input(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": str(candidate.get("title") or ""),
            "content": str(candidate.get("content") or ""),
            "kind": str(candidate.get("kind") or "decision"),
            "tags": candidate.get("tags") if isinstance(candidate.get("tags"), list) else [],
            "pinned": bool(candidate.get("pinned")),
            "importance": float(candidate.get("importance") or 2.8),
        }

    def _summary(self, source: str, candidates: list[dict[str, Any]], fallback_reason: str | None) -> str:
        conflict_count = sum(len(((candidate.get("review") or {}).get("patch") or {}).get("conflicts") or []) for candidate in candidates)
        base = f"生成 {len(candidates)} 条长期记忆草案，来源：{source}"
        if conflict_count:
            base += f"，包含 {conflict_count} 个冲突提示"
        if fallback_reason:
            base += f"。回退原因：{fallback_reason}"
        return base

    def _draft_id(self, conversation_id: str, created_at: str, candidates: list[dict[str, Any]]) -> str:
        raw = json.dumps({"conversationId": conversation_id, "createdAt": created_at, "candidates": candidates}, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:14]
        return f"mem_patch_{digest}"

    def _candidate_id(self, title: str, content: str) -> str:
        digest = hashlib.sha1(f"{title}\n{content[:1200]}".encode("utf-8", errors="ignore")).hexdigest()[:14]
        return f"mem_candidate_{digest}"
