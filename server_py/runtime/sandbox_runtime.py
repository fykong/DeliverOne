from __future__ import annotations

from typing import Any

from server_py.core.json_io import now_iso, read_json
from server_py.core.paths import conversation_root
from server_py.verification.stack_detector import StackDetector


class SandboxRuntimeService:
    """Conversation-scoped sandbox lifecycle snapshot.

    This keeps the UI from inferring runtime state by stitching together many
    panels. It mirrors the Codex-style idea that a task has one sandbox surface:
    files, commands, preview, validation, delivery, and rollback evidence.
    """

    def __init__(self, stack_detector: StackDetector | None = None) -> None:
        self.stack_detector = stack_detector or StackDetector()

    def build(
        self,
        state: dict[str, Any],
        processes: list[dict[str, Any]],
        checkpoints: list[dict[str, Any]],
        events: list[dict[str, Any]],
        diff: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conversation_id = str(state.get("conversationId") or "")
        repository = state.get("repository") if isinstance(state.get("repository"), dict) else None
        sandbox = state.get("sandbox") if isinstance(state.get("sandbox"), dict) else None
        preview = self._preview(conversation_id, processes, events)
        verification = self._verification(conversation_id)
        command_recommendations = self._command_recommendations(sandbox)
        delivery = self._delivery(conversation_id, events)
        rollback = self._rollback(conversation_id, events)
        file_summary = self._files(files, diff)
        lifecycle = self._lifecycle(repository, sandbox, processes, preview, verification, file_summary, checkpoints, delivery, rollback)

        return {
            "conversationId": conversation_id,
            "status": self._status(lifecycle),
            "repository": self._repository(repository),
            "sandbox": self._sandbox(sandbox),
            "lifecycle": lifecycle,
            "processes": self._processes(processes),
            "preview": preview,
            "verification": verification,
            "commandRecommendations": command_recommendations,
            "files": file_summary,
            "checkpoints": {
                "count": len(checkpoints),
                "latest": self._checkpoint_summary(checkpoints[0]) if checkpoints else None,
            },
            "delivery": delivery,
            "rollback": rollback,
            "updatedAt": now_iso(),
        }

    def _command_recommendations(self, sandbox: dict[str, Any] | None) -> dict[str, Any]:
        if not sandbox or not sandbox.get("repoPath"):
            return {
                "verification": {"primary": None, "all": [], "commands": {}},
                "preview": {"primary": None, "all": []},
                "source": {"packageJson": None, "pyproject": None, "generatedAt": now_iso()},
            }
        try:
            return self.stack_detector.recommend_for_path(str(sandbox["repoPath"]))
        except Exception as error:
            return {
                "verification": {"primary": None, "all": [], "commands": {}},
                "preview": {"primary": None, "all": []},
                "source": {"packageJson": None, "pyproject": None, "generatedAt": now_iso(), "error": str(error)},
            }

    def _lifecycle(
        self,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        processes: list[dict[str, Any]],
        preview: dict[str, Any],
        verification: dict[str, Any],
        files: dict[str, Any],
        checkpoints: list[dict[str, Any]],
        delivery: dict[str, Any],
        rollback: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            self._stage("repository", "仓库", "done" if repository else "blocked", "已接入仓库。" if repository else "还没有接入仓库。", {"dirtyFiles": int((repository or {}).get("dirtyFileCount") or 0)}),
            self._stage("sandbox", "沙盒", "done" if sandbox else "blocked", "当前对话有独立沙盒。" if sandbox else "每个对话必须先创建沙盒。", {"repoPath": 1 if sandbox else 0}),
            self._stage("files", "文件", "done" if files["treeItems"] else ("pending" if sandbox else "blocked"), "文件树和 diff 已加载。" if files["treeItems"] else "等待读取沙盒文件树。", {"tree": files["treeItems"], "changed": files["changedFiles"]}),
            self._stage("process", "进程", "current" if any(item.get("status") in {"starting", "running"} for item in processes) else ("done" if processes else "pending"), "预览进程正在运行。" if any(item.get("status") in {"starting", "running"} for item in processes) else "尚未启动沙盒预览进程。", {"running": self._processes(processes)["running"], "total": len(processes)}),
            self._stage(
                "preview",
                "预览",
                self._preview_stage_status(preview),
                preview["summary"],
                {
                    "screenshots": 1 if preview.get("screenshotPath") else 0,
                    "htmlBytes": int(preview.get("htmlBytes") or 0),
                    "runtimeDomBytes": int(preview.get("runtimeDomBytes") or 0),
                    "consoleErrors": int(preview.get("consoleErrorCount") or 0),
                    "assertions": 1 if isinstance(preview.get("assertions"), dict) and preview["assertions"].get("enabled") else 0,
                },
            ),
            self._stage("verification", "验证", self._verification_stage_status(verification), verification["summary"], {"commands": int(verification.get("commandCount") or 0)}),
            self._stage("checkpoint", "检查点", "done" if checkpoints else "pending", "已有写入前检查点。" if checkpoints else "写入前会自动创建检查点。", {"count": len(checkpoints)}),
            self._stage("delivery", "交付", "done" if delivery["status"] == "generated" else "pending", delivery["summary"], {"packages": 1 if delivery["status"] == "generated" else 0}),
            self._stage(
                "rollback",
                "回退",
                "done" if rollback["eventCount"] else ("current" if checkpoints else "pending"),
                rollback["summary"],
                {"events": rollback["eventCount"], "reports": 1 if rollback.get("report") else 0},
            ),
        ]

    def _stage(self, stage_id: str, title: str, status: str, summary: str, evidence: dict[str, int]) -> dict[str, Any]:
        return {"id": stage_id, "title": title, "status": status, "summary": summary, "evidence": evidence}

    def _repository(self, repository: dict[str, Any] | None) -> dict[str, Any] | None:
        if not repository:
            return None
        return {
            "sourceType": repository.get("sourceType"),
            "source": repository.get("source"),
            "branch": repository.get("branch"),
            "head": repository.get("head"),
            "packageManager": repository.get("packageManager"),
            "scriptCount": len(repository.get("scripts", {}) if isinstance(repository.get("scripts"), dict) else {}),
        }

    def _sandbox(self, sandbox: dict[str, Any] | None) -> dict[str, Any] | None:
        if not sandbox:
            return None
        return {
            "id": sandbox.get("id"),
            "rootPath": sandbox.get("rootPath"),
            "repoPath": sandbox.get("repoPath"),
            "createdAt": sandbox.get("createdAt"),
        }

    def _files(self, files: dict[str, Any] | None, diff: dict[str, Any] | None) -> dict[str, Any]:
        items = files.get("items", []) if isinstance(files, dict) and isinstance(files.get("items"), list) else []
        return {
            "treeItems": len(items),
            "textFiles": sum(1 for item in items if isinstance(item, dict) and item.get("type") == "file" and item.get("isText")),
            "changedFiles": int((diff or {}).get("fileCount") or 0),
            "truncated": bool((files or {}).get("truncated")),
        }

    def _processes(self, processes: list[dict[str, Any]]) -> dict[str, Any]:
        running = [item for item in processes if item.get("status") in {"starting", "running"}]
        failed = [item for item in processes if item.get("status") == "failed"]
        ports: list[int] = []
        for item in processes:
            item_ports = item.get("ports") if isinstance(item.get("ports"), list) else []
            ports.extend(int(port) for port in item_ports if isinstance(port, int))
        return {
            "total": len(processes),
            "running": len(running),
            "failed": len(failed),
            "ports": sorted(set(ports)),
            "latest": self._process_summary(processes[-1]) if processes else None,
        }

    def _process_summary(self, process: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": process.get("id"),
            "status": process.get("status"),
            "command": process.get("command"),
            "ports": process.get("ports", []),
            "updatedAt": process.get("updatedAt"),
        }

    def _preview(self, conversation_id: str, processes: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
        report_path = conversation_root(conversation_id) / "preview" / "smoke-report.json"
        report = read_json(report_path, None)
        running = any(item.get("status") in {"starting", "running"} for item in processes)
        if isinstance(report, dict):
            ok = bool(report.get("ok"))
            screenshot = report.get("screenshot") if isinstance(report.get("screenshot"), dict) else {}
            runtime_dom = report.get("runtimeDom") if isinstance(report.get("runtimeDom"), dict) else {}
            browser_console = report.get("browserConsole") if isinstance(report.get("browserConsole"), dict) else {}
            return {
                "status": "pass" if ok else "fail",
                "summary": report.get("summary") or ("预览验证通过。" if ok else "预览验证失败。"),
                "url": report.get("url"),
                "reportPath": report.get("reportPath") or str(report_path),
                "htmlPath": report.get("htmlPath"),
                "htmlTitle": report.get("htmlTitle"),
                "htmlBytes": report.get("htmlBytes") or 0,
                "runtimeDomPath": runtime_dom.get("path"),
                "runtimeDomOk": bool(runtime_dom.get("ok")),
                "runtimeDomBytes": runtime_dom.get("bytes") or 0,
                "runtimeDomVisibleTextLength": runtime_dom.get("visibleTextLength") or 0,
                "consoleErrorCount": browser_console.get("errorCount") or 0,
                "consoleReliable": bool(browser_console.get("reliable")),
                "consoleErrors": browser_console.get("errors") if isinstance(browser_console.get("errors"), list) else [],
                "assertions": report.get("assertions") if isinstance(report.get("assertions"), dict) else None,
                "screenshotPath": screenshot.get("path"),
                "screenshotOk": bool(screenshot.get("ok")),
                "quality": report.get("quality") if isinstance(report.get("quality"), dict) else None,
                "generatedAt": report.get("generatedAt"),
            }
        if running:
            return {
                "status": "running",
                "summary": "预览进程已启动，尚未运行 smoke test。",
                "url": self._preview_url(processes),
                "reportPath": None,
                "htmlPath": None,
                "htmlTitle": None,
                "htmlBytes": 0,
                "runtimeDomPath": None,
                "runtimeDomOk": False,
                "runtimeDomBytes": 0,
                "runtimeDomVisibleTextLength": 0,
                "consoleErrorCount": 0,
                "consoleReliable": False,
                "consoleErrors": [],
                "assertions": None,
                "screenshotPath": None,
                "screenshotOk": False,
                "generatedAt": None,
            }
        if any(item.get("type") == "preview.command.end" for item in events):
            return {
                "status": "stopped",
                "summary": "预览进程已结束，尚未产生 smoke test 报告。",
                "url": None,
                "reportPath": None,
                "htmlPath": None,
                "htmlTitle": None,
                "htmlBytes": 0,
                "runtimeDomPath": None,
                "runtimeDomOk": False,
                "runtimeDomBytes": 0,
                "runtimeDomVisibleTextLength": 0,
                "consoleErrorCount": 0,
                "consoleReliable": False,
                "consoleErrors": [],
                "assertions": None,
                "screenshotPath": None,
                "screenshotOk": False,
                "generatedAt": None,
            }
        return {
            "status": "not_started",
            "summary": "还没有启动沙盒预览。",
            "url": None,
            "reportPath": None,
            "htmlPath": None,
            "htmlTitle": None,
            "htmlBytes": 0,
            "runtimeDomPath": None,
            "runtimeDomOk": False,
            "runtimeDomBytes": 0,
            "runtimeDomVisibleTextLength": 0,
            "consoleErrorCount": 0,
            "consoleReliable": False,
            "consoleErrors": [],
            "assertions": None,
            "screenshotPath": None,
            "screenshotOk": False,
            "generatedAt": None,
        }

    def _preview_url(self, processes: list[dict[str, Any]]) -> str | None:
        for item in reversed(processes):
            ports = item.get("ports") if isinstance(item.get("ports"), list) else []
            if item.get("status") in {"starting", "running"} and ports:
                return f"http://127.0.0.1:{ports[0]}"
        return None

    def _verification(self, conversation_id: str) -> dict[str, Any]:
        report_path = conversation_root(conversation_id) / "delivery" / "verification-report.json"
        report = read_json(report_path, None)
        if not isinstance(report, dict):
            return {
                "status": "missing",
                "summary": "还没有运行验证命令。",
                "reportPath": None,
                "generatedAt": None,
                "commandCount": 0,
            }
        return {
            "status": report.get("status") or "unknown",
            "summary": report.get("summary") or "",
            "reportPath": report.get("reportPath") or str(report_path),
            "generatedAt": report.get("generatedAt"),
            "commandCount": len(report.get("results", [])) if isinstance(report.get("results"), list) else 0,
        }

    def _delivery(self, conversation_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        report_path = conversation_root(conversation_id) / "delivery" / "delivery-report.json"
        report = read_json(report_path, None)
        if isinstance(report, dict):
            return {
                "status": "generated",
                "summary": f"交付包已生成，包含 {len(report.get('changedFiles', []))} 个变更文件。",
                "reportPath": report.get("artifacts", {}).get("markdownPath") if isinstance(report.get("artifacts"), dict) else str(report_path),
                "generatedAt": report.get("generatedAt"),
            }
        if any(item.get("type") == "delivery.apply_source.end" for item in events):
            return {"status": "applied", "summary": "沙盒改动已应用到原仓库。", "reportPath": None, "generatedAt": None}
        return {"status": "missing", "summary": "尚未生成交付包。", "reportPath": None, "generatedAt": None}

    def _rollback(self, conversation_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        rollback_events = [item for item in events if str(item.get("type", "")).startswith("rollback.")]
        latest = rollback_events[-1] if rollback_events else None
        latest_report = self._latest_rollback_report_for_conversation(conversation_id)
        return {
            "eventCount": len(rollback_events),
            "summary": latest_report.get("summary") if latest_report else ("已发生回退操作。" if rollback_events else "尚未执行回退；有 checkpoint 后可随时回退。"),
            "latest": {
                "type": latest.get("type"),
                "createdAt": latest.get("createdAt"),
                "payload": latest.get("payload"),
            }
            if isinstance(latest, dict)
            else None,
            "report": latest_report,
        }

    def _latest_rollback_report_for_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        root = conversation_root(conversation_id) / "rollback"
        if not root.exists():
            return None
        reports = [read_json(path, None) for path in root.glob("rollback_*.json")]
        reports = [item for item in reports if isinstance(item, dict)]
        if not reports:
            return None
        latest = sorted(reports, key=lambda item: item.get("createdAt", ""))[-1]
        return {
            "id": latest.get("id"),
            "operation": latest.get("operation"),
            "summary": latest.get("summary"),
            "affectedFiles": latest.get("affectedFiles", []),
            "beforeFileCount": (latest.get("before") or {}).get("fileCount") if isinstance(latest.get("before"), dict) else None,
            "afterFileCount": (latest.get("after") or {}).get("fileCount") if isinstance(latest.get("after"), dict) else None,
            "confirmation": latest.get("confirmation") if isinstance(latest.get("confirmation"), dict) else None,
            "reportPath": latest.get("reportPath"),
            "createdAt": latest.get("createdAt"),
        }

    def _checkpoint_summary(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": checkpoint.get("id"),
            "label": checkpoint.get("label"),
            "fileCount": len(checkpoint.get("files", [])) if isinstance(checkpoint.get("files"), list) else 0,
            "createdAt": checkpoint.get("createdAt"),
        }

    def _preview_stage_status(self, preview: dict[str, Any]) -> str:
        if preview["status"] == "pass":
            return "done"
        if preview["status"] == "fail":
            return "blocked"
        if preview["status"] == "running":
            return "current"
        return "pending"

    def _verification_stage_status(self, verification: dict[str, Any]) -> str:
        if verification["status"] == "pass":
            return "done"
        if verification["status"] == "fail":
            return "blocked"
        if verification["status"] == "missing":
            return "pending"
        return "current"

    def _status(self, lifecycle: list[dict[str, Any]]) -> str:
        if any(item["status"] == "blocked" for item in lifecycle):
            return "blocked"
        if any(item["status"] == "current" for item in lifecycle):
            return "running"
        if all(item["status"] in {"done", "pending"} for item in lifecycle):
            return "ready"
        return "unknown"
