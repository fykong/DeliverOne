from __future__ import annotations

from pathlib import Path
from typing import Any

from server_py.core.proc import run_sandbox_command
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
    result = run_sandbox_command(command, str(cwd), timeout)
    ok = result["exitCode"] == 0 and not result["timedOut"]
    if result["timedOut"]:
        summary = f"命令超时（{timeout}s），已终止整棵进程树。watch/交互类命令请改为单次运行（如 vitest run）。"
    elif ok:
        summary = f"命令执行完成，退出码 {result['exitCode']}。"
    else:
        summary = f"命令执行失败，退出码 {result['exitCode']}。"
    return {
        "ok": ok,
        "summary": summary,
        "data": {
            "command": command,
            "cwd": str(cwd),
            "exitCode": result["exitCode"],
            "timedOut": result["timedOut"],
            "stdout": result["stdout"][-12000:],
            "stderr": result["stderr"][-12000:],
            "stdoutTail": result["stdout"][-4000:],
            "stderrTail": result["stderr"][-4000:],
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
