from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import conversation_root
from server_py.runtime.events import EventStore


class DeliveryService:
    def __init__(self, events: EventStore) -> None:
        self.events = events

    def package(
        self,
        conversation_id: str,
        state: dict[str, Any],
        tool_plan: dict[str, Any] | None,
        checkpoints: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        sandbox = state.get("sandbox")
        if not sandbox or not sandbox.get("repoPath"):
            raise RuntimeError("生成交付包需要当前对话沙盒。")

        repo = Path(sandbox["repoPath"]).resolve()
        delivery_root = conversation_root(conversation_id) / "delivery"
        delivery_root.mkdir(parents=True, exist_ok=True)

        status = self._git(repo, ["status", "--short"])
        diff_stat = self._git(repo, ["diff", "--stat"])
        patch = self._git(repo, ["diff", "--binary"])
        changed_files = self._changed_files(repo)
        verification_gate = self._verification_gate(conversation_id, tool_plan)
        preview_gate = self._preview_gate(conversation_id, tool_plan)
        rollback_gate = self._rollback_gate(conversation_id, checkpoints)

        patch_path = delivery_root / "changes.patch"
        json_path = delivery_root / "delivery-report.json"
        md_path = delivery_root / "delivery-report.md"
        patch_path.write_text(patch, encoding="utf-8")

        report = {
            "id": f"delivery_{conversation_id}",
            "conversationId": conversation_id,
            "generatedAt": now_iso(),
            "repository": state.get("repository"),
            "sandbox": sandbox,
            "toolPlan": self._plan_summary(tool_plan),
            "changedFiles": changed_files,
            "statusShort": status,
            "diffStat": diff_stat,
            "verificationGate": verification_gate,
            "previewGate": preview_gate,
            "rollbackGate": rollback_gate,
            "checkpointCount": len(checkpoints),
            "checkpoints": [
                {"id": item.get("id"), "label": item.get("label"), "createdAt": item.get("createdAt")}
                for item in checkpoints
            ],
            "eventTail": [
                {"type": item.get("type"), "actor": item.get("actor"), "createdAt": item.get("createdAt")}
                for item in events[-30:]
            ],
            "artifacts": {
                "patchPath": str(patch_path),
                "jsonPath": str(json_path),
                "markdownPath": str(md_path),
            },
            "notes": [
                "changes.patch 包含已跟踪文件 diff；未跟踪文件会列在 changedFiles 中。",
                self._verification_note(verification_gate),
                self._preview_note(preview_gate),
                self._rollback_note(rollback_gate),
                "应用回原仓库需要用户显式确认，并且第一版仅支持本地路径仓库。",
            ],
        }
        write_json(json_path, report)
        md_path.write_text(self._markdown(report), encoding="utf-8")
        self.events.append(
            conversation_id,
            "delivery.package.generated",
            {"changedFileCount": len(changed_files), "markdownPath": str(md_path), "patchPath": str(patch_path)},
            actor="runtime",
        )
        return report

    def preview(self, conversation_id: str, max_bytes: int = 120000) -> dict[str, Any]:
        delivery_root = conversation_root(conversation_id) / "delivery"
        json_path = delivery_root / "delivery-report.json"
        report = read_json(json_path, None)
        if not isinstance(report, dict):
            return {
                "conversationId": conversation_id,
                "exists": False,
                "summary": "尚未生成交付包。",
                "report": None,
                "markdown": None,
                "patch": None,
            }

        artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), dict) else {}
        markdown_path = self._safe_artifact_path(delivery_root, artifacts.get("markdownPath"))
        patch_path = self._safe_artifact_path(delivery_root, artifacts.get("patchPath"))
        markdown = self._read_preview_file(markdown_path, max_bytes)
        patch = self._read_preview_file(patch_path, max_bytes)
        return {
            "conversationId": conversation_id,
            "exists": True,
            "summary": f"交付包已生成，包含 {len(report.get('changedFiles', []))} 个变更文件。",
            "report": report,
            "markdown": markdown,
            "patch": patch,
            "generatedAt": report.get("generatedAt"),
        }

    def apply_to_source(self, conversation_id: str, state: dict[str, Any], confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            raise RuntimeError("应用回原仓库会修改用户本地文件，必须显式确认。")
        repository = state.get("repository")
        sandbox = state.get("sandbox")
        if not repository or repository.get("sourceType") != "local":
            raise RuntimeError("第一版只支持把沙盒改动应用回本地路径仓库。")
        if not sandbox or not sandbox.get("repoPath"):
            raise RuntimeError("缺少当前对话沙盒。")

        source_root = Path(str(repository.get("source"))).resolve()
        sandbox_root = Path(sandbox["repoPath"]).resolve()
        if not source_root.exists() or not source_root.is_dir():
            raise RuntimeError("原始本地仓库路径不存在。")

        changed_files = self._changed_files(sandbox_root)
        backup_root = conversation_root(conversation_id) / "delivery" / f"source-backup-{now_iso().replace(':', '-')}"
        applied: list[dict[str, str]] = []

        self.events.append(conversation_id, "delivery.apply_source.begin", {"fileCount": len(changed_files), "source": str(source_root)}, actor="runtime")
        for item in changed_files:
            relative_path = item["path"]
            source_target = self._resolve_inside(source_root, relative_path)
            sandbox_target = self._resolve_inside(sandbox_root, relative_path)
            backup_target = backup_root / relative_path

            if source_target.exists() and source_target.is_file():
                backup_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_target, backup_target)

            if item["action"] == "delete":
                if source_target.exists() and source_target.is_file():
                    source_target.unlink()
                applied.append({"path": relative_path, "action": "delete"})
                continue

            if not sandbox_target.exists() or not sandbox_target.is_file():
                continue
            source_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sandbox_target, source_target)
            applied.append({"path": relative_path, "action": "copy"})

        result = {
            "ok": True,
            "summary": f"已将 {len(applied)} 个沙盒文件变更应用回本地原仓库。",
            "applied": applied,
            "backupPath": str(backup_root),
        }
        self.events.append(conversation_id, "delivery.apply_source.end", result, actor="runtime")
        return result

    def _changed_files(self, repo: Path) -> list[dict[str, str]]:
        status = self._git_raw(repo, ["status", "--porcelain"])
        files: list[dict[str, str]] = []
        seen: set[str] = set()
        for line in status.splitlines():
            if len(line) < 4:
                continue
            code = line[:2]
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1].strip()
            action = "delete" if "D" in code else "copy"
            if path and path not in seen:
                files.append({"path": path.replace("\\", "/"), "status": code.strip() or "modified", "action": action})
                seen.add(path)
        return files

    def _plan_summary(self, plan: dict[str, Any] | None) -> dict[str, Any] | None:
        if not plan:
            return None
        return {
            "id": plan.get("id"),
            "status": plan.get("status"),
            "stepCount": len(plan.get("steps", [])),
            "generation": plan.get("generation"),
            "evidence": plan.get("evidence"),
        }

    def _verification_gate(self, conversation_id: str, plan: dict[str, Any] | None) -> dict[str, Any]:
        report_path = conversation_root(conversation_id) / "delivery" / "verification-report.json"
        report = read_json(report_path, None)
        if isinstance(report, dict):
            return {
                "status": report.get("status") or "unknown",
                "source": "verification-report",
                "summary": report.get("summary") or "",
                "reportPath": report.get("reportPath") or str(report_path),
                "generatedAt": report.get("generatedAt"),
                "commandCount": len(report.get("results", [])) if isinstance(report.get("results"), list) else 0,
            }

        evidence = (plan or {}).get("evidence") if isinstance((plan or {}).get("evidence"), dict) else {}
        verification_results = evidence.get("verificationResults") if isinstance(evidence, dict) else []
        if isinstance(verification_results, list) and verification_results:
            passed = sum(1 for item in verification_results if isinstance(item, dict) and item.get("ok"))
            total = len(verification_results)
            status = "pass" if passed == total else "fail"
            return {
                "status": status,
                "source": "tool-plan",
                "summary": f"工具计划验证命令：{passed}/{total} 通过。",
                "reportPath": None,
                "generatedAt": (plan or {}).get("updatedAt"),
                "commandCount": total,
            }

        return {
            "status": "missing",
            "source": "none",
            "summary": "还没有绑定验证结果；交付包只能作为审查草稿。",
            "reportPath": None,
            "generatedAt": None,
            "commandCount": 0,
        }

    def _preview_gate(self, conversation_id: str, plan: dict[str, Any] | None) -> dict[str, Any]:
        report_path = conversation_root(conversation_id) / "preview" / "smoke-report.json"
        report = read_json(report_path, None)
        if isinstance(report, dict):
            screenshot = report.get("screenshot") if isinstance(report.get("screenshot"), dict) else {}
            runtime_dom = report.get("runtimeDom") if isinstance(report.get("runtimeDom"), dict) else {}
            browser_console = report.get("browserConsole") if isinstance(report.get("browserConsole"), dict) else {}
            return {
                "status": "pass" if report.get("ok") else "fail",
                "source": "preview-smoke-report",
                "summary": report.get("summary") or "",
                "reportPath": report.get("reportPath") or str(report_path),
                "screenshotPath": screenshot.get("path"),
                "screenshotOk": bool(screenshot.get("ok")),
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
                "quality": report.get("quality") if isinstance(report.get("quality"), dict) else None,
                "generatedAt": report.get("generatedAt"),
            }

        evidence = (plan or {}).get("evidence") if isinstance((plan or {}).get("evidence"), dict) else {}
        preview_results = evidence.get("previewResults") if isinstance(evidence, dict) else []
        if isinstance(preview_results, list) and preview_results:
            passed = sum(1 for item in preview_results if isinstance(item, dict) and item.get("ok"))
            total = len(preview_results)
            latest = next((item for item in reversed(preview_results) if isinstance(item, dict)), {})
            return {
                "status": "pass" if passed == total else "fail",
                "source": "tool-plan",
                "summary": f"工具计划预览 smoke：{passed}/{total} 通过。",
                "reportPath": latest.get("reportPath"),
                "screenshotPath": latest.get("screenshotPath"),
                "screenshotOk": bool(latest.get("screenshotOk")),
                "htmlTitle": latest.get("htmlTitle"),
                "htmlBytes": latest.get("htmlBytes") or 0,
                "runtimeDomPath": latest.get("runtimeDomPath"),
                "runtimeDomOk": bool(latest.get("runtimeDomOk")),
                "runtimeDomBytes": latest.get("runtimeDomBytes") or 0,
                "runtimeDomVisibleTextLength": latest.get("runtimeDomVisibleTextLength") or 0,
                "consoleErrorCount": latest.get("consoleErrorCount") or 0,
                "consoleReliable": bool(latest.get("consoleReliable")),
                "consoleErrors": latest.get("consoleErrors") if isinstance(latest.get("consoleErrors"), list) else [],
                "assertions": latest.get("assertions") if isinstance(latest.get("assertions"), dict) else None,
                "quality": latest.get("quality") if isinstance(latest.get("quality"), dict) else None,
                "generatedAt": (plan or {}).get("updatedAt"),
            }

        return {
            "status": "missing",
            "source": "none",
            "summary": "还没有绑定预览 smoke 证据；前端页面交付需要补充浏览器验证。",
            "reportPath": None,
            "screenshotPath": None,
            "screenshotOk": False,
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
            "quality": None,
            "generatedAt": None,
        }

    def _rollback_gate(self, conversation_id: str, checkpoints: list[dict[str, Any]]) -> dict[str, Any]:
        root = conversation_root(conversation_id) / "rollback"
        latest_report = None
        if root.exists():
            reports = [read_json(path, None) for path in root.glob("rollback_*.json")]
            reports = [item for item in reports if isinstance(item, dict)]
            if reports:
                latest_report = sorted(reports, key=lambda item: item.get("createdAt", ""))[-1]

        if isinstance(latest_report, dict):
            before = latest_report.get("before") if isinstance(latest_report.get("before"), dict) else {}
            after = latest_report.get("after") if isinstance(latest_report.get("after"), dict) else {}
            return {
                "status": "used",
                "source": "rollback-report",
                "summary": latest_report.get("summary") or "最近一次回退已记录。",
                "checkpointCount": len(checkpoints),
                "rollbackAvailable": bool(checkpoints),
                "latest": {
                    "id": latest_report.get("id"),
                    "operation": latest_report.get("operation"),
                    "affectedFiles": latest_report.get("affectedFiles", []),
                    "beforeFileCount": before.get("fileCount", 0),
                    "afterFileCount": after.get("fileCount", 0),
                    "confirmation": latest_report.get("confirmation") if isinstance(latest_report.get("confirmation"), dict) else None,
                    "reportPath": latest_report.get("reportPath"),
                    "createdAt": latest_report.get("createdAt"),
                },
            }

        return {
            "status": "ready" if checkpoints else "missing",
            "source": "checkpoints" if checkpoints else "none",
            "summary": f"已有 {len(checkpoints)} 个 checkpoint，可按检查点回退。" if checkpoints else "还没有 checkpoint；写入前需要先创建回退点。",
            "checkpointCount": len(checkpoints),
            "rollbackAvailable": bool(checkpoints),
            "latest": None,
        }

    def _verification_note(self, gate: dict[str, Any]) -> str:
        status = gate.get("status")
        if status == "pass":
            return f"验证门禁通过：{gate.get('summary')}"
        if status == "fail":
            return f"验证门禁未通过：{gate.get('summary')}"
        if status == "skipped":
            return f"验证门禁跳过：{gate.get('summary')}"
        return "验证门禁缺失：请先运行验证或在工具计划中保留验证命令。"

    def _preview_note(self, gate: dict[str, Any]) -> str:
        status = gate.get("status")
        if status == "pass":
            return f"预览门禁通过：{gate.get('summary')}"
        if status == "fail":
            return f"预览门禁未通过：{gate.get('summary')}"
        return "预览门禁缺失：前端或页面类交付建议先运行浏览器 smoke test。"

    def _rollback_note(self, gate: dict[str, Any]) -> str:
        if gate.get("status") == "used":
            latest = gate.get("latest") if isinstance(gate.get("latest"), dict) else {}
            return f"回退证据已记录：{gate.get('summary')}（{latest.get('beforeFileCount', 0)} -> {latest.get('afterFileCount', 0)} 个变更）。"
        if gate.get("rollbackAvailable"):
            return f"回退门禁就绪：{gate.get('summary')}"
        return "回退门禁缺失：当前没有 checkpoint，写入类交付不可直接上线。"

    def _markdown(self, report: dict[str, Any]) -> str:
        changed_files = report["changedFiles"]
        verification = report.get("verificationGate") or {}
        lines = [
            "# 交付报告",
            "",
            f"- 对话：`{report['conversationId']}`",
            f"- 生成时间：`{report['generatedAt']}`",
            f"- 变更文件数：{len(changed_files)}",
            f"- Checkpoint 数：{report['checkpointCount']}",
            f"- 验证门禁：{verification.get('status', 'missing')}（{verification.get('source', 'none')}）",
            f"- 验证摘要：{verification.get('summary', '')}",
            f"- 预览门禁：{(report.get('previewGate') or {}).get('status', 'missing')}（{(report.get('previewGate') or {}).get('source', 'none')}）",
            f"- 预览摘要：{(report.get('previewGate') or {}).get('summary', '')}",
            f"- 浏览器错误：{(report.get('previewGate') or {}).get('consoleErrorCount', 0)}",
            f"- 运行后 DOM：{(report.get('previewGate') or {}).get('runtimeDomBytes', 0)} bytes",
            f"- 验收断言：{((report.get('previewGate') or {}).get('assertions') or {}).get('summary', '未配置')}",
            f"- 回退门禁：{(report.get('rollbackGate') or {}).get('status', 'missing')}（{(report.get('rollbackGate') or {}).get('source', 'none')}）",
            f"- 回退摘要：{(report.get('rollbackGate') or {}).get('summary', '')}",
            "",
            "## 变更文件",
            "",
        ]
        lines.extend(f"- `{item['path']}`：{item['status']}" for item in changed_files)
        if not changed_files:
            lines.append("- 暂无文件变更。")
        lines.extend(["", "## Diff Stat", "", "```text", report["diffStat"] or "无", "```", "", "## 回退", "", "可通过 checkpoint 回退，也可以确认后将沙盒回到原始 HEAD。"])
        return "\n".join(lines) + "\n"

    def _git(self, repo: Path, args: list[str]) -> str:
        return self._git_raw(repo, args).strip()

    def _git_raw(self, repo: Path, args: list[str]) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        return result.stdout or result.stderr

    def _resolve_inside(self, root: Path, relative_path: str) -> Path:
        target = (root / relative_path).resolve()
        if target != root and root not in target.parents:
            raise RuntimeError("目标路径超出仓库范围。")
        return target

    def _safe_artifact_path(self, delivery_root: Path, raw_path: Any) -> Path | None:
        if not raw_path:
            return None
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = delivery_root / path
        resolved = path.resolve()
        root = delivery_root.resolve()
        if resolved != root and root not in resolved.parents:
            raise RuntimeError("交付产物路径超出当前对话目录，拒绝读取。")
        return resolved

    def _read_preview_file(self, path: Path | None, max_bytes: int) -> dict[str, Any] | None:
        if not path or not path.exists() or not path.is_file():
            return None
        limit = max(1000, min(int(max_bytes or 120000), 500000))
        raw = path.read_bytes()
        content = raw[:limit].decode("utf-8", errors="replace")
        return {
            "path": str(path),
            "content": content,
            "bytes": len(raw),
            "truncated": len(raw) > limit,
        }
