from __future__ import annotations

from server_py.runtime.state_machine import RuntimeStateMachine


def test_clarification_entry_points():
    machine = RuntimeStateMachine()
    for source in ["idle", "sandbox_ready", "waiting_plan_confirmation", "tool_plan_completed", "completed", "failed"]:
        assert machine.can_transition(source, "clarification"), source


def test_clarification_exit_to_planning():
    machine = RuntimeStateMachine()
    assert machine.can_transition("clarification", "waiting_plan_confirmation")
    assert machine.can_transition("clarification", "planning")
    # 再次澄清(同阶段)也允许
    assert machine.can_transition("clarification", "clarification")


def test_disallowed_transition_records_warning():
    machine = RuntimeStateMachine()
    state = {"phase": "idle", "conversationId": "c"}
    machine.transition(state, "tool_plan_running", event="test")
    assert state["phase"] == "tool_plan_running"
    assert state["stateWarnings"]
