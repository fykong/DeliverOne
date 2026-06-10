from __future__ import annotations

from typing import Any

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import conversation_root


PRIMARY_STAGE_IDS = [
    "requirement",
    "clarification",
    "plan",
    "tool-plan",
    "approval",
    "execution",
    "verification",
    "repair",
    "delivery",
    "rollback",
]


class TaskStateMachineService:
    """Persist the user-visible delivery lifecycle as a recoverable ledger."""

    def persist(self, runtime_snapshot: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        conversation_id = str(runtime_snapshot.get("conversationId") or state.get("conversationId") or "")
        previous = self.read(conversation_id)
        controls = previous.get("stageControls") if isinstance(previous.get("stageControls"), dict) else {}
        action_override = previous.get("nextActionOverride") if isinstance(previous.get("nextActionOverride"), dict) else None
        edit_history = previous.get("editHistory") if isinstance(previous.get("editHistory"), list) else []
        stages = self._stages(runtime_snapshot.get("stages", []))
        stages = self._apply_stage_controls(stages, controls)
        primary_stages = [stage for stage in stages if stage.get("primary")]
        blocked = [stage for stage in primary_stages if stage.get("status") == "blocked"]
        current = [stage for stage in primary_stages if stage.get("status") == "current"]
        status = "blocked" if blocked else ("running" if current else "ready")
        active_stage = next((stage["id"] for stage in stages if stage["status"] in {"blocked", "current"}), stages[-1]["id"] if stages else None)
        summary = self._ledger_summary(stages)
        root = conversation_root(conversation_id) / "runtime"
        path = root / "task-state-machine.json"
        next_actions = self._merge_next_actions(runtime_snapshot.get("nextActions", []), action_override)
        blockers = list(runtime_snapshot.get("blockers", []) if isinstance(runtime_snapshot.get("blockers"), list) else [])
        blockers.extend(stage["summary"] for stage in primary_stages if stage.get("status") == "blocked" and stage.get("summary") not in blockers)
        ledger = {
            "schemaVersion": 1,
            "conversationId": conversation_id,
            "phase": runtime_snapshot.get("phase"),
            "status": status,
            "activeStage": active_stage,
            "summary": summary,
            "primaryStageIds": PRIMARY_STAGE_IDS,
            "stages": stages,
            "evidence": runtime_snapshot.get("evidence", {}),
            "blockers": blockers,
            "warnings": runtime_snapshot.get("warnings", []),
            "nextActions": next_actions,
            "stageControls": controls,
            "nextActionOverride": action_override,
            "editHistory": edit_history[-50:],
            "lastTransition": state.get("lastTransition"),
            "transitionCount": len(state.get("stateTransitions", [])) if isinstance(state.get("stateTransitions"), list) else 0,
            "recentTransitions": self._recent_transitions(state),
            "source": {
                "kind": "runtime-snapshot",
                "snapshotUpdatedAt": runtime_snapshot.get("updatedAt"),
                "mechanisms": runtime_snapshot.get("reusedCodexMechanisms", []),
            },
            "updatedAt": now_iso(),
            "path": str(path),
        }
        write_json(path, ledger)
        return {
            "schemaVersion": ledger["schemaVersion"],
            "status": ledger["status"],
            "activeStage": ledger["activeStage"],
            "primaryStageIds": PRIMARY_STAGE_IDS,
            "stageCount": len(stages),
            "transitionCount": ledger["transitionCount"],
            "recentTransitions": ledger["recentTransitions"],
            "control": self._control_summary(controls, action_override, edit_history),
            "path": ledger["path"],
            "updatedAt": ledger["updatedAt"],
        }

    def read(self, conversation_id: str) -> dict[str, Any]:
        return read_json(conversation_root(conversation_id) / "runtime" / "task-state-machine.json", {}) or {}

    def edit(
        self,
        conversation_id: str,
        operation: str,
        stage_id: str | None = None,
        note: str | None = None,
        action_ids: list[str] | None = None,
        actor: str = "user",
    ) -> dict[str, Any]:
        ledger = self.read(conversation_id)
        if not ledger:
            raise RuntimeError("任务状态机尚未生成，请先刷新运行状态。")
        normalized = operation.strip()
        controls = ledger.get("stageControls") if isinstance(ledger.get("stageControls"), dict) else {}
        edit_history = ledger.get("editHistory") if isinstance(ledger.get("editHistory"), list) else []
        created_at = now_iso()

        if normalized in {"annotate_stage", "pause_stage", "resume_stage"}:
            if not stage_id:
                raise RuntimeError("缺少阶段 ID。")
            stage = self._find_stage(ledger, stage_id)
            if not stage:
                raise RuntimeError(f"阶段不存在：{stage_id}")
            control = controls.get(stage_id) if isinstance(controls.get(stage_id), dict) else {}
            if normalized == "annotate_stage":
                control["note"] = (note or "").strip()
            elif normalized == "pause_stage":
                control["paused"] = True
                control["note"] = (note or control.get("note") or "用户暂停此阶段，等待人工审查。").strip()
            elif normalized == "resume_stage":
                control["paused"] = False
                if note:
                    control["note"] = note.strip()
            control.update({"stageId": stage_id, "updatedAt": created_at, "actor": actor})
            controls[stage_id] = control
        elif normalized == "set_next_actions":
            cleaned = [item.strip() for item in action_ids or [] if item and item.strip()]
            if not cleaned:
                raise RuntimeError("至少提供一个下一步动作 ID。")
            ledger["nextActionOverride"] = {
                "actionIds": cleaned[:8],
                "note": (note or "").strip(),
                "actor": actor,
                "updatedAt": created_at,
            }
        elif normalized == "clear_next_actions":
            ledger["nextActionOverride"] = None
        else:
            raise RuntimeError(f"不支持的状态机编辑操作：{operation}")

        edit_history.append(
            {
                "operation": normalized,
                "stageId": stage_id,
                "note": (note or "").strip(),
                "actionIds": action_ids or [],
                "actor": actor,
                "createdAt": created_at,
            }
        )
        ledger["stageControls"] = controls
        ledger["editHistory"] = edit_history[-50:]
        ledger["updatedAt"] = created_at
        path = conversation_root(conversation_id) / "runtime" / "task-state-machine.json"
        ledger["path"] = str(path)
        write_json(path, ledger)
        return self._summary(ledger)

    def record_tool_plan_edit(
        self,
        conversation_id: str,
        edit_record: dict[str, Any],
        review: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        ledger = self.read(conversation_id)
        if not ledger:
            return None
        created_at = now_iso()
        controls = ledger.get("stageControls") if isinstance(ledger.get("stageControls"), dict) else {}
        edit_history = ledger.get("editHistory") if isinstance(ledger.get("editHistory"), list) else []
        stage_id = "tool-plan"
        operation = str(edit_record.get("operation") or "tool_plan_edit")
        step_id = str(edit_record.get("stepId") or "")
        reason = str(edit_record.get("reason") or "用户修改了工具计划。").strip()
        review_verdict = review.get("verdict") if isinstance(review, dict) else None
        review_summary = review.get("summary") if isinstance(review, dict) else None
        note_parts = [reason]
        if review_verdict:
            note_parts.append(f"Reviewer：{review_verdict}")
        control = controls.get(stage_id) if isinstance(controls.get(stage_id), dict) else {}
        control.update(
            {
                "stageId": stage_id,
                "note": "；".join(part for part in note_parts if part),
                "paused": False,
                "updatedAt": created_at,
                "actor": "user",
            }
        )
        controls[stage_id] = control
        edit_history.append(
            {
                "operation": "tool_plan_edit",
                "stageId": stage_id,
                "note": reason,
                "actionIds": ["edit_tool_plan", "approve_tool_plan"],
                "actor": "user",
                "createdAt": created_at,
                "metadata": {
                    "toolPlanOperation": operation,
                    "stepId": step_id,
                    "reviewVerdict": review_verdict,
                    "reviewSummary": review_summary,
                },
            }
        )
        ledger["stageControls"] = controls
        ledger["editHistory"] = edit_history[-50:]
        ledger["updatedAt"] = created_at
        path = conversation_root(conversation_id) / "runtime" / "task-state-machine.json"
        ledger["path"] = str(path)
        write_json(path, ledger)
        return self._summary(ledger)

    def _stages(self, raw_stages: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_stages, list):
            return []
        result: list[dict[str, Any]] = []
        for index, stage in enumerate(raw_stages):
            if not isinstance(stage, dict):
                continue
            stage_id = str(stage.get("id") or f"stage-{index}")
            result.append(
                {
                    "id": stage_id,
                    "index": index + 1,
                    "primary": stage_id in PRIMARY_STAGE_IDS,
                    "title": stage.get("title") or stage_id,
                    "owner": stage.get("owner") or "runtime",
                    "status": stage.get("status") or "pending",
                    "summary": stage.get("summary") or "",
                    "evidence": stage.get("evidence") if isinstance(stage.get("evidence"), dict) else {},
                    "actions": stage.get("actions") if isinstance(stage.get("actions"), list) else [],
                }
            )
        return result

    def _apply_stage_controls(self, stages: list[dict[str, Any]], controls: dict[str, Any]) -> list[dict[str, Any]]:
        for stage in stages:
            stage_id = stage.get("id")
            control = controls.get(stage_id) if isinstance(controls.get(stage_id), dict) else None
            if not control:
                continue
            stage["control"] = {
                "note": control.get("note"),
                "paused": bool(control.get("paused")),
                "updatedAt": control.get("updatedAt"),
                "actor": control.get("actor"),
            }
            if control.get("note"):
                stage["userNote"] = control.get("note")
            if control.get("paused"):
                stage["status"] = "blocked"
                stage["summary"] = f"用户暂停此阶段：{control.get('note') or '等待人工审查。'}"
                stage["actions"] = ["resume_stage"]
        return stages

    def _merge_next_actions(self, raw_actions: Any, action_override: dict[str, Any] | None) -> list[dict[str, Any]]:
        actions = raw_actions if isinstance(raw_actions, list) else []
        if not action_override:
            return actions
        action_ids = action_override.get("actionIds") if isinstance(action_override.get("actionIds"), list) else []
        merged: list[dict[str, Any]] = []
        for action_id in action_ids:
            existing = next((item for item in actions if isinstance(item, dict) and item.get("id") == action_id), None)
            merged.append(existing or {"id": action_id, "label": action_id, "kind": "approval"})
        return merged

    def _control_summary(self, controls: dict[str, Any], action_override: dict[str, Any] | None, edit_history: list[dict[str, Any]]) -> dict[str, Any]:
        annotated = [stage_id for stage_id, control in controls.items() if isinstance(control, dict) and control.get("note")]
        paused = [stage_id for stage_id, control in controls.items() if isinstance(control, dict) and control.get("paused")]
        return {
            "annotatedStageIds": sorted(annotated),
            "pausedStageIds": sorted(paused),
            "manualNextActionIds": action_override.get("actionIds", []) if isinstance(action_override, dict) else [],
            "manualNextActionNote": action_override.get("note") if isinstance(action_override, dict) else None,
            "editCount": len(edit_history),
            "latestEdit": edit_history[-1] if edit_history else None,
        }

    def _summary(self, ledger: dict[str, Any]) -> dict[str, Any]:
        return {
            "schemaVersion": ledger.get("schemaVersion", 1),
            "status": ledger.get("status", "unknown"),
            "activeStage": ledger.get("activeStage"),
            "primaryStageIds": ledger.get("primaryStageIds", PRIMARY_STAGE_IDS),
            "stageCount": len(ledger.get("stages", [])) if isinstance(ledger.get("stages"), list) else 0,
            "transitionCount": ledger.get("transitionCount", 0),
            "recentTransitions": ledger.get("recentTransitions", []),
            "control": self._control_summary(
                ledger.get("stageControls") if isinstance(ledger.get("stageControls"), dict) else {},
                ledger.get("nextActionOverride") if isinstance(ledger.get("nextActionOverride"), dict) else None,
                ledger.get("editHistory") if isinstance(ledger.get("editHistory"), list) else [],
            ),
            "path": ledger.get("path"),
            "updatedAt": ledger.get("updatedAt"),
        }

    def _ledger_summary(self, stages: list[dict[str, Any]]) -> str:
        active = next((stage for stage in stages if stage["status"] in {"blocked", "current"}), None)
        if not active:
            return "任务状态机已完成当前可见链路。"
        return f"当前阶段：{active['title']}。{active['summary']}"

    def _find_stage(self, ledger: dict[str, Any], stage_id: str) -> dict[str, Any] | None:
        stages = ledger.get("stages")
        if not isinstance(stages, list):
            return None
        for stage in stages:
            if isinstance(stage, dict) and stage.get("id") == stage_id:
                return stage
        return None

    def _recent_transitions(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        transitions = state.get("stateTransitions")
        if not isinstance(transitions, list):
            return []
        result: list[dict[str, Any]] = []
        for item in transitions[-8:]:
            if not isinstance(item, dict):
                continue
            result.append(
                {
                    "from": item.get("from"),
                    "to": item.get("to"),
                    "event": item.get("event"),
                    "actor": item.get("actor"),
                    "allowed": bool(item.get("allowed", True)),
                    "createdAt": item.get("createdAt"),
                }
            )
        return result
