from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class MCPHttpClient:
    """Small Streamable HTTP MCP client.

    The client follows the same conservative shape Codex uses for remote MCP:
    send JSON-RPC over HTTP, accept JSON or event-stream responses, preserve
    Mcp-Session-Id across the short handshake, and keep each operation
    stateless from the workbench runtime perspective.
    """

    def discover_tools(self, server: dict[str, Any], timeout_seconds: int = 8) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "serverId": server.get("id"),
            "transport": "http",
            "tools": [],
            "error": None,
            "httpStatus": None,
        }
        try:
            session_id = self._initialize(server, timeout_seconds)
            self._notify_initialized(server, session_id, timeout_seconds)
            response, status, _ = self._post(
                server,
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                session_id,
                timeout_seconds,
                expected_id=2,
            )
            result["httpStatus"] = status
            if response.get("error"):
                raise RuntimeError(f"tools/list 被拒绝：{response['error']}")
            tools = (response.get("result") or {}).get("tools", [])
            result["ok"] = True
            result["tools"] = tools if isinstance(tools, list) else []
        except Exception as error:
            result["error"] = str(error)
        return result

    def call_tool(
        self,
        server: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "serverId": server.get("id"),
            "transport": "http",
            "toolName": tool_name,
            "content": [],
            "structuredContent": None,
            "result": None,
            "error": None,
            "httpStatus": None,
        }
        try:
            session_id = self._initialize(server, timeout_seconds)
            self._notify_initialized(server, session_id, timeout_seconds)
            response, status, _ = self._post(
                server,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments or {}},
                },
                session_id,
                timeout_seconds,
                expected_id=2,
            )
            result["httpStatus"] = status
            if response.get("error"):
                raise RuntimeError(f"tools/call 被拒绝：{response['error']}")

            payload = response.get("result") or {}
            if not isinstance(payload, dict):
                payload = {"content": [{"type": "text", "text": str(payload)}]}
            result["ok"] = not bool(payload.get("isError"))
            result["content"] = payload.get("content", [])
            result["structuredContent"] = payload.get("structuredContent")
            result["result"] = payload
            if payload.get("isError"):
                result["error"] = self._content_text(payload.get("content", [])) or "MCP 工具返回错误。"
        except Exception as error:
            result["error"] = str(error)
        return result

    def _initialize(self, server: dict[str, Any], timeout_seconds: int) -> str | None:
        response, _, session_id = self._post(
            server,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "ai-delivery-workbench", "version": "0.1.0"},
                },
            },
            None,
            timeout_seconds,
            expected_id=1,
        )
        if response.get("error"):
            raise RuntimeError(f"initialize 被拒绝：{response['error']}")
        return session_id

    def _notify_initialized(self, server: dict[str, Any], session_id: str | None, timeout_seconds: int) -> None:
        try:
            self._post(
                server,
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                session_id,
                timeout_seconds,
                expected_id=None,
            )
        except Exception:
            # Some HTTP MCP servers respond with 202/204 or close notification
            # requests quickly. The next request proves whether the session is
            # usable, so notification failures should not hide the real cause.
            return

    def _post(
        self,
        server: dict[str, Any],
        message: dict[str, Any],
        session_id: str | None,
        timeout_seconds: int,
        expected_id: int | None,
    ) -> tuple[dict[str, Any], int | None, str | None]:
        url = str(server.get("url") or "").strip()
        if not url:
            raise RuntimeError("HTTP MCP server 缺少 url。")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            **self._configured_headers(server),
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(url, data=payload, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                status = response.status
                body = response.read()
                session = response.headers.get("Mcp-Session-Id") or session_id
                if status in {202, 204}:
                    return {}, status, session
                return self._decode_response(body, response.headers.get("Content-Type"), expected_id), status, session
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:2000]
            raise RuntimeError(f"HTTP {error.code}：{body or error.reason}") from error
        except URLError as error:
            raise RuntimeError(f"HTTP MCP 连接失败：{error.reason}") from error

    def _configured_headers(self, server: dict[str, Any]) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key in ("headers", "http_headers"):
            raw = server.get(key, {})
            if isinstance(raw, dict):
                headers.update({str(name): str(value) for name, value in raw.items() if value is not None})

        env_headers = server.get("env_http_headers", {})
        if isinstance(env_headers, dict):
            for header_name, env_name in env_headers.items():
                value = os.environ.get(str(env_name))
                if value:
                    headers[str(header_name)] = value

        bearer_env = server.get("bearer_token_env_var") or server.get("bearerTokenEnv") or server.get("authEnv")
        if bearer_env:
            token = os.environ.get(str(bearer_env))
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    def _decode_response(self, body: bytes, content_type: str | None, expected_id: int | None) -> dict[str, Any]:
        if content_type and content_type.lower().startswith("text/event-stream"):
            return self._decode_event_stream(body, expected_id)
        text = body.decode("utf-8", errors="replace")
        if not text.strip():
            return {}
        payload = json.loads(text)
        return self._select_message(payload, expected_id)

    def _decode_event_stream(self, body: bytes, expected_id: int | None) -> dict[str, Any]:
        text = body.decode("utf-8", errors="replace")
        messages: list[dict[str, Any]] = []
        block: list[str] = []
        for line in text.splitlines():
            if not line.strip():
                self._collect_sse_block(block, messages)
                block = []
                continue
            block.append(line)
        self._collect_sse_block(block, messages)
        return self._select_message(messages, expected_id)

    def _collect_sse_block(self, block: list[str], messages: list[dict[str, Any]]) -> None:
        data_lines = [line[5:].strip() for line in block if line.startswith("data:")]
        if not data_lines:
            return
        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            return
        payload = json.loads(data)
        if isinstance(payload, dict):
            messages.append(payload)

    def _select_message(self, payload: Any, expected_id: int | None) -> dict[str, Any]:
        if isinstance(payload, list):
            candidates = [item for item in payload if isinstance(item, dict)]
            if expected_id is None:
                return candidates[-1] if candidates else {}
            for item in candidates:
                if item.get("id") == expected_id:
                    return item
            return candidates[-1] if candidates else {}
        if isinstance(payload, dict):
            return payload
        return {"result": payload}

    def _content_text(self, content: Any) -> str:
        if not isinstance(content, list):
            return ""
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(part for part in parts if part).strip()
