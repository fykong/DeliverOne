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


class ToolRunner(Protocol):
    def list(self) -> list[dict[str, Any]]:
        ...

    def run(self, tool_id: str, payload: Any, context: ToolContext) -> dict[str, Any]:
        ...
