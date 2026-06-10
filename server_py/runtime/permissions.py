from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from typing import TYPE_CHECKING

from server_py.core.json_io import read_json
from server_py.core.paths import AGENT_POLICY_PATH, WORKSPACE_ROOT

if TYPE_CHECKING:  # 仅类型标注使用，避免与 server_py.tools 循环导入
    from server_py.tools.types import AgentTool, ToolContext


PolicyDecision = Literal["allow", "prompt", "forbid"]


DEFAULT_POLICY = {
    "approvalMode": "untrusted",
    "sandboxMode": "workspace_write",
    "trustedCommandPrefixes": [
        "git status",
        "git diff",
        "git log",
        "git branch",
        "git show",
        "npm run typecheck",
        "npm run lint",
        "npm run test",
        "npm test",
        "npm run build",
        "pwd",
        "ls",
        "dir",
        "rg",
        "cat",
        "type",
    ],
    "dangerousCommandPatterns": [
        r"\brm\s+-rf\b",
        r"\brmdir\s+/s\b",
        r"\bdel\s+/[sq]\b",
        r"\bRemove-Item\b.*\b-Recurse\b",
        r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+clean\s+-fd\b",
        r"\bshutdown\b",
        r"\bformat\b",
    ],
    "rules": [],
}


@dataclass(frozen=True)
class PermissionAssessment:
    allowed: bool
    needs_approval: bool
    reason: str
    risk_level: str
    decision: PolicyDecision = "forbid"
    rule_id: str | None = None
    proposed_prefix_rule: list[str] | None = None


class PermissionPolicy:
    """Codex-style approval and sandbox policy.

    This is a Python adaptation of the useful Codex runtime ideas:
    command decisions are explicit (allow / prompt / forbid), safe prefixes are
    configurable, dangerous commands cannot be smuggled through normal command
    execution, and every tool must be bound to a conversation sandbox.
    """

    def __init__(self, approval_mode: str | None = None, sandbox_mode: str | None = None) -> None:
        self.config = read_json(AGENT_POLICY_PATH, DEFAULT_POLICY)
        self.approval_mode = approval_mode or self.config.get("approvalMode", "untrusted")
        self.sandbox_mode = sandbox_mode or self.config.get("sandboxMode", "workspace_write")
        self.trusted_command_prefixes = tuple(
            self.config.get("trustedCommandPrefixes", DEFAULT_POLICY["trustedCommandPrefixes"])
        )
        self.dangerous_command_patterns = list(
            self.config.get("dangerousCommandPatterns", DEFAULT_POLICY["dangerousCommandPatterns"])
        )
        self.rules = list(self.config.get("rules", []))

    def describe(self) -> dict[str, Any]:
        return {
            "approvalMode": self.approval_mode,
            "sandboxMode": self.sandbox_mode,
            "trustedCommandPrefixes": list(self.trusted_command_prefixes),
            "dangerousCommandPatterns": self.dangerous_command_patterns,
            "rules": [item.get("description", item) for item in self.rules],
            "ruleObjects": self.rules,
            "policyPath": str(AGENT_POLICY_PATH),
            "reusedCodexMechanisms": [
                "ExecPolicyManager decision model",
                "prefix-rule allowlist",
                "dangerous command heuristic",
                "sandbox-bound execution",
            ],
        }

    def matrix(self) -> list[dict[str, Any]]:
        return [
            {
                "riskLevel": "read",
                "defaultDecision": "allow",
                "approvalRequired": False,
                "checkpointRequired": False,
                "scope": "当前 conversation sandbox",
                "reason": "只读工具允许在当前沙盒内执行。",
            },
            {
                "riskLevel": "write",
                "defaultDecision": "allow_with_checkpoint",
                "approvalRequired": False,
                "checkpointRequired": True,
                "scope": "当前 conversation sandbox",
                "reason": "写入工具必须声明 requiresCheckpoint，并由工具在写入前创建 checkpoint。",
            },
            {
                "riskLevel": "command",
                "defaultDecision": "allow_trusted_or_prompt",
                "approvalRequired": "非可信命令需要计划确认或单独授权",
                "checkpointRequired": False,
                "scope": "当前 conversation sandbox",
                "reason": "可信命令可直接执行；非可信命令进入审批；危险命令禁止普通 command.run 执行。",
            },
            {
                "riskLevel": "external",
                "defaultDecision": "prompt",
                "approvalRequired": True,
                "checkpointRequired": False,
                "scope": "按外部能力单独确认",
                "reason": "外部 MCP / Browser / GitHub 工具可能传输上下文，默认需要确认。",
            },
            {
                "riskLevel": "dangerous",
                "defaultDecision": "forbid_or_dedicated_approval",
                "approvalRequired": True,
                "checkpointRequired": "视操作而定",
                "scope": "禁止通过普通命令绕过",
                "reason": "高风险操作必须走专门的回退或交付接口。",
            },
        ]

    def assess_tool(self, tool: AgentTool, payload: Any, context: ToolContext) -> PermissionAssessment:
        risk = tool.risk_level
        if not self._has_sandbox_repo(context):
            return self._forbid("sandbox-required", "当前对话没有可用沙盒仓库，工具不能执行。", risk)

        if not self._repo_in_workspace(context.repo_path):
            return self._forbid("workspace-only", "仓库路径不在本项目 workspace 内，已拒绝执行。", risk)

        if risk == "read":
            return self._allow("read-tool", "只读工具允许在当前沙盒内执行。", risk)

        if risk == "write":
            if context.sandbox_mode == "read_only":
                return self._prompt("read-only-sandbox", "当前是只读沙盒，写入需要用户切换权限。", risk)
            if not tool.requires_checkpoint:
                return self._forbid("write-needs-checkpoint", "写入工具缺少 checkpoint 保护，已阻断。", risk)
            return self._allow("checkpointed-write", "写入工具会先创建 checkpoint，再修改沙盒文件。", risk)

        if risk == "command":
            if getattr(tool, "managed_command", False):
                return self._assess_managed_command(payload, context, risk)
            return self._assess_command(payload, context, risk)

        if risk == "external":
            if context.user_initiated or self._payload_approved(payload):
                return self._allow("user-approved-external", "用户已确认外部能力调用。", risk)
            return self._prompt("external-needs-approval", "外部能力调用必须先经过用户确认。", risk)

        if risk == "dangerous":
            if self._payload_dedicated_approval(payload):
                return self._allow("dedicated-dangerous-approval", "用户已通过专门授权确认高风险能力。", risk)
            return self._prompt("dangerous-needs-dedicated-approval", "高风险能力必须走专门授权或回退接口。", risk)

        return self._forbid("unknown-risk", f"未知风险等级：{risk}", risk)

    def _assess_managed_command(self, payload: Any, context: ToolContext, risk: str) -> PermissionAssessment:
        if context.user_initiated or self._payload_approved(payload):
            return self._allow(
                "managed-command-approved",
                "自管理命令工具来自用户已确认的计划或显式授权，可在沙盒内执行。",
                risk,
            )
        return self._prompt(
            "managed-command-needs-approval",
            "自管理命令工具需要用户确认后才能在沙盒内执行。",
            risk,
        )

    def _assess_command(self, payload: Any, context: ToolContext, risk: str) -> PermissionAssessment:
        command = self._command_text(payload)
        if not command:
            return self._forbid("missing-command", "命令为空，已拒绝执行。", risk)

        if self._is_dangerous_command(command):
            return self._prompt(
                "dangerous-command",
                "命令包含高风险操作，不能通过普通 command.run 执行；请使用专门回退/同步接口或单独授权。",
                risk,
                proposed_prefix_rule=self._prefix_rule(command),
            )

        configured = self._config_rule_decision(command)
        if configured:
            return configured

        if self._is_trusted_command(command):
            if self._contains_shell_metachars(command):
                # command.run 用 shell 执行；带链式/重定向/子命令的输入即使
                # 前缀可信也可能携带任意第二条命令，必须走人工审批。
                return self._prompt(
                    "trusted-prefix-with-metachars",
                    "命令以可信前缀开头，但包含 &&、;、| 等 shell 连接符，需要用户确认完整命令。",
                    risk,
                    proposed_prefix_rule=self._prefix_rule(command),
                )
            return self._allow("trusted-prefix", "命中可信命令前缀，可在沙盒内执行。", risk)

        if context.user_initiated or self._payload_approved(payload):
            return self._allow(
                "plan-approved-command",
                "该命令来自用户已审查确认的工具计划，可在沙盒内执行。",
                risk,
                proposed_prefix_rule=self._prefix_rule(command),
            )

        return self._prompt(
            "untrusted-command-needs-approval",
            "非可信命令需要用户确认后才能在沙盒内执行。",
            risk,
            proposed_prefix_rule=self._prefix_rule(command),
        )

    def _config_rule_decision(self, command: str) -> PermissionAssessment | None:
        for rule in self.rules:
            if not isinstance(rule, dict):
                continue
            prefix = str(rule.get("prefix") or "").strip()
            decision = str(rule.get("decision") or "").strip().lower()
            if not prefix or not self._matches_prefix(command, prefix):
                continue
            if decision == "allow":
                if self._contains_shell_metachars(command):
                    return self._prompt(
                        rule.get("id") or "config-prefix-allow",
                        "命中持久化允许规则，但命令包含 shell 连接符，需要用户确认完整命令。",
                        "command",
                    )
                return self._allow(rule.get("id") or "config-prefix-allow", rule.get("description") or "命中持久化允许规则。", "command")
            if decision == "prompt":
                return self._prompt(rule.get("id") or "config-prefix-prompt", rule.get("description") or "命中持久化审批规则。", "command")
            if decision == "forbid":
                return self._forbid(rule.get("id") or "config-prefix-forbid", rule.get("description") or "命中持久化禁止规则。", "command")
        return None

    def _has_sandbox_repo(self, context: ToolContext) -> bool:
        return bool(context.conversation_id and context.sandbox_id and context.repo_path)

    def _repo_in_workspace(self, repo_path: str | None) -> bool:
        if not repo_path:
            return False
        root = WORKSPACE_ROOT.resolve()
        target = Path(repo_path).resolve()
        return target == root or root in target.parents

    def _command_text(self, payload: Any) -> str:
        if isinstance(payload, dict):
            value = payload.get("command") or payload.get("cmd") or ""
            if isinstance(value, list):
                return " ".join(str(item) for item in value)
            return str(value).strip()
        return str(payload).strip()

    def _payload_approved(self, payload: Any) -> bool:
        return isinstance(payload, dict) and bool(payload.get("approved"))

    def _payload_dedicated_approval(self, payload: Any) -> bool:
        return isinstance(payload, dict) and bool(payload.get("dedicatedApproval"))

    def _is_trusted_command(self, command: str) -> bool:
        normalized = self._normalize_command(command)
        return any(self._matches_prefix(normalized, prefix) for prefix in self.trusted_command_prefixes)

    def _matches_prefix(self, command: str, prefix: str) -> bool:
        normalized = self._normalize_command(command)
        normalized_prefix = self._normalize_command(prefix)
        return normalized == normalized_prefix or normalized.startswith(normalized_prefix + " ")

    def _is_dangerous_command(self, command: str) -> bool:
        return any(re.search(pattern, command, flags=re.IGNORECASE) for pattern in self.dangerous_command_patterns)

    _SHELL_METACHAR_PATTERN = re.compile(r"(&&|\|\||;|\||\$\(|`|>|<|\r|\n)")

    def _contains_shell_metachars(self, command: str) -> bool:
        return bool(self._SHELL_METACHAR_PATTERN.search(command))

    def _prefix_rule(self, command: str) -> list[str] | None:
        try:
            parts = shlex.split(command, posix=False)
        except ValueError:
            parts = command.split()
        if not parts:
            return None
        if len(parts) >= 3 and parts[0].lower() == "npm" and parts[1].lower() == "run":
            return parts[:3]
        if len(parts) >= 2 and parts[0].lower() == "git":
            return parts[:2]
        return parts[:1]

    def _normalize_command(self, command: str) -> str:
        return " ".join(str(command or "").strip().split())

    def _allow(
        self,
        rule_id: str,
        reason: str,
        risk: str,
        proposed_prefix_rule: list[str] | None = None,
    ) -> PermissionAssessment:
        return PermissionAssessment(True, False, reason, risk, "allow", rule_id, proposed_prefix_rule)

    def _prompt(
        self,
        rule_id: str,
        reason: str,
        risk: str,
        proposed_prefix_rule: list[str] | None = None,
    ) -> PermissionAssessment:
        return PermissionAssessment(False, True, reason, risk, "prompt", rule_id, proposed_prefix_rule)

    def _forbid(self, rule_id: str, reason: str, risk: str) -> PermissionAssessment:
        return PermissionAssessment(False, False, reason, risk, "forbid", rule_id)
