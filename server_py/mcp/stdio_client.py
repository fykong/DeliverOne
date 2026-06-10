from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Any


class MCPStdioClient:
    """Stateless MCP stdio client.

    Each operation starts a fresh server process, performs the MCP handshake,
    executes one request, then terminates the process. This is slower than a
    long-lived session, but it is predictable and easy to audit for the first
    stable runtime.
    """

    def discover_tools(self, server: dict[str, Any], timeout_seconds: int = 8) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "serverId": server.get("id"),
            "tools": [],
            "error": None,
            "stderrTail": "",
        }
        thread = threading.Thread(target=self._discover_in_thread, args=(server, timeout_seconds, result), daemon=True)
        thread.start()
        thread.join(timeout_seconds + 1)
        if thread.is_alive():
            result["error"] = f"MCP stdio tools/list 超时：{timeout_seconds}s。"
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
            "toolName": tool_name,
            "content": [],
            "structuredContent": None,
            "result": None,
            "error": None,
            "stderrTail": "",
        }
        thread = threading.Thread(
            target=self._call_in_thread,
            args=(server, tool_name, arguments or {}, timeout_seconds, result),
            daemon=True,
        )
        thread.start()
        thread.join(timeout_seconds + 1)
        if thread.is_alive():
            result["error"] = f"MCP stdio tools/call 超时：{timeout_seconds}s。"
        return result

    def _discover_in_thread(self, server: dict[str, Any], timeout_seconds: int, result: dict[str, Any]) -> None:
        proc: subprocess.Popen[bytes] | None = None
        timer: threading.Timer | None = None
        try:
            proc = self._start(server)
            timer = self._start_timer(proc, timeout_seconds)
            self._initialize(proc)
            self._send(proc, 2, "tools/list", {})
            tools_response = self._read_response(proc, expected_id=2)
            if tools_response.get("error"):
                raise RuntimeError(f"tools/list 被拒绝：{tools_response['error']}")

            tools = (tools_response.get("result") or {}).get("tools", [])
            result["ok"] = True
            result["tools"] = tools if isinstance(tools, list) else []
        except Exception as error:
            result["error"] = str(error)
        finally:
            self._cleanup(proc, timer, result)

    def _call_in_thread(
        self,
        server: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: int,
        result: dict[str, Any],
    ) -> None:
        proc: subprocess.Popen[bytes] | None = None
        timer: threading.Timer | None = None
        try:
            proc = self._start(server)
            timer = self._start_timer(proc, timeout_seconds)
            self._initialize(proc)
            self._send(proc, 2, "tools/call", {"name": tool_name, "arguments": arguments})
            call_response = self._read_response(proc, expected_id=2)
            if call_response.get("error"):
                raise RuntimeError(f"tools/call 被拒绝：{call_response['error']}")

            payload = call_response.get("result") or {}
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
        finally:
            self._cleanup(proc, timer, result)

    def _start(self, server: dict[str, Any]) -> subprocess.Popen[bytes]:
        command = str(server.get("command") or "").strip()
        args = [str(item) for item in server.get("args", []) if item is not None]
        env = os.environ.copy()
        env_config = server.get("env", {})
        if isinstance(env_config, dict):
            env.update({str(key): str(value) for key, value in env_config.items()})
        return subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    def _start_timer(self, proc: subprocess.Popen[bytes], timeout_seconds: int) -> threading.Timer:
        timer = threading.Timer(timeout_seconds, self._terminate, args=(proc,))
        timer.daemon = True
        timer.start()
        return timer

    def _initialize(self, proc: subprocess.Popen[bytes]) -> None:
        self._send(
            proc,
            1,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ai-delivery-workbench", "version": "0.1.0"},
            },
        )
        initialize = self._read_response(proc, expected_id=1)
        if initialize.get("error"):
            raise RuntimeError(f"initialize 被拒绝：{initialize['error']}")
        self._notify(proc, "notifications/initialized", {})

    def _send(self, proc: subprocess.Popen[bytes], request_id: int, method: str, params: dict[str, Any]) -> None:
        self._write(proc, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})

    def _notify(self, proc: subprocess.Popen[bytes], method: str, params: dict[str, Any]) -> None:
        self._write(proc, {"jsonrpc": "2.0", "method": method, "params": params})

    def _write(self, proc: subprocess.Popen[bytes], message: dict[str, Any]) -> None:
        if not proc.stdin:
            raise RuntimeError("MCP stdio stdin 不可用。")
        # MCP stdio 传输规范（2024-11-05）：每条消息是一行 JSON-RPC，以 \n 结尾。
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        proc.stdin.write(payload + b"\n")
        proc.stdin.flush()

    def _read_response(self, proc: subprocess.Popen[bytes], expected_id: int) -> dict[str, Any]:
        while True:
            message = self._read_message(proc)
            if message.get("id") == expected_id:
                return message

    def _read_message(self, proc: subprocess.Popen[bytes]) -> dict[str, Any]:
        if not proc.stdout:
            raise RuntimeError("MCP stdio stdout 不可用。")
        while True:
            line = proc.stdout.readline()
            if line == b"":
                raise RuntimeError("MCP stdio 连接已关闭。")
            stripped = line.strip()
            if not stripped:
                continue
            # 兼容旧版 LSP 风格帧（Content-Length 头 + 空行 + body），
            # 标准换行分隔 JSON 也走同一循环。
            if stripped.lower().startswith(b"content-length:"):
                length = int(stripped.split(b":", 1)[1].strip())
                while True:
                    header_line = proc.stdout.readline()
                    if header_line == b"" or not header_line.strip():
                        break
                payload = proc.stdout.read(length)
                return json.loads(payload.decode("utf-8"))
            try:
                return json.loads(stripped.decode("utf-8"))
            except json.JSONDecodeError:
                # 非 JSON 输出（server 误写日志到 stdout），跳过继续读。
                continue

    def _cleanup(
        self,
        proc: subprocess.Popen[bytes] | None,
        timer: threading.Timer | None,
        result: dict[str, Any],
    ) -> None:
        if timer:
            timer.cancel()
        if proc:
            result["stderrTail"] = self._stderr_tail(proc)
            self._terminate(proc)

    def _stderr_tail(self, proc: subprocess.Popen[bytes]) -> str:
        if not proc.stderr:
            return ""
        try:
            if proc.poll() is None:
                return ""
            return proc.stderr.read().decode("utf-8", errors="replace")[-4000:]
        except Exception:
            return ""

    def _terminate(self, proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    def _content_text(self, content: Any) -> str:
        if not isinstance(content, list):
            return ""
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(part for part in parts if part).strip()
