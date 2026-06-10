from __future__ import annotations

import difflib
import subprocess
from pathlib import Path
from typing import Any

from server_py.core.json_io import now_iso, read_json
from server_py.core.paths import conversation_root


class SandboxDiffService:
    def current(self, conversation_id: str, repo_path: str) -> dict[str, Any]:
        repo = Path(repo_path).resolve()
        files = [self._current_file_diff(repo, item) for item in self._changed_files(repo)]
        files = [item for item in files if item]
        return self._response(conversation_id, "current", files, "当前沙盒相对原始仓库的变更。")

    def file(self, conversation_id: str, repo_path: str, relative_path: str) -> dict[str, Any]:
        repo = Path(repo_path).resolve()
        normalized = self._normalize_relative(repo, relative_path)
        changed = {item["path"]: item for item in self._changed_files(repo)}
        item = self._current_file_diff(repo, changed.get(normalized, {"path": normalized, "status": "modified"}))
        files = [item] if item else []
        return self._response(conversation_id, "file", files, f"{normalized} 的当前变更。")

    def checkpoint(self, conversation_id: str, checkpoint_id: str) -> dict[str, Any]:
        manifest_path = conversation_root(conversation_id) / "checkpoints" / checkpoint_id / "manifest.json"
        manifest = read_json(manifest_path, None)
        if not manifest:
            raise RuntimeError("检查点不存在。")

        repo = Path(manifest["repoPath"]).resolve()
        files: list[dict[str, Any]] = []
        for entry in manifest.get("files", []):
            item = self._checkpoint_file_diff(repo, entry)
            if item and item["diff"].strip():
                files.append(item)

        response = self._response(conversation_id, "checkpoint", files, f"检查点 {checkpoint_id} 到当前沙盒的差异。")
        response["checkpointId"] = checkpoint_id
        response["checkpointLabel"] = manifest.get("label")
        response["checkpointCreatedAt"] = manifest.get("createdAt")
        return response

    def _changed_files(self, repo: Path) -> list[dict[str, str]]:
        output = self._git(repo, ["status", "--porcelain"])
        files: list[dict[str, str]] = []
        for line in output.splitlines():
            if len(line) < 4:
                continue
            code = line[:2]
            raw_path = line[3:].strip()
            if " -> " in raw_path:
                raw_path = raw_path.split(" -> ", 1)[1]
            status = self._status_from_code(code)
            files.append({"path": raw_path.replace("\\", "/"), "status": status})
        return files

    def _current_file_diff(self, repo: Path, item: dict[str, str]) -> dict[str, Any] | None:
        relative = self._normalize_relative(repo, item["path"])
        status = item.get("status", "modified")
        if status == "added" and not self._is_tracked(repo, relative):
            target = self._resolve_inside(repo, relative)
            new_text = self._read_text(target) if target.exists() and target.is_file() else ""
            diff = self._unified_diff("", new_text, relative)
        else:
            diff = self._git(repo, ["diff", "--no-ext-diff", "--", relative])
            if not diff and status == "added":
                target = self._resolve_inside(repo, relative)
                new_text = self._read_text(target) if target.exists() and target.is_file() else ""
                diff = self._unified_diff("", new_text, relative)

        additions, deletions = self._count_changes(diff)
        return {
            "path": relative,
            "status": status,
            "additions": additions,
            "deletions": deletions,
            "diff": diff,
        }

    def _checkpoint_file_diff(self, repo: Path, entry: dict[str, Any]) -> dict[str, Any] | None:
        relative = self._normalize_relative(repo, str(entry.get("relativePath", "")))
        existed = bool(entry.get("existed"))
        target = self._resolve_inside(repo, relative)
        current_exists = target.exists() and target.is_file()

        old_text = ""
        snapshot_path = entry.get("snapshotPath")
        if existed and snapshot_path:
            snapshot = Path(snapshot_path)
            if snapshot.exists() and snapshot.is_file():
                old_text = self._read_text(snapshot)

        new_text = self._read_text(target) if current_exists else ""
        if existed and not current_exists:
            status = "deleted"
        elif not existed and current_exists:
            status = "added"
        elif old_text != new_text:
            status = "modified"
        else:
            status = "unchanged"

        diff = self._unified_diff(old_text, new_text, relative)
        additions, deletions = self._count_changes(diff)
        return {
            "path": relative,
            "status": status,
            "additions": additions,
            "deletions": deletions,
            "diff": diff,
        }

    def _status_from_code(self, code: str) -> str:
        if code == "??":
            return "added"
        if "D" in code:
            return "deleted"
        if "A" in code:
            return "added"
        if "R" in code:
            return "renamed"
        return "modified"

    def _is_tracked(self, repo: Path, relative_path: str) -> bool:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative_path],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        return result.returncode == 0

    def _git(self, repo: Path, args: list[str]) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        return result.stdout

    def _unified_diff(self, old_text: str, new_text: str, relative_path: str) -> str:
        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()
        return "\n".join(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                lineterm="",
            )
        )

    def _count_changes(self, diff: str) -> tuple[int, int]:
        additions = 0
        deletions = 0
        for line in diff.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                additions += 1
            elif line.startswith("-"):
                deletions += 1
        return additions, deletions

    def _read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8-sig", errors="replace")

    def _resolve_inside(self, root: Path, relative_path: str) -> Path:
        if not relative_path.strip():
            raise RuntimeError("缺少文件路径。")
        target = (root / relative_path).resolve()
        if target != root and root not in target.parents:
            raise RuntimeError("文件路径超出当前沙盒仓库。")
        return target

    def _normalize_relative(self, root: Path, relative_path: str) -> str:
        target = self._resolve_inside(root, relative_path)
        return str(target.relative_to(root)).replace("\\", "/")

    def _response(self, conversation_id: str, kind: str, files: list[dict[str, Any]], summary: str) -> dict[str, Any]:
        return {
            "conversationId": conversation_id,
            "kind": kind,
            "summary": summary,
            "fileCount": len(files),
            "files": files,
            "generatedAt": now_iso(),
        }
