from __future__ import annotations

from server_py.runtime.events import EventStore
from server_py.runtime.permissions import PermissionPolicy
from server_py.sandbox.checkpoint_manager import CheckpointManager
from server_py.observability.metrics import MetricStore
from server_py.runtime.approval_store import ApprovalStore
from server_py.tools.code_tools import create_code_tools
from server_py.tools.command_tools import create_command_tools
from server_py.tools.browser_tools import create_browser_tools
from server_py.tools.github_tools import create_github_tools
from server_py.tools.registry import ToolRegistry
from server_py.tools.verification_tools import create_verification_tools
from server_py.verification.runner import VerificationRunner
from server_py.preview.smoke_test import PreviewSmokeTester


def create_tool_registry(
    events: EventStore,
    policy: PermissionPolicy,
    checkpoints: CheckpointManager,
    metrics: MetricStore | None = None,
    verification_runner: VerificationRunner | None = None,
    approvals: ApprovalStore | None = None,
    preview_smoke: PreviewSmokeTester | None = None,
) -> ToolRegistry:
    registry = ToolRegistry(events, policy, metrics, approvals)
    tools = [*create_code_tools(checkpoints), *create_command_tools(), *create_github_tools()]
    if verification_runner:
        tools.extend(create_verification_tools(verification_runner))
    if preview_smoke:
        tools.extend(create_browser_tools(preview_smoke))
    for tool in tools:
        registry.register(tool)
    return registry
