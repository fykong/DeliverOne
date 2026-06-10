from __future__ import annotations

from typing import Any

from server_py.tools.types import AgentTool, ToolContext
from server_py.verification.runner import VerificationRunner


def _verification_run_factory(runner: VerificationRunner):
    def run(payload: Any, context: ToolContext) -> dict[str, Any]:
        record = payload if isinstance(payload, dict) else {}
        if not context.repo_path:
            raise RuntimeError("当前对话还没有沙盒仓库。")
        report = runner.run(
            conversation_id=context.conversation_id,
            sandbox={"id": context.sandbox_id, "repoPath": context.repo_path},
            commands=record.get("commands") if isinstance(record.get("commands"), dict) else None,
            timeout_seconds=int(record.get("timeoutSeconds", 180) or 180),
        )
        return {
            "ok": report["status"] == "pass",
            "summary": report["summary"],
            "data": report,
        }

    return run


def create_verification_tools(runner: VerificationRunner) -> list[AgentTool]:
    return [
        AgentTool(
            "verification.run",
            "运行验证",
            "在当前对话沙盒中运行栈相关的 build/typecheck/lint/test 命令，并生成结构化验证报告。",
            "command",
            _verification_run_factory(runner),
            input_schema={"commands": "object", "timeoutSeconds": "number", "approved": "boolean"},
            managed_command=True,
        )
    ]
