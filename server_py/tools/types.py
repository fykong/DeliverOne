from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class ToolContext:
    conversation_id: str
    sandbox_id: str | None = None
    repo_path: str | None = None
    plan_id: str | None = None
    step_id: str | None = None
    sandbox_mode: str = "workspace_write"
    approval_mode: str = "untrusted"
    user_initiated: bool = False


@dataclass(frozen=True)
class AgentTool:
    id: str
    name: str
    description: str
    risk_level: str
    run: Callable[[Any, ToolContext], dict[str, Any]]
    requires_checkpoint: bool = False
    input_schema: dict[str, Any] | None = None
    # 自管理命令工具：payload 不携带 shell 命令，由工具内部决定要执行什么
    # （如 verification.run 按栈选择验证命令、browser.preview_smoke 只访问
    # 本地预览端口）。权限层对这类工具走「确认后放行 / 否则审批」，
    # 而不是因缺少 command 字段直接 forbid。
    managed_command: bool = False


class ToolRunner(Protocol):
    def list(self) -> list[dict[str, Any]]:
        ...

    def run(self, tool_id: str, payload: Any, context: ToolContext) -> dict[str, Any]:
        ...
