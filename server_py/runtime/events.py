from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from server_py.core.json_io import now_iso
from server_py.core.paths import conversation_root


class EventStore:
    """Codex-style append-only event stream for each conversation."""

    def append(self, conversation_id: str, event_type: str, payload: dict[str, Any] | None = None, actor: str = "runtime") -> dict[str, Any]:
        event = {
            "id": f"evt_{uuid4().hex[:12]}",
            "conversationId": conversation_id,
            "type": event_type,
            "actor": actor,
            "payload": payload or {},
            "createdAt": now_iso(),
        }
        path = conversation_root(conversation_id) / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def list(self, conversation_id: str, limit: int = 200) -> list[dict[str, Any]]:
        path = conversation_root(conversation_id) / "events.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows[-limit:]

