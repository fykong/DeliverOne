from __future__ import annotations

import json
import time
from typing import Any

from server_py.observability.metrics import MetricStore
from server_py.runtime.approval_store import ApprovalStore
from server_py.runtime.events import EventStore
from server_py.runtime.permissions import PermissionAssessment, PermissionPolicy
from server_py.tools.types import AgentTool, ToolContext


class ToolRegistry:
    def __init__(self, events: EventStore, policy: PermissionPolicy, metrics: MetricStore | None = None, approvals: ApprovalStore | None = None) -> None:
        self._tools: dict[str, AgentTool] = {}
        self.events = events
        self.policy = policy
        self.metrics = metrics
        self.approvals = approvals

    def register(self, tool: AgentTool) -> "ToolRegistry":
        self._tools[tool.id] = tool
        return self

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "id": tool.id,
                "name": tool.name,
                "description": tool.description,
                "riskLevel": tool.risk_level,
                "requiresCheckpoint": tool.requires_checkpoint,
                "managedCommand": tool.managed_command,
                "inputSchema": tool.input_schema or {},
            }
            for tool in self._tools.values()
        ]

    def run(self, tool_id: str, payload: Any, context: ToolContext) -> dict[str, Any]:
        started = time.perf_counter()
        tool = self._tools.get(tool_id)
        if not tool:
            return {"ok": False, "summary": f"工具不存在：{tool_id}", "error": f"Unknown tool: {tool_id}"}

        assessment = self.policy.assess_tool(tool, payload, context)
        grant = None
        if not assessment.allowed and assessment.needs_approval and self.approvals:
            grant = self.approvals.consume_matching(context.conversation_id, tool.id, tool.risk_level, payload)
            if grant:
                assessment = PermissionAssessment(True, False, f"已使用会话授权：{grant['id']}。", tool.risk_level)
        call_payload = {
            "toolId": tool.id,
            "toolName": tool.name,
            "planId": context.plan_id,
            "stepId": context.step_id,
            "sandboxId": context.sandbox_id,
            "riskLevel": tool.risk_level,
            "requiresCheckpoint": tool.requires_checkpoint,
            "inputSummary": self._summarize(payload),
            "input": self._safe_payload(payload),
            "permission": {
                "allowed": assessment.allowed,
                "needsApproval": assessment.needs_approval,
                "decision": assessment.decision,
                "ruleId": assessment.rule_id,
                "reason": assessment.reason,
                "proposedPrefixRule": assessment.proposed_prefix_rule,
                "grantId": grant.get("id") if grant else None,
            },
        }
        self.events.append(context.conversation_id, "tool.call.begin", call_payload, actor="agent")

        if not assessment.allowed:
            result = {
                "ok": False,
                "summary": assessment.reason,
                "blocked": not assessment.needs_approval,
                "needsApproval": assessment.needs_approval,
                "decision": assessment.decision,
                "ruleId": assessment.rule_id,
                "proposedPrefixRule": assessment.proposed_prefix_rule,
                "riskLevel": tool.risk_level,
                "error": assessment.reason,
            }
            if assessment.needs_approval:
                self.events.append(context.conversation_id, "approval.requested", call_payload, actor="runtime")
            self.events.append(
                context.conversation_id,
                "tool.call.end",
                {
                    "toolId": tool.id,
                    "planId": context.plan_id,
                    "stepId": context.step_id,
                    "ok": False,
                    "summary": result["summary"],
                    "result": self._safe_payload(result),
                },
                actor="runtime",
            )
            self._record_metric(context, tool.id, started, False, tool.risk_level)
            return result

        try:
            result = tool.run(payload, context)
            self.events.append(
                context.conversation_id,
                "tool.call.end",
                {
                    "toolId": tool.id,
                    "planId": context.plan_id,
                    "stepId": context.step_id,
                    "ok": result.get("ok", True),
                    "summary": result.get("summary", ""),
                    "result": self._safe_payload(result),
                },
                actor="runtime",
            )
            self._record_metric(context, tool.id, started, bool(result.get("ok", True)), tool.risk_level)
            return result
        except Exception as error:
            result = {"ok": False, "summary": f"{tool.name} 调用失败：{error}", "error": str(error)}
            self.events.append(
                context.conversation_id,
                "tool.call.end",
                {
                    "toolId": tool.id,
                    "planId": context.plan_id,
                    "stepId": context.step_id,
                    "ok": False,
                    "summary": result["summary"],
                    "result": self._safe_payload(result),
                },
                actor="runtime",
            )
            self._record_metric(context, tool.id, started, False, tool.risk_level)
            return result

    def _summarize(self, payload: Any) -> str:
        try:
            text = json.dumps(payload, ensure_ascii=False)
        except TypeError:
            text = str(payload)
        if len(text) > 1000:
            return text[:1000] + "..."
        return text

    def _safe_payload(self, value: Any, max_text: int = 8000) -> Any:
        if isinstance(value, dict):
            return {str(key): self._safe_payload(item, max_text) for key, item in value.items()}
        if isinstance(value, list):
            return [self._safe_payload(item, max_text) for item in value[:80]]
        if isinstance(value, str):
            return value[:max_text] + "...[已截断]" if len(value) > max_text else value
        return value

    def _record_metric(self, context: ToolContext, tool_id: str, started: float, ok: bool, risk_level: str) -> None:
        if not self.metrics:
            return
        self.metrics.record_tool_call(
            context.conversation_id,
            tool_id,
            int((time.perf_counter() - started) * 1000),
            ok,
            risk_level,
        )
