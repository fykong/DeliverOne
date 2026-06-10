from __future__ import annotations

from typing import Any

from server_py.agent.planning_agent import PlanningAgent
from server_py.audit.plan_auditor import PlanAuditor
from server_py.conversations.store import ConversationStore
from server_py.core.json_io import now_iso
from server_py.memory.memory_service import MemoryService
from server_py.runtime.events import EventStore
from server_py.sandbox.checkpoint_manager import CheckpointManager
from server_py.tools.registry import ToolRegistry
from server_py.tools.types import ToolContext


class AgentWorkflow:
    def __init__(
        self,
        planning_agent: PlanningAgent,
        conversations: ConversationStore,
        auditor: PlanAuditor,
        memory: MemoryService,
        tools: ToolRegistry,
        events: EventStore,
        checkpoints: CheckpointManager,
    ) -> None:
        self.planning_agent = planning_agent
        self.conversations = conversations
        self.auditor = auditor
        self.memory = memory
        self.tools = tools
        self.events = events
        self.checkpoints = checkpoints

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        return self.conversations.get(conversation_id)

    def plan(
        self,
        conversation_id: str,
        requirement: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self.events.append(conversation_id, "turn.started", {"phase": "planning"})
        self.events.append(conversation_id, "user.message", {"content": requirement}, actor="user")
        turn = self.planning_agent.run(conversation_id, requirement, repository, sandbox)
        self.conversations.record_planning(conversation_id, requirement, turn, repository, sandbox)
        self.memory.record_agent_turn(conversation_id, turn)
        self.events.append(conversation_id, "agent.message", {"content": turn["reply"], "phase": turn["phase"]}, actor="agent")
        self.events.append(conversation_id, "turn.completed", {"phase": turn["phase"]})
        return turn

    def confirm_plan(self, conversation_id: str) -> dict[str, Any]:
        state = self.conversations.get(conversation_id)
        previous_turn = state.get("turns", [])[-1] if state.get("turns") else None
        audit = self.auditor.audit_plan_confirmation(bool(previous_turn), state.get("phase") == "waiting_plan_confirmation")

        if not previous_turn or state.get("phase") != "waiting_plan_confirmation":
            self.conversations.record_audit(conversation_id, audit)
            self.events.append(conversation_id, "approval.rejected", {"reason": "当前没有等待确认的计划。"})
            raise RuntimeError("当前没有等待确认的计划。")

        self.events.append(conversation_id, "approval.resolved", {"id": "plan", "decision": "approved"}, actor="user")
        sandbox = state.get("sandbox")
        if not sandbox:
            reply = "计划已确认，但当前对话还没有沙盒。请先接入本地仓库或 GitHub 仓库，系统会为这次对话创建独立沙盒。"
            steps = [
                {"id": "plan-confirmed", "title": "计划确认", "detail": "用户已确认当前执行计划。", "status": "done"},
                {"id": "sandbox-required", "title": "沙盒缺失", "detail": "代码工具只能在当前对话沙盒中运行。", "status": "blocked"},
            ]
            turn = self._turn(conversation_id, "waiting_sandbox", previous_turn, reply, steps, [audit], "当前对话没有沙盒。")
            self.conversations.record_turn(conversation_id, turn, "waiting_sandbox", reply)
            self.memory.record_decision(conversation_id, "计划已确认", "用户确认计划，但执行被沙盒缺失阻塞。")
            self.memory.record_agent_turn(conversation_id, turn)
            self.events.append(conversation_id, "agent.message", {"content": reply, "phase": "waiting_sandbox"}, actor="agent")
            return turn

        context = ToolContext(conversation_id=conversation_id, sandbox_id=sandbox["id"], repo_path=sandbox["repoPath"])
        query = state.get("lastRequirement", "")
        search_result = self.tools.run("code.search_files", {"query": query, "maxResults": 8}, context)
        diff_result = self.tools.run("code.git_diff", {}, context)
        checkpoints = self.checkpoints.list(conversation_id)

        steps = [
            {"id": "plan-confirmed", "title": "计划确认", "detail": "用户已确认当前执行计划。", "status": "done"},
            {"id": "code-search", "title": "代码定位", "detail": search_result["summary"], "status": "done" if search_result.get("ok") else "failed"},
            {"id": "diff-check", "title": "Diff 检查", "detail": diff_result["summary"], "status": "done" if diff_result.get("ok") else "failed"},
            {
                "id": "write-gate-ready",
                "title": "写入门禁就绪",
                "detail": "后续每次写文件都会先创建 checkpoint；非可信命令会进入审批。",
                "status": "done",
            },
        ]
        reply = "\n".join(
            [
                "我已经开始执行确认后的第一步：先在当前沙盒里定位代码，不直接改原始仓库。",
                "",
                "代码定位结果：",
                self._format_search_evidence(search_result.get("data")),
                "",
                f"Diff 状态：{diff_result['summary']}",
                f"当前检查点数量：{len(checkpoints)}",
                "",
                "下一步如果进入修改，写入工具会先生成 checkpoint；如果需要跑非可信命令，会先返回确认请求。",
            ]
        )
        turn = self._turn(conversation_id, "ready_to_edit", previous_turn, reply, steps, [audit])
        turn["toolResults"] = {"search": search_result, "diff": diff_result, "checkpoints": checkpoints}
        self.conversations.record_turn(conversation_id, turn, "ready_to_edit", reply)
        self.memory.record_decision(conversation_id, "计划已确认", "系统已进入代码定位阶段，并启用写入 checkpoint 门禁。")
        self.memory.record_agent_turn(conversation_id, turn)
        self.events.append(conversation_id, "agent.message", {"content": reply, "phase": "ready_to_edit"}, actor="agent")
        self.events.append(conversation_id, "turn.completed", {"phase": "ready_to_edit"})
        return turn

    def _format_search_evidence(self, data: Any) -> str:
        matches = data.get("matches", []) if isinstance(data, dict) else []
        if not matches:
            return "暂未找到明显候选文件，下一步需要扩大搜索词或读取仓库结构。"
        return "\n".join(f"- {item.get('path', '未知文件')}：{item.get('reason', '匹配')}" for item in matches[:8])

    def _turn(
        self,
        conversation_id: str,
        phase: str,
        previous_turn: dict[str, Any],
        reply: str,
        steps: list[dict[str, Any]],
        audits: list[dict[str, Any]],
        blocked_reason: str | None = None,
    ) -> dict[str, Any]:
        turn = {
            "conversationId": conversation_id,
            "phase": phase,
            "preflight": previous_turn["preflight"],
            "model": previous_turn["model"],
            "reply": reply,
            "steps": steps,
            "audits": audits,
            "createdAt": now_iso(),
        }
        if blocked_reason:
            turn["blockedReason"] = blocked_reason
        return turn
