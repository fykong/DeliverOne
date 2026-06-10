from __future__ import annotations

import subprocess
import threading
from collections import deque
from os import name as os_name
from typing import Any
from uuid import uuid4

from server_py.core.json_io import now_iso
from server_py.runtime.events import EventStore


class ProcessRegistry:
    def __init__(self, events: EventStore) -> None:
        self._processes: dict[str, dict[str, Any]] = {}
        self._handles: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()
        self.events = events

    def start(self, conversation_id: str, sandbox_id: str, command: str, cwd: str, ports: list[int] | None = None) -> dict[str, Any]:
        if not command.strip():
            raise RuntimeError("预览命令不能为空。")
        process_id = f"proc_{uuid4().hex[:10]}"
        started = now_iso()
        record = {
            "id": process_id,
            "conversationId": conversation_id,
            "sandboxId": sandbox_id,
            "command": command,
            "cwd": cwd,
            "status": "starting",
            "startedAt": started,
            "updatedAt": started,
            "stdoutTail": "",
            "stderrTail": "",
            "ports": ports or [],
            "stopRequested": False,
        }
        with self._lock:
            self._processes[process_id] = record
        self.events.append(conversation_id, "preview.command.begin", {"processId": process_id, "command": command, "cwd": cwd, "ports": ports or []})

        proc = subprocess.Popen(
            command,
            cwd=cwd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        with self._lock:
            self._handles[process_id] = proc
            record["pid"] = proc.pid
            record["status"] = "running"
            record["updatedAt"] = now_iso()

        self._pump(process_id, proc, "stdout")
        self._pump(process_id, proc, "stderr")
        threading.Thread(target=self._watch_exit, args=(conversation_id, process_id, proc), daemon=True).start()
        return dict(record)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._processes.values()]

    def stop(self, process_id: str, conversation_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            record = self._processes.get(process_id)
            proc = self._handles.get(process_id)
            if not record:
                raise RuntimeError("预览进程不存在。")
            if conversation_id and record.get("conversationId") != conversation_id:
                raise RuntimeError("不能停止其他对话的预览进程。")
            if record.get("status") in {"exited", "failed", "stopped"}:
                return dict(record)
            record["stopRequested"] = True
            record["updatedAt"] = now_iso()

        if not proc:
            with self._lock:
                record["status"] = "stopped"
                record["updatedAt"] = now_iso()
                result = dict(record)
            return result

        self.events.append(record["conversationId"], "preview.command.stop.begin", {"processId": process_id, "pid": proc.pid})
        self._terminate_process_tree(proc)

        with self._lock:
            record["status"] = "stopped"
            record["exitCode"] = proc.poll()
            record["updatedAt"] = now_iso()
            result = dict(record)
        self.events.append(record["conversationId"], "preview.command.stop.end", {"processId": process_id, "status": "stopped", "exitCode": result.get("exitCode")})
        return result

    def _terminate_process_tree(self, proc: subprocess.Popen[str]) -> None:
        if proc.poll() is not None:
            return
        if os_name == "nt":
            taskkill = subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if taskkill.returncode == 0:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    def _pump(self, process_id: str, proc: subprocess.Popen[str], stream_name: str) -> None:
        stream = proc.stdout if stream_name == "stdout" else proc.stderr
        tail: deque[str] = deque(maxlen=80)

        def run() -> None:
            if not stream:
                return
            for line in stream:
                tail.append(line.rstrip())
                with self._lock:
                    record = self._processes.get(process_id)
                    if record:
                        record[f"{stream_name}Tail"] = "\n".join(tail)
                        record["updatedAt"] = now_iso()

        threading.Thread(target=run, daemon=True).start()

    def _watch_exit(self, conversation_id: str, process_id: str, proc: subprocess.Popen[str]) -> None:
        code = proc.wait()
        with self._lock:
            record = self._processes.get(process_id)
            self._handles.pop(process_id, None)
            if record:
                record["exitCode"] = code
                record["status"] = "stopped" if record.get("stopRequested") else ("exited" if code == 0 else "failed")
                record["updatedAt"] = now_iso()
                status = record["status"]
            else:
                status = "exited" if code == 0 else "failed"
        self.events.append(conversation_id, "preview.command.end", {"processId": process_id, "exitCode": code, "status": status})
