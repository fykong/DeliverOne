from __future__ import annotations

from typing import Any
from uuid import uuid4

from server_py.core.json_io import now_iso


PHASES = [
    "idle",
    "repository_required",
    "sandbox_creating",
    "sandbox_ready",
    "preflight",
    "clarification",
    "planning",
    "waiting_plan_confirmation",
    "waiting_tool_plan_confirmation",
    "waiting_sandbox",
    "locating_code",
    "ready_to_edit",
    "checkpoint_before_write",
    "editing",
    "verifying",
    "reviewing",
    "delivery_ready",
    "execution_blocked",
    "execution_ready",
    "tool_plan_approved",
    "tool_plan_running",
    "tool_plan_completed",
    "tool_plan_failed",
    "tool_plan_waiting_approval",
    "completed",
    "failed",
]


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"repository_required", "sandbox_creating", "sandbox_ready", "planning", "clarification", "failed"},
    "repository_required": {"sandbox_creating", "sandbox_ready", "failed"},
    "sandbox_creating": {"sandbox_ready", "repository_required", "failed"},
    "sandbox_ready": {"preflight", "clarification", "planning", "waiting_plan_confirmation", "waiting_tool_plan_confirmation", "failed"},
    "preflight": {"clarification", "planning", "waiting_plan_confirmation", "failed"},
    "clarification": {"planning", "waiting_plan_confirmation", "failed"},
    "planning": {"clarification", "waiting_plan_confirmation", "failed"},
    "waiting_plan_confirmation": {"clarification", "planning", "waiting_sandbox", "ready_to_edit", "waiting_tool_plan_confirmation", "failed"},
    "waiting_sandbox": {"sandbox_creating", "sandbox_ready", "planning", "failed"},
    "ready_to_edit": {"waiting_tool_plan_confirmation", "checkpoint_before_write", "editing", "verifying", "delivery_ready", "failed"},
    "waiting_tool_plan_confirmation": {"tool_plan_approved", "tool_plan_running", "tool_plan_failed", "failed"},
    "tool_plan_approved": {"tool_plan_running", "tool_plan_failed", "failed"},
    "tool_plan_running": {"tool_plan_completed", "tool_plan_failed", "tool_plan_waiting_approval", "failed"},
    "tool_plan_waiting_approval": {"tool_plan_running", "tool_plan_completed", "tool_plan_failed", "failed"},
    "tool_plan_failed": {"waiting_tool_plan_confirmation", "planning", "failed"},
    "tool_plan_completed": {"delivery_ready", "completed", "planning", "clarification", "waiting_plan_confirmation", "sandbox_ready", "failed"},
    "checkpoint_before_write": {"editing", "execution_blocked", "failed"},
    "editing": {"verifying", "reviewing", "delivery_ready", "execution_blocked", "failed"},
    "verifying": {"reviewing", "delivery_ready", "execution_blocked", "failed"},
    "reviewing": {"delivery_ready", "editing", "execution_blocked", "failed"},
    "delivery_ready": {"completed", "planning", "sandbox_ready", "failed"},
    "execution_blocked": {"planning", "waiting_tool_plan_confirmation", "failed"},
    "execution_ready": {"tool_plan_running", "editing", "verifying", "failed"},
    "completed": {"planning", "clarification", "sandbox_ready"},
    "failed": {"planning", "clarification", "sandbox_ready", "repository_required"},
}


class RuntimeStateMachine:
    """Codex-inspired conversation runtime state reducer.

    The first version records and validates transitions without hard blocking
    legacy flows. Later Orchestrator work can turn strict mode on per endpoint.
    """

    def describe(self) -> dict[str, Any]:
        return {
            "phases": PHASES,
            "allowedTransitions": {phase: sorted(targets) for phase, targets in ALLOWED_TRANSITIONS.items()},
            "mode": "record-and-warn",
        }

    def transition(
        self,
        state: dict[str, Any],
        target_phase: str,
        event: str,
        actor: str = "runtime",
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
        strict: bool = False,
    ) -> dict[str, Any]:
        source_phase = str(state.get("phase") or "idle")
        allowed = self.can_transition(source_phase, target_phase)
        if not allowed and strict:
            raise RuntimeError(f"状态不能从 {source_phase} 转移到 {target_phase}。")

        transition = {
            "id": f"transition_{uuid4().hex[:10]}",
            "from": source_phase,
            "to": target_phase,
            "event": event,
            "actor": actor,
            "allowed": allowed,
            "reason": reason,
            "metadata": metadata or {},
            "createdAt": now_iso(),
        }
        state["phase"] = target_phase
        state["lastTransition"] = transition
        history = state.setdefault("stateTransitions", [])
        history.append(transition)
        state["stateTransitions"] = history[-100:]
        if not allowed:
            warnings = state.setdefault("stateWarnings", [])
            warnings.append(f"{transition['createdAt']} {source_phase} -> {target_phase}: {event}")
            state["stateWarnings"] = warnings[-50:]
        return state

    def can_transition(self, source_phase: str, target_phase: str) -> bool:
        if source_phase == target_phase:
            return True
        if target_phase not in PHASES:
            return False
        if target_phase == "failed":
            return True
        return target_phase in ALLOWED_TRANSITIONS.get(source_phase, set())
