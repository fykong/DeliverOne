from __future__ import annotations

from typing import Any
from uuid import uuid4

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import conversation_root
from server_py.runtime.events import EventStore


class ApprovalStore:
    def __init__(self, events: EventStore) -> None:
        self.events = events

    def list(self, conversation_id: str) -> list[dict[str, Any]]:
        approvals = read_json(self._path(conversation_id), [])
        return approvals if isinstance(approvals, list) else []

    def grant(
        self,
        conversation_id: str,
        tool_id: str,
        risk_level: str,
        scope: str = "session",
        command: str | None = None,
        note: str | None = None,
        request_event_id: str | None = None,
    ) -> dict[str, Any]:
        if scope not in {"once", "turn", "session"}:
            raise RuntimeError("授权 scope 只能是 once、turn 或 session。")
        grant = {
            "id": f"grant_{uuid4().hex[:10]}",
            "conversationId": conversation_id,
            "toolId": tool_id,
            "riskLevel": risk_level,
            "scope": scope,
            "command": command,
            "note": note,
            "requestEventId": request_event_id,
            "decision": "granted",
            "active": True,
            "createdAt": now_iso(),
            "usedAt": None,
            "revokedAt": None,
            "deniedAt": None,
        }
        approvals = self.list(conversation_id)
        approvals.append(grant)
        self._save(conversation_id, approvals)
        self.events.append(
            conversation_id,
            "approval.granted",
            {"grantId": grant["id"], "toolId": tool_id, "scope": scope, "requestEventId": request_event_id},
            actor="user",
        )
        return grant

    def deny(
        self,
        conversation_id: str,
        tool_id: str,
        risk_level: str,
        reason: str,
        request_event_id: str | None = None,
        command: str | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise RuntimeError("拒绝审批必须填写原因。")
        record = {
            "id": f"deny_{uuid4().hex[:10]}",
            "conversationId": conversation_id,
            "toolId": tool_id,
            "riskLevel": risk_level,
            "scope": "once",
            "command": command,
            "note": reason.strip(),
            "requestEventId": request_event_id,
            "decision": "denied",
            "active": False,
            "createdAt": now_iso(),
            "usedAt": None,
            "revokedAt": None,
            "deniedAt": now_iso(),
        }
        approvals = self.list(conversation_id)
        approvals.append(record)
        self._save(conversation_id, approvals)
        self.events.append(
            conversation_id,
            "approval.denied",
            {"decisionId": record["id"], "toolId": tool_id, "riskLevel": risk_level, "reason": record["note"], "requestEventId": request_event_id},
            actor="user",
        )
        return record

    def revoke(self, conversation_id: str, grant_id: str) -> dict[str, Any]:
        approvals = self.list(conversation_id)
        for grant in approvals:
            if grant.get("id") == grant_id:
                grant["active"] = False
                grant["decision"] = "revoked"
                grant["revokedAt"] = now_iso()
                self._save(conversation_id, approvals)
                self.events.append(conversation_id, "approval.revoked", {"grantId": grant_id}, actor="user")
                return grant
        raise RuntimeError("授权记录不存在。")

    def consume_matching(self, conversation_id: str, tool_id: str, risk_level: str, payload: Any) -> dict[str, Any] | None:
        approvals = self.list(conversation_id)
        command = self._command_text(payload)
        matched: dict[str, Any] | None = None
        for grant in approvals:
            if not grant.get("active"):
                continue
            if grant.get("toolId") not in {tool_id, "*"}:
                continue
            if grant.get("riskLevel") not in {risk_level, "*"}:
                continue
            grant_command = str(grant.get("command") or "").strip()
            if grant_command and grant_command != command:
                continue
            matched = grant
            break

        if not matched:
            return None
        matched["usedAt"] = now_iso()
        if matched.get("scope") == "once":
            matched["active"] = False
        self._save(conversation_id, approvals)
        self.events.append(
            conversation_id,
            "approval.consumed",
            {"grantId": matched["id"], "toolId": tool_id, "riskLevel": risk_level},
            actor="runtime",
        )
        return matched

    def _path(self, conversation_id: str):
        return conversation_root(conversation_id) / "approvals.json"

    def _save(self, conversation_id: str, approvals: list[dict[str, Any]]) -> None:
        write_json(self._path(conversation_id), approvals)

    def _command_text(self, payload: Any) -> str:
        if isinstance(payload, dict):
            value = payload.get("command") or payload.get("cmd") or ""
            if isinstance(value, list):
                return " ".join(str(item) for item in value)
            return str(value).strip()
        return str(payload).strip()
