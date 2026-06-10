from __future__ import annotations

from typing import Any

from server_py.mcp.adapter import MCPAdapter
from server_py.tools.registry import ToolRegistry
from server_py.tools.types import ToolContext


class UnifiedToolRuntime:
    """Single Agent-facing tool runtime.

    Internal tools still live in ToolRegistry. External tools are discovered and
    executed through MCPAdapter. The Agent planner and executor should depend on
    this class instead of choosing a separate backend per tool source.
    """

    def __init__(self, registry: ToolRegistry, mcp: MCPAdapter) -> None:
        self.registry = registry
        self.mcp = mcp

    def list(self) -> list[dict[str, Any]]:
        return self.mcp.list_tools()

    def list_internal(self) -> list[dict[str, Any]]:
        return self.registry.list()

    def run(self, tool_id: str, payload: Any, context: ToolContext) -> dict[str, Any]:
        if tool_id.startswith("external."):
            return self.mcp.run_external_tool(tool_id, payload, context)
        return self.registry.run(tool_id, payload, context)
