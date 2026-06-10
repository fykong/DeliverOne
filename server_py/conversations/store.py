from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Any
from uuid import uuid4

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import WORKSPACE_ROOT, conversation_root
from server_py.runtime.state_machine import RuntimeStateMachine


def _force_remove_tree(path: Path) -> None:
    """Windows 下 git 仓库的 .git/objects 是只读文件,shutil.rmtree 会 WinError 5。

    onexc/onerror 回调里清除只读位后重试。Python 3.12+ 用 onexc,旧版用 onerror。
    """

    def _on_error(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    try:
        shutil.rmtree(path, onexc=lambda f, t, e: _on_error(f, t, e))  # type: ignore[call-arg]
    except TypeError:
        shutil.rmtree(path, onerror=lambda f, t, e: _on_error(f, t, e))


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
            try:
                _force_remove_tree(root)
            except OSError as error:
                raise RuntimeError(
                    f"删除会话失败：{error}。可能有预览进程仍占用文件，请先停止预览后重试。"
                ) from error
        return {"ok": True, "conversationId": conversation_id, "summary": "会话和对应沙盒工作区已删除。"}

    def cleanup_orphans(self) -> dict[str, Any]:
        """删除没有 conversation-state.json 的孤儿目录(只读 GET 链路误建的空壳)。"""
        root = WORKSPACE_ROOT / "conversations"
        if not root.exists():
            return {"ok": True, "removed": 0, "removedIds": []}
        removed: list[str] = []
        for item in root.iterdir():
            if not item.is_dir():
                continue
            if (item / "conversation-state.json").exists():
                continue
            try:
                _force_remove_tree(item)
                removed.append(item.name)
            except OSError:
                continue
        return {"ok": True, "removed": len(removed), "removedIds": removed}

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
            # 持久化里程碑消息:刷新/切换对话后聊天区仍能看到仓库接入记录。
            source_label = "GitHub" if (repository or {}).get("sourceType") == "github" else "本地"
            branch = (repository or {}).get("branch") or "未知"
            scripts = "、".join(sorted(((repository or {}).get("scripts") or {}).keys()))
            text = f"{source_label}项目已复制到本次对话的隔离沙盒（基于分支 {branch}），原始项目不会被改动。"
            if scripts:
                text += f"检测到项目自带命令：{scripts}——后续跑测试、起预览会自动选用合适的。"
            state.setdefault("messages", []).append(self._message("agent", text))
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

    def record_milestone(self, conversation_id: str, content: str) -> dict[str, Any]:
        """持久化里程碑消息(预览启动/交付/回退/修复计划等):
        刷新或切换对话后聊天区从 state.messages 重建,只在前端 push 的消息会消失。"""
        state = self.get(conversation_id)
        state.setdefault("messages", []).append(self._message("agent", content))
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
        repository = state.get("repository") if isinstance(state.get("repository"), dict) else None
        # 标题优先用开发需求(lastRequirement,澄清合并后仍以原始需求开头),
        # 而不是首条用户消息——首条可能是"你是谁"这类提问,会霸占标题;
        # 也不是最后一条——澄清回答"1选A"之类短回复在列表里完全认不出。
        first_user_message = next((item for item in messages if item.get("role") == "user"), None)
        title = str(state.get("lastRequirement") or "").strip()
        if not title and isinstance(first_user_message, dict):
            title = str(first_user_message.get("content", "")).strip()
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
            # 后端权威标记:开发/测试会话显式 internal,前端据此过滤,
            # 不再用标题关键词启发式误伤用户自己的同名对话。
            "internal": bool(state.get("internal")),
        }
