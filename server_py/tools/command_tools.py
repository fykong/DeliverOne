from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from server_py.tools.types import AgentTool, ToolContext


def _run_command(payload: Any, context: ToolContext) -> dict[str, Any]:
    record = payload if isinstance(payload, dict) else {}
    command = str(record.get("command", "")).strip()
    if not command:
        raise RuntimeError("缺少 command。")
    if not context.repo_path:
        raise RuntimeError("当前对话还没有沙盒仓库。")

    timeout = min(int(record.get("timeoutSeconds", 60) or 60), 600)
    cwd = Path(context.repo_path).resolve()
    result = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    ok = result.returncode == 0
    return {
        "ok": ok,
        "summary": f"命令执行完成，退出码 {result.returncode}。" if ok else f"命令执行失败，退出码 {result.returncode}。",
        "data": {
            "command": command,
            "cwd": str(cwd),
            "exitCode": result.returncode,
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:],
            "stdoutTail": result.stdout[-4000:],
            "stderrTail": result.stderr[-4000:],
        },
    }


def create_command_tools() -> list[AgentTool]:
    return [
        AgentTool(
            "command.run",
            "运行命令",
            "在当前对话沙盒仓库内运行受控命令；非可信命令需要用户确认。",
            "command",
            _run_command,
            input_schema={"command": "string", "timeoutSeconds": "number", "approved": "boolean"},
        )
    ]
