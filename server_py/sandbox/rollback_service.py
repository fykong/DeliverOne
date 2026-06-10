from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import conversation_root
from server_py.runtime.events import EventStore
from server_py.sandbox.checkpoint_manager import CheckpointManager


class RollbackService:
    def __init__(self, checkpoints: CheckpointManager, events: EventStore) -> None:
        self.checkpoints = checkpoints
        self.events = events

    def list_reports(self, conversation_id: str) -> list[dict[str, Any]]:
        root = conversation_root(conversation_id) / "rollback"
        if not root.exists():
            return []
        reports = [read_json(path, None) for path in root.glob("rollback_*.json")]
        summaries = [self._report_summary(item) for item in reports if isinstance(item, dict)]
        return sorted(summaries, key=lambda item: item.get("createdAt", ""), reverse=True)

    def get_report(self, conversation_id: str, report_id: str) -> dict[str, Any]:
        safe_id = "".join(ch for ch in report_id if ch.isalnum() or ch in {"_", "-"})
        if not safe_id or safe_id != report_id:
            raise RuntimeError("回退报告 id 不合法。")
        path = conversation_root(conversation_id) / "rollback" / f"{safe_id}.json"
        root = (conversation_root(conversation_id) / "rollback").resolve()
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise RuntimeError("回退报告路径超出当前对话目录。")
        report = read_json(resolved, None)
        if not isinstance(report, dict):
            raise RuntimeError("回退报告不存在。")
        return report

    def restore_checkpoint(self, conversation_id: str, checkpoint_id: str) -> dict[str, Any]:
        repo, affected_files = self._checkpoint_scope(conversation_id, checkpoint_id)
        before = self._diff_snapshot(repo, affected_files)
        self.events.append(conversation_id, "rollback.checkpoint.begin", {"checkpointId": checkpoint_id, "affectedFiles": affected_files})
        result = self.checkpoints.restore(conversation_id, checkpoint_id)
        report = self._write_report(conversation_id, "checkpoint", repo, before, self._diff_snapshot(repo, affected_files), result, {"checkpointId": checkpoint_id})
        output = {**result, "rollbackReport": report}
        self.events.append(conversation_id, "rollback.checkpoint.end", self._event_result(output))
        return output

    def restore_checkpoint_file(self, conversation_id: str, checkpoint_id: str, relative_path: str) -> dict[str, Any]:
        repo, _affected_files = self._checkpoint_scope(conversation_id, checkpoint_id)
        affected_files = [self._normalize_relative(repo, relative_path)]
        before = self._diff_snapshot(repo, affected_files)
        self.events.append(
            conversation_id,
            "rollback.checkpoint_file.begin",
            {"checkpointId": checkpoint_id, "relativePath": relative_path},
        )
        result = self.checkpoints.restore_file(conversation_id, checkpoint_id, relative_path)
        report = self._write_report(
            conversation_id,
            "checkpoint_file",
            repo,
            before,
            self._diff_snapshot(repo, affected_files),
            result,
            {"checkpointId": checkpoint_id, "relativePath": affected_files[0]},
        )
        output = {**result, "rollbackReport": report}
        self.events.append(conversation_id, "rollback.checkpoint_file.end", self._event_result(output))
        return output

    def restore_checkpoint_hunk(self, conversation_id: str, checkpoint_id: str, relative_path: str, hunk_index: int) -> dict[str, Any]:
        repo, _affected_files = self._checkpoint_scope(conversation_id, checkpoint_id)
        affected_files = [self._normalize_relative(repo, relative_path)]
        before = self._diff_snapshot(repo, affected_files)
        self.events.append(
            conversation_id,
            "rollback.checkpoint_hunk.begin",
            {"checkpointId": checkpoint_id, "relativePath": relative_path, "hunkIndex": hunk_index},
        )
        result = self.checkpoints.restore_hunk(conversation_id, checkpoint_id, relative_path, hunk_index)
        report = self._write_report(
            conversation_id,
            "checkpoint_hunk",
            repo,
            before,
            self._diff_snapshot(repo, affected_files),
            result,
            {"checkpointId": checkpoint_id, "relativePath": affected_files[0], "hunkIndex": hunk_index},
        )
        output = {**result, "rollbackReport": report}
        self.events.append(conversation_id, "rollback.checkpoint_hunk.end", self._event_result(output))
        return output

    def hard_reset(self, conversation_id: str, repo_path: str, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            raise RuntimeError("全仓硬重置会丢弃沙盒内全部改动，必须显式确认。")
        repo = Path(repo_path).resolve()
        before = self._diff_snapshot(repo, None)
        self.events.append(conversation_id, "rollback.original.begin", {"repoPath": str(repo)})
        reset = subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=repo, capture_output=True, text=True, timeout=30, check=False)
        clean = subprocess.run(["git", "clean", "-fd"], cwd=repo, capture_output=True, text=True, timeout=30, check=False)
        ok = reset.returncode == 0 and clean.returncode == 0
        result = {
            "ok": ok,
            "summary": "已回退到沙盒仓库原始 HEAD。" if ok else "全仓回退失败。",
            "resetStdout": reset.stdout.strip(),
            "resetStderr": reset.stderr.strip(),
            "cleanStdout": clean.stdout.strip(),
            "cleanStderr": clean.stderr.strip(),
        }
        report = self._write_report(conversation_id, "original", repo, before, self._diff_snapshot(repo, None), result, {"repoPath": str(repo)})
        result["rollbackReport"] = report
        self.events.append(conversation_id, "rollback.original.end", self._event_result(result))
        if not ok:
            raise RuntimeError(result["summary"])
        return result

    def _checkpoint_scope(self, conversation_id: str, checkpoint_id: str) -> tuple[Path, list[str]]:
        manifest_path = conversation_root(conversation_id) / "checkpoints" / checkpoint_id / "manifest.json"
        manifest = read_json(manifest_path, None)
        if not manifest:
            raise RuntimeError("检查点不存在。")
        repo = Path(manifest["repoPath"]).resolve()
        files = [
            str(item.get("relativePath") or "").replace("\\", "/")
            for item in manifest.get("files", [])
            if isinstance(item, dict) and item.get("relativePath")
        ]
        return repo, files

    def _write_report(
        self,
        conversation_id: str,
        operation: str,
        repo: Path,
        before: dict[str, Any],
        after: dict[str, Any],
        result: dict[str, Any],
        target: dict[str, Any],
    ) -> dict[str, Any]:
        rollback_id = f"rollback_{uuid4().hex[:10]}"
        root = conversation_root(conversation_id) / "rollback"
        root.mkdir(parents=True, exist_ok=True)
        report_path = root / f"{rollback_id}.json"
        report = {
            "id": rollback_id,
            "conversationId": conversation_id,
            "operation": operation,
            "target": target,
            "repoPath": str(repo),
            "ok": bool(result.get("ok")),
            "summary": result.get("summary", ""),
            "affectedFiles": self._affected_files(result, target),
            "before": before,
            "after": after,
            "confirmation": self._confirmation(result, before, after),
            "createdAt": now_iso(),
            "reportPath": str(report_path),
        }
        write_json(report_path, report)
        return {
            "id": rollback_id,
            "operation": operation,
            "summary": report["summary"],
            "affectedFiles": report["affectedFiles"],
            "beforeFileCount": before.get("fileCount", 0),
            "afterFileCount": after.get("fileCount", 0),
            "confirmation": report["confirmation"],
            "reportPath": str(report_path),
            "createdAt": report["createdAt"],
        }

    def _diff_snapshot(self, repo: Path, files: list[str] | None) -> dict[str, Any]:
        normalized_files = [self._normalize_relative(repo, file_path) for file_path in files or [] if file_path]
        diff_args = ["diff", "--no-ext-diff"]
        if normalized_files:
            diff_args.extend(["--", *normalized_files])
        diff = self._git(repo, diff_args)
        status_args = ["status", "--short"]
        if normalized_files:
            status_args.extend(["--", *normalized_files])
        status = self._git(repo, status_args)
        return {
            "fileCount": self._status_file_count(status),
            "statusShort": status,
            "diff": diff,
            "diffBytes": len(diff.encode("utf-8")),
            "capturedAt": now_iso(),
        }

    def _affected_files(self, result: dict[str, Any], target: dict[str, Any]) -> list[str]:
        files: list[str] = []
        for key in ("restoredFiles", "removedFiles"):
            value = result.get(key)
            if isinstance(value, list):
                files.extend(str(item).replace("\\", "/") for item in value if item)
        relative_path = target.get("relativePath")
        if isinstance(relative_path, str) and relative_path:
            files.append(relative_path.replace("\\", "/"))
        return sorted(set(files))

    def _event_result(self, result: dict[str, Any]) -> dict[str, Any]:
        report = result.get("rollbackReport") if isinstance(result.get("rollbackReport"), dict) else None
        payload = {key: value for key, value in result.items() if key != "rollbackReport"}
        if report:
            payload["rollbackReport"] = {
                "id": report.get("id"),
                "operation": report.get("operation"),
                "reportPath": report.get("reportPath"),
                "beforeFileCount": report.get("beforeFileCount"),
                "afterFileCount": report.get("afterFileCount"),
                "confirmation": report.get("confirmation"),
            }
        return payload

    def _confirmation(self, result: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_files = int(before.get("fileCount") or 0)
        after_files = int(after.get("fileCount") or 0)
        before_bytes = int(before.get("diffBytes") or 0)
        after_bytes = int(after.get("diffBytes") or 0)
        if not result.get("ok"):
            status = "failed"
            ok = False
            summary = "回退命令未成功，不能确认沙盒已回到预期状态。"
        elif after_files == 0 and after_bytes == 0:
            status = "clean"
            ok = True
            summary = "回退后目标范围已无剩余 diff。"
        elif after_files < before_files or after_bytes < before_bytes:
            status = "improved"
            ok = True
            summary = "回退后目标范围的变更已减少，仍建议查看剩余 diff。"
        elif after_files == before_files and after_bytes == before_bytes:
            status = "unchanged"
            ok = False
            summary = "回退前后 diff 未发生变化，需要人工确认目标是否正确。"
        elif after_files > before_files or after_bytes > before_bytes:
            status = "expanded"
            ok = False
            summary = "回退后目标范围的变更多了，需要人工检查。"
        else:
            status = "unknown"
            ok = False
            summary = "系统无法判断回退是否达到预期，请人工查看前后 diff。"
        return {
            "status": status,
            "ok": ok,
            "summary": summary,
            "beforeFileCount": before_files,
            "afterFileCount": after_files,
            "beforeDiffBytes": before_bytes,
            "afterDiffBytes": after_bytes,
        }

    def _report_summary(self, report: dict[str, Any]) -> dict[str, Any]:
        before = report.get("before") if isinstance(report.get("before"), dict) else {}
        after = report.get("after") if isinstance(report.get("after"), dict) else {}
        return {
            "id": report.get("id"),
            "operation": report.get("operation"),
            "summary": report.get("summary", ""),
            "affectedFiles": report.get("affectedFiles") if isinstance(report.get("affectedFiles"), list) else [],
            "beforeFileCount": before.get("fileCount", 0),
            "afterFileCount": after.get("fileCount", 0),
            "confirmation": report.get("confirmation") if isinstance(report.get("confirmation"), dict) else None,
            "reportPath": report.get("reportPath"),
            "createdAt": report.get("createdAt"),
        }

    def _normalize_relative(self, repo: Path, relative_path: str) -> str:
        target = (repo / relative_path).resolve()
        if target != repo and repo not in target.parents:
            raise RuntimeError("文件路径超出当前沙盒仓库。")
        return str(target.relative_to(repo)).replace("\\", "/")

    def _git(self, repo: Path, args: list[str]) -> str:
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
        return (result.stdout or result.stderr).strip()

    def _status_file_count(self, status: str) -> int:
        return len([line for line in status.splitlines() if line.strip()])
