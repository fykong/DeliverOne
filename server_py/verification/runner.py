from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from server_py.core.json_io import now_iso, write_json
from server_py.core.paths import conversation_root
from server_py.core.proc import run_sandbox_command
from server_py.runtime.events import EventStore
from server_py.verification.stack_detector import StackDetector


class VerificationRunner:
    def __init__(self, events: EventStore, stack_detector: StackDetector) -> None:
        self.events = events
        self.stack_detector = stack_detector

    def run(
        self,
        conversation_id: str,
        sandbox: dict[str, Any],
        commands: dict[str, str] | None = None,
        timeout_seconds: int = 180,
    ) -> dict[str, Any]:
        repo_path = sandbox.get("repoPath")
        if not repo_path:
            raise RuntimeError("运行验证需要当前对话沙盒仓库。")

        repo = Path(repo_path).resolve()
        selected = self._normalize_commands(commands) or self.stack_detector.select_commands_for_path(str(repo))
        report_id = f"verify_{uuid4().hex[:10]}"
        generated_at = now_iso()
        self.events.append(
            conversation_id,
            "verification.run.begin",
            {"reportId": report_id, "commandCount": len(selected), "repoPath": str(repo)},
            actor="runtime",
        )

        results = [
            self._run_one(conversation_id, report_id, phase, command, repo, timeout_seconds)
            for phase, command in selected.items()
        ]
        ok = bool(results) and all(item["ok"] for item in results)
        report = {
            "id": report_id,
            "conversationId": conversation_id,
            "generatedAt": generated_at,
            "repoPath": str(repo),
            "status": "pass" if ok else ("skipped" if not results else "fail"),
            "summary": self._summary(results),
            "commands": selected,
            "results": results,
        }

        report_root = conversation_root(conversation_id) / "delivery"
        report_root.mkdir(parents=True, exist_ok=True)
        report_path = report_root / "verification-report.json"
        report["reportPath"] = str(report_path)
        write_json(report_path, report)

        self.events.append(
            conversation_id,
            "verification.run.end",
            {"reportId": report_id, "status": report["status"], "reportPath": str(report_path)},
            actor="runtime",
        )
        return report

    def _run_one(self, conversation_id: str, report_id: str, phase: str, command: str, repo: Path, timeout_seconds: int) -> dict[str, Any]:
        started_at = now_iso()
        started = time.perf_counter()
        timeout = max(1, min(int(timeout_seconds or 180), 600))
        self.events.append(
            conversation_id,
            "verification.command.begin",
            {"reportId": report_id, "phase": phase, "command": command},
            actor="runtime",
        )
        result = run_sandbox_command(command, str(repo), timeout)
        exit_code = result["exitCode"]
        stdout = result["stdout"][-12000:]
        stderr = result["stderr"][-12000:]
        timed_out = bool(result["timedOut"])

        duration_ms = int((time.perf_counter() - started) * 1000)
        ok = exit_code == 0 and not timed_out
        item = {
            "phase": phase,
            "command": command,
            "ok": ok,
            "exitCode": exit_code,
            "timedOut": timed_out,
            "durationMs": duration_ms,
            "startedAt": started_at,
            "finishedAt": now_iso(),
            "stdoutTail": stdout,
            "stderrTail": stderr,
            "summary": f"{phase} 验证通过。" if ok else f"{phase} 验证未通过。",
        }
        self.events.append(
            conversation_id,
            "verification.command.end",
            {"reportId": report_id, "phase": phase, "ok": ok, "exitCode": exit_code, "timedOut": timed_out, "durationMs": duration_ms},
            actor="runtime",
        )
        return item

    def _normalize_commands(self, commands: dict[str, str] | None) -> dict[str, str]:
        if not commands:
            return {}
        allowed = {"build", "typecheck", "lint", "tests"}
        normalized: dict[str, str] = {}
        for phase, command in commands.items():
            key = str(phase)
            value = str(command).strip()
            if key in allowed and value:
                normalized[key] = value
        return normalized

    def _summary(self, results: list[dict[str, Any]]) -> str:
        if not results:
            return "没有检测到可运行的验证命令。"
        passed = sum(1 for item in results if item["ok"])
        return f"验证完成：{passed}/{len(results)} 通过。"
