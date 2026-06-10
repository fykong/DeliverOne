from __future__ import annotations

import shutil
from typing import Any
from uuid import uuid4

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import WORKSPACE_ROOT, conversation_root
from server_py.runtime.state_machine import RuntimeStateMachine


class ConversationStore:
    def __init__(self, state_machine: RuntimeStateMachine | None = None) -> None:
        self.state_machine = state_machine or RuntimeStateMachine()

    def list(self) -> list[dict[str, Any]]:
        root = WORKSPACE_ROOT / "conversations"
        if not root.exists():
            return []
        states: list[dict[str, Any]] = []
        for item in root.iterdir():
            if not item.is_dir():
                continue
            state = read_json(item / "conversation-state.json", None)
            if state:
                states.append(self._summary(state))
        return sorted(states, key=lambda state: state.get("updatedAt", ""), reverse=True)

    def get(self, conversation_id: str) -> dict[str, Any]:
        path = conversation_root(conversation_id) / "conversation-state.json"
        state = read_json(path, None)
        if state:
            return state
        created = now_iso()
        return {
            "conversationId": conversation_id,
            "phase": "idle",
            "messages": [],
            "turns": [],
            "audits": [],
            "createdAt": created,
            "updatedAt": created,
        }

    def save(self, state: dict[str, Any]) -> dict[str, Any]:
        state["updatedAt"] = now_iso()
        write_json(conversation_root(state["conversationId"]) / "conversation-state.json", state)
        return state

    def delete(self, conversation_id: str) -> dict[str, Any]:
        root = conversation_root(conversation_id).resolve()
        workspace = WORKSPACE_ROOT.resolve()
        if root != workspace and workspace not in root.parents:
            raise RuntimeError("会话路径超出工作区，拒绝删除。")
        if root.exists():
            shutil.rmtree(root)
        return {"ok": True, "conversationId": conversation_id, "summary": "会话和对应沙盒工作区已删除。"}

    def record_context(
        self,
        conversation_id: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
    ) -> dict[str, Any]:
        state = self.get(conversation_id)
        state["repository"] = repository
        state["sandbox"] = sandbox
        if sandbox:
            self._transition(state, "sandbox_ready", "sandbox.ready", "runtime", "当前对话沙盒已创建。")
        return self.save(state)

    def record_tool_call_plan(self, conversation_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        state = self.get(conversation_id)
        state["toolCallPlan"] = {
            "id": plan.get("id"),
            "status": plan.get("status"),
            "stepCount": len(plan.get("steps", [])),
            "updatedAt": plan.get("updatedAt"),
            "evidence": plan.get("evidence", {}),
        }
        status = plan.get("status")
        if status == "waiting_confirmation":
            state["pendingConfirmation"] = {
                "id": "tool-call-plan",
                "title": "确认工具调用计划",
                "description": "确认后，系统会按步骤调用受控工具，并记录 checkpoint、diff 和验证证据。",
                "createdAt": now_iso(),
            }
            self._transition(state, "waiting_tool_plan_confirmation", "tool_plan.created", "agent", "等待用户确认工具调用计划。")
        elif status in {"approved", "running", "completed", "failed", "waiting_approval"}:
            target_phase = f"tool_plan_{status}"
            self._transition(state, target_phase, f"tool_plan.{status}", "runtime", "工具调用计划状态更新。")
            state.pop("pendingConfirmation", None)
        return self.save(state)

    def record_planning(
        self,
        conversation_id: str,
        requirement: str,
        turn: dict[str, Any],
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        user_message: str | None = None,
    ) -> dict[str, Any]:
        state = self.get(conversation_id)
        self._transition(state, turn["phase"], "agent.planning.completed", "agent", "模型规划阶段完成。")
        state["lastRequirement"] = requirement
        state["repository"] = repository
        state["sandbox"] = sandbox
        # 澄清回答合并时,聊天区显示用户原话,lastRequirement 存合并后的完整需求。
        state.setdefault("messages", []).append(self._message("user", user_message or requirement))
        state["messages"].append(self._message("agent", turn["reply"]))
        state.setdefault("turns", []).append(turn)
        state.setdefault("audits", []).extend(turn.get("audits", []))
        if turn["phase"] == "waiting_plan_confirmation":
            state["pendingConfirmation"] = {
                "id": "plan",
                "title": "确认执行计划",
                "description": "确认后，Agent 才能进入代码定位、检查点、修改和验证流程。",
                "createdAt": now_iso(),
            }
        else:
            state.pop("pendingConfirmation", None)
        return self.save(state)

    def record_turn(self, conversation_id: str, turn: dict[str, Any], phase: str, message: str) -> dict[str, Any]:
        state = self.get(conversation_id)
        self._transition(state, phase, "agent.turn.recorded", "agent", "Agent turn 已写入会话。")
        state.setdefault("messages", []).append(self._message("agent", message))
        state.setdefault("turns", []).append(turn)
        state.setdefault("audits", []).extend(turn.get("audits", []))
        state.pop("pendingConfirmation", None)
        return self.save(state)

    def record_audit(self, conversation_id: str, audit: dict[str, Any]) -> dict[str, Any]:
        state = self.get(conversation_id)
        state.setdefault("audits", []).append(audit)
        return self.save(state)

    def _message(self, role: str, content: str) -> dict[str, Any]:
        return {"id": f"msg_{uuid4().hex[:10]}", "role": role, "content": content, "createdAt": now_iso()}

    def _transition(self, state: dict[str, Any], phase: str, event: str, actor: str, reason: str) -> None:
        self.state_machine.transition(state, phase, event=event, actor=actor, reason=reason, strict=False)

    def _summary(self, state: dict[str, Any]) -> dict[str, Any]:
        messages = state.get("messages") if isinstance(state.get("messages"), list) else []
        last_user_message = next((item for item in reversed(messages) if item.get("role") == "user"), None)
        repository = state.get("repository") if isinstance(state.get("repository"), dict) else None
        title = ""
        if isinstance(last_user_message, dict):
            title = str(last_user_message.get("content", "")).strip()
        if not title and repository:
            title = str(repository.get("source", "")).split("\\")[-1].split("/")[-1]
        if not title:
            title = "未命名对话"
        return {
            "conversationId": state.get("conversationId"),
            "title": title[:80],
            "phase": state.get("phase", "idle"),
            "updatedAt": state.get("updatedAt"),
            "createdAt": state.get("createdAt"),
            "repository": repository,
            "sandbox": state.get("sandbox"),
            "toolCallPlan": state.get("toolCallPlan"),
            "lastTransition": state.get("lastTransition"),
            "stateWarningCount": len(state.get("stateWarnings", [])),
        }
