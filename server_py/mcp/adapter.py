from __future__ import annotations

import os
import json
import shutil
import time
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import PROJECT_ROOT
from server_py.mcp.http_client import MCPHttpClient
from server_py.mcp.stdio_client import MCPStdioClient
from server_py.observability.metrics import MetricStore
from server_py.runtime.approval_store import ApprovalStore
from server_py.runtime.events import EventStore
from server_py.tools.registry import ToolRegistry
from server_py.tools.types import ToolContext


MCP_SERVERS_PATH = PROJECT_ROOT / "config" / "mcp-servers.json"

TOOL_PRIORITY: dict[str, tuple[float, str, list[str]]] = {
    "code.search_files": (0.96, "先定位相关文件，减少无目标读取。", ["代码", "上下文", "搜索"]),
    "code.read_file": (0.94, "读取目标文件内容，是生成计划和 patch 前的必需证据。", ["代码", "上下文", "读取"]),
    "code.git_diff": (0.9, "查看沙盒当前变更，确认 patch、回退和交付范围。", ["diff", "回退", "交付"]),
    "verification.run": (0.88, "运行 build/typecheck/lint/test，给 Verifier 提供结构化证据。", ["验证", "测试", "交付"]),
    "code.apply_patch": (0.84, "批量写入前自动 checkpoint，适合执行已审查修复。", ["写入", "checkpoint", "patch"]),
    "browser.preview_smoke": (0.82, "预览页面并保存 smoke 证据，适合前端交付验收。", ["浏览器", "预览", "截图"]),
    "command.run": (0.78, "运行沙盒命令，适合安装依赖、启动脚本和补充验证。", ["命令", "沙盒", "验证"]),
    "github.inspect_repository": (0.72, "确认当前沙盒 remote、分支和 HEAD，避免改错仓库。", ["GitHub", "仓库", "审计"]),
    "code.write_file": (0.68, "单文件写入能力，适合小范围明确修改。", ["写入", "checkpoint"]),
}

QUERY_HINTS: dict[str, tuple[float, list[str], str]] = {
    "预览": (0.16, ["browser.preview_smoke", "command.run"], "当前需求涉及预览，优先推荐浏览器 smoke 和预览命令。"),
    "browser": (0.16, ["browser.preview_smoke"], "需求提到浏览器，优先收集页面证据。"),
    "截图": (0.14, ["browser.preview_smoke"], "需求提到截图，优先使用浏览器预览验证。"),
    "验证": (0.16, ["verification.run", "command.run"], "需求提到验证，优先运行结构化验证命令。"),
    "测试": (0.16, ["verification.run", "command.run"], "需求提到测试，优先运行结构化验证命令。"),
    "diff": (0.14, ["code.git_diff"], "需求提到 diff，优先查看沙盒变更。"),
    "回退": (0.14, ["code.git_diff"], "需求提到回退，优先查看变更和 checkpoint 证据。"),
    "github": (0.14, ["github.inspect_repository"], "需求提到 GitHub，优先确认仓库远程信息。"),
    "mcp": (0.12, ["external."], "需求提到 MCP，可优先查看已发现外部工具。"),
    "代码": (0.12, ["code.search_files", "code.read_file", "code.apply_patch"], "需求涉及代码修改，优先读取上下文再写入。"),
}


class MCPAdapter:
    """MCP-style facade for internal tools and external MCP servers."""

    def __init__(
        self,
        tools: ToolRegistry,
        events: EventStore,
        approvals: ApprovalStore | None = None,
        metrics: MetricStore | None = None,
    ) -> None:
        self.tools = tools
        self.events = events
        self.approvals = approvals
        self.metrics = metrics
        self.stdio_client = MCPStdioClient()
        self.http_client = MCPHttpClient()
        self._external_tools: list[dict[str, Any]] = []
        self._external_tool_index: dict[str, dict[str, Any]] = {}
        self._discovery_results: list[dict[str, Any]] = []

    def manifest(self) -> dict[str, Any]:
        servers = self.server_statuses()
        internal_tools = self.tools.list()
        tools = [self._tool_manifest(tool) for tool in internal_tools] + self._external_tools
        return {
            "version": 1,
            "mode": "internal-first",
            "adapter": "python-mcp-adapter",
            "capabilities": {
                "internalTools": True,
                "externalServers": bool(servers),
                "dynamicExternalExecution": True,
                "externalServerDiagnostics": True,
                "stdioToolDiscovery": True,
                "stdioToolCall": True,
                "httpToolDiscovery": True,
                "httpToolCall": True,
                "sseConfig": True,
                "wsConfig": True,
                "sseToolCall": False,
                "wsToolCall": False,
                "approvalAware": True,
                "sandboxScoped": True,
            },
            "servers": servers,
            "tools": self._rank_tools(tools),
        }

    def config(self) -> dict[str, Any]:
        config = self._config()
        config["updatedAt"] = config.get("updatedAt")
        return config

    def save_config(self, value: dict[str, Any]) -> dict[str, Any]:
        validation = self.validate_config(value)
        if not validation["ok"]:
            message = "；".join(item["message"] for item in validation["errors"][:3])
            raise RuntimeError(f"MCP 配置校验失败：{message}")
        normalized = validation["normalized"]
        payload = {"version": normalized["version"], "servers": normalized["servers"], "updatedAt": now_iso()}
        write_json(MCP_SERVERS_PATH, payload)
        self._external_tools = []
        self._external_tool_index = {}
        self._discovery_results = []
        return self.config()

    def validate_config(self, value: dict[str, Any]) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if not isinstance(value, dict):
            return {
                "ok": False,
                "errors": [{"path": "$", "message": "MCP 配置必须是 JSON 对象。"}],
                "warnings": [],
                "normalized": {"version": 1, "servers": []},
            }

        try:
            version = int(value.get("version") or 1)
        except (TypeError, ValueError):
            version = 1
            warnings.append({"path": "$.version", "message": "version 不是数字，已按 1 处理。"})

        servers = value.get("servers", [])
        if not isinstance(servers, list):
            errors.append({"path": "$.servers", "message": "servers 必须是数组。"})
            servers = []

        normalized_servers: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, raw_server in enumerate(servers):
            path = f"$.servers[{index}]"
            if not isinstance(raw_server, dict):
                errors.append({"path": path, "message": "server 配置必须是对象。"})
                continue
            server = dict(raw_server)
            server_id = str(server.get("id") or "").strip()
            if server_id in seen_ids:
                errors.append({"path": f"{path}.id", "message": f"server id 重复：{server_id}。"})
            if server_id:
                seen_ids.add(server_id)

            status = self._server_status(server)
            if status.get("transport") and not server.get("transport"):
                server["transport"] = status["transport"]
            for problem in status.get("problems", []):
                errors.append({"path": path, "message": str(problem)})
            if server.get("enabled") and status.get("transport") == "http":
                warnings.append(
                    {
                        "path": path,
                        "message": "HTTP MCP 已支持 tools/list 和 tools/call；OAuth 自动登录和长连接恢复仍会在后续补齐。",
                    }
                )
            if server.get("enabled") and status.get("transport") in {"sse", "ws"}:
                warnings.append(
                    {
                        "path": path,
                        "message": "SSE/WS 配置会保存并诊断，但当前还不会建立长连接执行工具。",
                    }
                )
            auth_env = server.get("bearer_token_env_var") or server.get("bearerTokenEnv") or server.get("authEnv")
            if server.get("enabled") and auth_env and not os.environ.get(str(auth_env)):
                warnings.append({"path": path, "message": f"认证环境变量 {auth_env} 当前未设置，调用时可能失败。"})
            if status.get("transport") == "stdio" and str(server.get("command") or "").lower() in {"npx", "uvx"}:
                warnings.append(
                    {
                        "path": path,
                        "message": "stdio server 依赖外部包管理器，首次发现可能较慢；建议在演示前先执行一次发现。",
                    }
                )
            normalized_servers.append(server)

        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "normalized": {"version": version, "servers": normalized_servers},
        }

    def list_tools(self, query: str | None = None) -> list[dict[str, Any]]:
        return self._rank_tools(self.manifest()["tools"], query)

    def history(self, conversation_id: str, tool_id: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        events = self.events.list(conversation_id, max(limit * 4, 120))
        relevant_types = {
            "mcp.tool.dispatch",
            "mcp.external.call.begin",
            "mcp.external.call.end",
            "tool.call.begin",
            "tool.call.end",
            "approval.requested",
        }
        for event in events:
            event_type = str(event.get("type") or "")
            if event_type not in relevant_types:
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            event_tool_id = payload.get("toolId")
            if tool_id and event_tool_id != tool_id:
                continue
            if not event_tool_id:
                continue
            rows.append(self._history_entry(event, payload))
        return rows[-limit:]

    def replay_history_entry(self, conversation_id: str, history_entry_id: str, context: ToolContext) -> dict[str, Any]:
        entry = self._history_by_id(conversation_id, history_entry_id)
        if not entry:
            raise RuntimeError("找不到可重放的 MCP 调用历史。")
        tool_id = str(entry.get("toolId") or "")
        if not tool_id:
            raise RuntimeError("历史记录缺少 toolId，不能重放。")
        payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
        input_payload = payload.get("input")
        if not isinstance(input_payload, dict):
            raise RuntimeError("这条历史没有保存可重放输入。只有新版本产生的调用历史支持重放。")
        replay_payload = dict(input_payload)
        replay_payload["approved"] = True
        self.events.append(
            conversation_id,
            "mcp.tool.replay.requested",
            {
                "historyEntryId": history_entry_id,
                "eventId": entry.get("eventId"),
                "toolId": tool_id,
                "planId": entry.get("planId"),
                "stepId": entry.get("stepId"),
            },
            actor="user",
        )
        replay_context = ToolContext(
            conversation_id=context.conversation_id,
            sandbox_id=context.sandbox_id,
            repo_path=context.repo_path,
            plan_id=entry.get("planId"),
            step_id=entry.get("stepId"),
            sandbox_mode=context.sandbox_mode,
            approval_mode=context.approval_mode,
            user_initiated=True,
        )
        result = self.run_tool(tool_id, replay_payload, replay_context)
        self.events.append(
            conversation_id,
            "mcp.tool.replay.completed",
            {
                "historyEntryId": history_entry_id,
                "toolId": tool_id,
                "planId": entry.get("planId"),
                "stepId": entry.get("stepId"),
                "ok": bool(result.get("ok")),
                "summary": result.get("summary"),
            },
            actor="runtime",
        )
        return {
            "ok": bool(result.get("ok")),
            "summary": f"已重放 MCP 调用：{result.get('summary') or tool_id}",
            "historyEntryId": history_entry_id,
            "toolId": tool_id,
            "planId": entry.get("planId"),
            "stepId": entry.get("stepId"),
            "result": result,
        }

    def server_statuses(self) -> list[dict[str, Any]]:
        statuses = [self._server_status(server) for server in self._config_servers()]
        by_id = {item.get("serverId"): item for item in self._discovery_results}
        for status in statuses:
            discovery = by_id.get(status.get("id"))
            if discovery:
                status["toolDiscovery"] = "ready" if discovery.get("ok") else "failed"
                status["toolCount"] = len(discovery.get("tools", []))
                status["discoveryError"] = discovery.get("error")
        return statuses

    def _history_by_id(self, conversation_id: str, history_entry_id: str) -> dict[str, Any] | None:
        candidates = self.history(conversation_id, limit=200)
        for item in reversed(candidates):
            if item.get("id") == history_entry_id or item.get("eventId") == history_entry_id:
                return item
        return None

    def discover_external_tools(self, timeout_seconds: int = 8) -> dict[str, Any]:
        statuses = self.server_statuses()
        servers_by_id = {str(server.get("id")): server for server in self._config_servers() if server.get("id")}
        results: list[dict[str, Any]] = []
        tools: list[dict[str, Any]] = []
        tool_index: dict[str, dict[str, Any]] = {}

        for status in statuses:
            if status.get("status") != "configured":
                continue
            transport = status.get("transport")
            if transport in {"sse", "ws"}:
                results.append(
                    {
                        "serverId": status.get("id"),
                        "ok": False,
                        "tools": [],
                        "transport": transport,
                        "error": f"{transport} MCP 长连接执行仍在框架待办中；请先使用 stdio 或 http transport。",
                    }
                )
                continue

            server = servers_by_id.get(str(status.get("id")))
            if not server:
                continue
            if transport == "stdio":
                result = self.stdio_client.discover_tools(server, timeout_seconds)
            elif transport == "http":
                result = self.http_client.discover_tools(server, timeout_seconds)
            else:
                continue
            results.append(result)
            if result.get("ok"):
                for tool in result.get("tools", []):
                    manifest = self._external_tool_manifest(server, tool)
                    tools.append(manifest)
                    tool_index[manifest["id"]] = {
                        "serverId": manifest["serverId"],
                        "toolName": str(tool.get("name") or manifest["name"]),
                        "server": server,
                        "transport": transport,
                        "manifest": manifest,
                    }

        self._external_tools = tools
        self._external_tool_index = tool_index
        self._discovery_results = results
        return {
            "ok": all(item.get("ok") for item in results) if results else True,
            "serverCount": len(results),
            "toolCount": len(tools),
            "results": results,
            "tools": tools,
        }

    def run_tool(self, tool_id: str, payload: Any, context: ToolContext) -> dict[str, Any]:
        if not tool_id.startswith("external."):
            return self.run_internal_tool(tool_id, payload, context)
        return self.run_external_tool(tool_id, payload, context)

    def run_internal_tool(self, tool_id: str, payload: Any, context: ToolContext) -> dict[str, Any]:
        self.events.append(
            context.conversation_id,
            "mcp.tool.dispatch",
            {
                "toolId": tool_id,
                "source": "internal",
                "sandboxId": context.sandbox_id,
                "planId": context.plan_id,
                "stepId": context.step_id,
                "input": self._safe_payload(payload),
            },
            actor="runtime",
        )
        return self.tools.run(tool_id, payload, context)

    def run_external_tool(self, tool_id: str, payload: Any, context: ToolContext) -> dict[str, Any]:
        started = time.perf_counter()
        payload = payload if isinstance(payload, dict) else {"value": payload}
        entry = self._external_tool_index.get(tool_id)
        if not entry:
            self.discover_external_tools()
            entry = self._external_tool_index.get(tool_id)
        if not entry:
            return {
                "ok": False,
                "summary": "外部 MCP 工具尚未发现，请先检查 MCP 配置并执行发现。",
                "error": f"Unknown external MCP tool: {tool_id}",
            }

        grant = self._approval_grant(tool_id, payload, context)
        call_payload = {
            "toolId": tool_id,
            "toolName": entry["toolName"],
            "serverId": entry["serverId"],
            "transport": entry.get("transport") or entry.get("server", {}).get("transport"),
            "planId": context.plan_id,
            "stepId": context.step_id,
            "sandboxId": context.sandbox_id,
            "riskLevel": "external",
            "inputSummary": self._summarize(payload),
            "input": self._safe_payload(payload),
            "permission": {
                "allowed": bool(context.user_initiated or payload.get("approved") or grant),
                "needsApproval": not bool(context.user_initiated or payload.get("approved") or grant),
                "grantId": grant.get("id") if grant else None,
            },
        }
        self.events.append(context.conversation_id, "mcp.tool.dispatch", {**call_payload, "source": "external"}, actor="runtime")
        self.events.append(context.conversation_id, "tool.call.begin", call_payload, actor="agent")

        if call_payload["permission"]["needsApproval"]:
            result = {
                "ok": False,
                "summary": "外部 MCP 工具会把上下文发送给外部能力，需用户确认后执行。",
                "needsApproval": True,
                "riskLevel": "external",
                "error": "External MCP tool requires approval.",
            }
            self.events.append(context.conversation_id, "approval.requested", call_payload, actor="runtime")
            self.events.append(
                context.conversation_id,
                "tool.call.end",
                {"toolId": tool_id, "planId": context.plan_id, "stepId": context.step_id, "ok": False, "summary": result["summary"]},
                actor="runtime",
            )
            self._record_metric(context, tool_id, started, False)
            return result

        arguments = self._tool_arguments(payload)
        timeout_seconds = self._timeout_seconds(payload)
        self.events.append(
            context.conversation_id,
            "mcp.external.call.begin",
            {
                "toolId": tool_id,
                "serverId": entry["serverId"],
                "toolName": entry["toolName"],
                "transport": entry.get("transport"),
                "endpoint": entry.get("server", {}).get("url"),
                "planId": context.plan_id,
                "stepId": context.step_id,
            },
            actor="runtime",
        )
        if entry.get("transport") == "http":
            call_result = self.http_client.call_tool(entry["server"], entry["toolName"], arguments, timeout_seconds)
        else:
            call_result = self.stdio_client.call_tool(entry["server"], entry["toolName"], arguments, timeout_seconds)
        ok = bool(call_result.get("ok"))
        summary = "外部 MCP 工具执行完成。" if ok else f"外部 MCP 工具执行失败：{call_result.get('error') or '未知错误'}"
        result = {
            "ok": ok,
            "summary": summary,
            "riskLevel": "external",
            "data": call_result,
        }
        if not ok:
            result["error"] = call_result.get("error") or summary
        self.events.append(
            context.conversation_id,
            "mcp.external.call.end",
            {
                "toolId": tool_id,
                "serverId": entry["serverId"],
                "transport": entry.get("transport"),
                "planId": context.plan_id,
                "stepId": context.step_id,
                "ok": ok,
                "summary": summary,
                "result": self._safe_payload(call_result),
            },
            actor="runtime",
        )
        self.events.append(
            context.conversation_id,
            "tool.call.end",
            {
                "toolId": tool_id,
                "planId": context.plan_id,
                "stepId": context.step_id,
                "ok": ok,
                "summary": summary,
                "result": self._safe_payload(result),
            },
            actor="runtime",
        )
        self._record_metric(context, tool_id, started, ok)
        return result

    def _approval_grant(self, tool_id: str, payload: dict[str, Any], context: ToolContext) -> dict[str, Any] | None:
        if context.user_initiated or payload.get("approved") or not self.approvals:
            return None
        return self.approvals.consume_matching(context.conversation_id, tool_id, "external", payload)

    def _tool_arguments(self, payload: dict[str, Any]) -> dict[str, Any]:
        arguments = payload.get("arguments")
        if isinstance(arguments, dict):
            return arguments
        return {key: value for key, value in payload.items() if key not in {"approved", "timeoutSeconds"}}

    def _timeout_seconds(self, payload: dict[str, Any]) -> int:
        try:
            timeout = int(payload.get("timeoutSeconds") or 15)
        except (TypeError, ValueError):
            return 15
        return max(1, min(timeout, 120))

    def _tool_manifest(self, tool: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": tool["id"],
            "mcpName": f"internal.{tool['id']}",
            "source": "internal",
            "name": tool.get("name"),
            "description": tool.get("description"),
            "riskLevel": tool.get("riskLevel"),
            "requiresCheckpoint": tool.get("requiresCheckpoint"),
            "inputSchema": tool.get("inputSchema", {}),
            "schemaSummary": self._schema_summary(tool.get("inputSchema", {})),
            "approvalAware": tool.get("riskLevel") in {"command", "external", "dangerous"},
            "sandboxScoped": True,
            "capabilityTags": self._capability_tags(tool["id"], tool.get("description", "")),
        }

    def _external_tool_manifest(self, server: dict[str, Any], tool: dict[str, Any]) -> dict[str, Any]:
        server_id = str(server.get("id"))
        tool_name = str(tool.get("name") or "unnamed")
        input_schema = tool.get("inputSchema") or tool.get("schema") or {}
        normalized_input_schema = self._normalize_input_schema(input_schema)
        transport = self._transport(server)
        return {
            "id": f"external.{self._safe_id(server_id)}.{self._safe_id(tool_name)}",
            "mcpName": f"{server_id}.{tool_name}",
            "source": "external",
            "serverId": server_id,
            "transport": transport,
            "endpoint": server.get("url"),
            "name": tool_name,
            "description": tool.get("description") or "",
            "riskLevel": "external",
            "requiresCheckpoint": False,
            "inputSchema": normalized_input_schema,
            "schemaSummary": self._schema_summary(normalized_input_schema),
            "approvalAware": True,
            "sandboxScoped": False,
            "capabilityTags": self._capability_tags(f"external.{server_id}.{tool_name}", tool.get("description") or ""),
        }

    def _config(self) -> dict[str, Any]:
        config = read_json(MCP_SERVERS_PATH, {"version": 1, "servers": []})
        return config if isinstance(config, dict) else {"version": 1, "servers": []}

    def _config_servers(self) -> list[dict[str, Any]]:
        servers = self._config().get("servers", [])
        return [server for server in servers if isinstance(server, dict)] if isinstance(servers, list) else []

    def _server_status(self, server: dict[str, Any]) -> dict[str, Any]:
        enabled = bool(server.get("enabled", False))
        transport = self._transport(server)
        problems: list[str] = []
        if not server.get("id"):
            problems.append("缺少 id。")
        if transport not in {"stdio", "http", "sse", "ws"}:
            problems.append("transport 必须是 stdio、http、sse 或 ws。")

        details: dict[str, Any] = {}
        if transport == "stdio":
            command = str(server.get("command") or "").strip()
            if not command:
                problems.append("stdio MCP server 缺少 command。")
            else:
                resolved = self._resolve_command(command)
                details["command"] = command
                details["resolvedCommand"] = resolved
                if not resolved:
                    problems.append(f"找不到 stdio command：{command}。")
            args = server.get("args", [])
            if args is not None and not isinstance(args, list):
                problems.append("args 必须是数组。")
            details["args"] = args if isinstance(args, list) else []
        elif transport in {"http", "sse", "ws"}:
            url = str(server.get("url") or "").strip()
            if not url:
                problems.append(f"{transport} MCP server 缺少 url。")
            else:
                parsed = urlparse(url)
                valid_schemes = {"http": {"http", "https"}, "sse": {"http", "https"}, "ws": {"ws", "wss"}}[transport]
                if parsed.scheme not in valid_schemes or not parsed.netloc:
                    problems.append(f"{transport} MCP server url 不合法：{url}。")
                details["url"] = url
                details["endpoint"] = url
            for key in ("headers", "http_headers", "env_http_headers"):
                value = server.get(key, {})
                if value is not None and not isinstance(value, dict):
                    problems.append(f"{key} 必须是对象。")
            timeout = server.get("timeoutSeconds") or server.get("timeout_seconds")
            if timeout is not None:
                try:
                    timeout_value = int(timeout)
                    if timeout_value < 1 or timeout_value > 120:
                        problems.append("timeoutSeconds 必须在 1 到 120 秒之间。")
                    else:
                        details["timeoutSeconds"] = timeout_value
                except (TypeError, ValueError):
                    problems.append("timeoutSeconds 必须是数字。")
            auth_env = server.get("bearer_token_env_var") or server.get("bearerTokenEnv") or server.get("authEnv")
            if auth_env:
                details["authEnv"] = str(auth_env)

        env = server.get("env", {})
        if env is not None and not isinstance(env, dict):
            problems.append("env 必须是对象。")
        details["envKeys"] = sorted((env or {}).keys()) if isinstance(env, dict) else []
        status = "disabled" if not enabled else ("misconfigured" if problems else "configured")
        return {
            "id": server.get("id"),
            "name": server.get("name") or server.get("id"),
            "transport": transport or None,
            "endpoint": details.get("url") or details.get("command"),
            "enabled": enabled,
            "status": status,
            "problems": problems,
            "details": details,
            "toolDiscovery": "pending" if status == "configured" else "unavailable",
        }

    def _transport(self, server: dict[str, Any]) -> str:
        transport = str(server.get("transport") or "").strip().lower()
        if transport:
            return transport
        if server.get("command"):
            return "stdio"
        if server.get("url"):
            return "http"
        return ""

    def _resolve_command(self, command: str) -> str | None:
        path = Path(command)
        if path.is_absolute():
            return str(path) if path.exists() else None
        return shutil.which(command)

    def _safe_id(self, value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in value)

    def _normalize_input_schema(self, schema: Any) -> dict[str, Any]:
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}}
        normalized = dict(schema)
        if not isinstance(normalized.get("properties"), dict):
            normalized["properties"] = {}
        if not normalized.get("type"):
            normalized["type"] = "object"
        return normalized

    def _summarize(self, payload: Any) -> str:
        try:
            import json

            text = json.dumps(payload, ensure_ascii=False)
        except TypeError:
            text = str(payload)
        return text[:1000] + "..." if len(text) > 1000 else text

    def _rank_tools(self, tools: list[dict[str, Any]], query: str | None = None) -> list[dict[str, Any]]:
        query_text = (query or "").lower()
        ranked: list[dict[str, Any]] = []
        for tool in tools:
            item = dict(tool)
            score, base_reason, signals = TOOL_PRIORITY.get(str(item.get("id")), (0.55, "可通过统一工具运行时调用。", []))
            if item.get("source") == "external":
                score = max(score, 0.62)
                base_reason = "外部 MCP 工具，适合补充内置工具没有覆盖的能力；调用前需要审批。"
                signals = [*signals, "外部 MCP", "需审批"]
            searchable = " ".join(
                str(value or "").lower()
                for value in [item.get("id"), item.get("name"), item.get("description"), item.get("mcpName"), item.get("serverId")]
            )
            for hint, (bonus, prefixes, reason) in QUERY_HINTS.items():
                if hint.lower() not in query_text:
                    continue
                if any(str(item.get("id", "")).startswith(prefix) or prefix in searchable for prefix in prefixes):
                    score += bonus
                    base_reason = reason
                    signals.append(f"匹配：{hint}")
            if query_text and any(token in searchable for token in self._tokens(query_text)):
                score += 0.08
                signals.append("文本匹配")
            if item.get("requiresCheckpoint"):
                signals.append("写入前 checkpoint")
            if item.get("approvalAware"):
                signals.append("审批保护")
            item["recommendationScore"] = round(min(score, 1.0), 3)
            item["recommendationReason"] = base_reason
            item["recommendationSignals"] = self._dedupe(signals)[:6]
            item["capabilityTags"] = self._dedupe([*(item.get("capabilityTags") or []), *signals])[:8]
            ranked.append(item)
        return sorted(ranked, key=lambda item: (-float(item.get("recommendationScore") or 0), str(item.get("source") != "internal"), str(item.get("id"))))

    def _tokens(self, text: str) -> list[str]:
        return [token.lower() for token in re.findall(r"[a-zA-Z0-9_.-]+|[\u4e00-\u9fff]+", text) if token.strip()]

    def _capability_tags(self, tool_id: str, description: str) -> list[str]:
        text = f"{tool_id} {description}".lower()
        tags: list[str] = []
        if "code." in tool_id:
            tags.append("代码")
        if "command" in text or "命令" in description:
            tags.append("命令")
        if "verification" in text or "验证" in description or "test" in text:
            tags.append("验证")
        if "browser" in text or "预览" in description or "smoke" in text:
            tags.append("浏览器")
        if "github" in text or "git" in text:
            tags.append("GitHub")
        if tool_id.startswith("external."):
            tags.append("外部 MCP")
        return self._dedupe(tags)

    def _history_entry(self, event: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        event_type = str(event.get("type") or "")
        ok = payload.get("ok")
        needs_approval = bool(payload.get("needsApproval") or (isinstance(payload.get("permission"), dict) and payload["permission"].get("needsApproval")))
        tool_id = str(payload.get("toolId") or "")
        tool = self._tool_by_id(tool_id)
        input_value = self._history_input(payload)
        result_value = payload.get("result") if "result" in payload else None
        if needs_approval or event_type == "approval.requested":
            status = "needs_approval"
        elif ok is True:
            status = "completed"
        elif ok is False:
            status = "failed"
        else:
            status = "running" if event_type.endswith(".begin") or event_type == "mcp.tool.dispatch" else "unknown"
        return {
            "id": f"hist_{event.get('id')}",
            "eventId": event.get("id"),
            "conversationId": event.get("conversationId"),
            "toolId": tool_id,
            "toolName": payload.get("toolName") or (tool or {}).get("name"),
            "serverId": payload.get("serverId") or (tool or {}).get("serverId"),
            "transport": payload.get("transport") or (tool or {}).get("transport"),
            "planId": payload.get("planId"),
            "stepId": payload.get("stepId"),
            "type": event_type,
            "source": payload.get("source") or (tool or {}).get("source") or ("external" if tool_id.startswith("external.") else "internal"),
            "status": status,
            "summary": payload.get("summary") or payload.get("inputSummary") or event_type,
            "inputSummary": payload.get("inputSummary"),
            "schemaSummary": (tool or {}).get("schemaSummary") or self._schema_summary((tool or {}).get("inputSchema")),
            "inputPreview": self._payload_preview(input_value),
            "resultPreview": self._payload_preview(result_value),
            "approval": self._approval_summary(payload, needs_approval),
            "result": payload.get("result"),
            "payload": self._safe_payload(payload),
            "createdAt": event.get("createdAt"),
        }

    def _tool_by_id(self, tool_id: str) -> dict[str, Any] | None:
        if not tool_id:
            return None
        if tool_id.startswith("external."):
            return self._external_tool_index.get(tool_id)
        for tool in self.tools.list():
            if tool.get("id") == tool_id:
                return self._tool_manifest(tool)
        return None

    def _history_input(self, payload: dict[str, Any]) -> Any:
        value = payload.get("input")
        if value is not None:
            return value
        arguments = payload.get("arguments")
        if arguments is not None:
            return arguments
        if "request" in payload:
            return payload.get("request")
        return None

    def _schema_summary(self, schema: Any) -> dict[str, Any] | None:
        if not isinstance(schema, dict):
            return None
        required_raw = schema.get("required")
        required = [str(item) for item in required_raw if isinstance(item, str)] if isinstance(required_raw, list) else []
        required_set = set(required)
        properties_raw = schema.get("properties")
        properties: list[dict[str, Any]] = []
        if isinstance(properties_raw, dict):
            for name, raw_property in properties_raw.items():
                property_schema = raw_property if isinstance(raw_property, dict) else {}
                enum_raw = property_schema.get("enum")
                enum = [str(item) for item in enum_raw[:12]] if isinstance(enum_raw, list) else None
                properties.append(
                    {
                        "name": str(name),
                        "type": self._schema_type(property_schema),
                        "required": str(name) in required_set,
                        "description": str(property_schema.get("description") or ""),
                        **({"enum": enum} if enum else {}),
                    }
                )
        return {
            "type": str(schema.get("type") or "object"),
            "required": required,
            "propertyCount": len(properties_raw) if isinstance(properties_raw, dict) else 0,
            "properties": properties[:40],
        }

    def _schema_type(self, schema: dict[str, Any]) -> str:
        raw_type = schema.get("type")
        if isinstance(raw_type, list):
            return " | ".join(str(item) for item in raw_type)
        if isinstance(raw_type, str):
            return raw_type
        if "enum" in schema:
            return "enum"
        if "items" in schema:
            return "array"
        if "properties" in schema:
            return "object"
        return "unknown"

    def _payload_preview(self, value: Any, max_text: int = 2200) -> dict[str, Any] | None:
        if value is None:
            return None
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            text = str(value)
        byte_count = len(text.encode("utf-8"))
        truncated = len(text) > max_text
        return {
            "text": f"{text[:max_text]}...[已截断]" if truncated else text,
            "truncated": truncated,
            "bytes": byte_count,
            "kind": type(value).__name__,
        }

    def _approval_summary(self, payload: dict[str, Any], needs_approval: bool) -> dict[str, Any] | None:
        permission = payload.get("permission") if isinstance(payload.get("permission"), dict) else {}
        if not needs_approval and not permission and "approved" not in payload:
            return None
        return {
            "needsApproval": needs_approval,
            "allowed": payload.get("approved") if "approved" in payload else permission.get("allowed"),
            "grantId": permission.get("grantId"),
            "reason": str(permission.get("reason") or payload.get("approvalReason") or ""),
            "riskLevel": str(payload.get("riskLevel") or permission.get("riskLevel") or ""),
        }

    def _safe_payload(self, value: Any, max_text: int = 8000) -> Any:
        if isinstance(value, dict):
            return {str(key): self._safe_payload(item, max_text) for key, item in value.items()}
        if isinstance(value, list):
            return [self._safe_payload(item, max_text) for item in value[:80]]
        if isinstance(value, str):
            return value[:max_text] + "...[已截断]" if len(value) > max_text else value
        return value

    def _dedupe(self, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    def _record_metric(self, context: ToolContext, tool_id: str, started: float, ok: bool) -> None:
        if not self.metrics:
            return
        self.metrics.record_tool_call(context.conversation_id, tool_id, int((time.perf_counter() - started) * 1000), ok, "external")
