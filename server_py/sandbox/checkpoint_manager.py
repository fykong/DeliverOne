from __future__ import annotations

import shutil
import subprocess
import difflib
from pathlib import Path
from typing import Any
from uuid import uuid4

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import conversation_root


class CheckpointManager:
    def create(
        self,
        conversation_id: str,
        repo_path: str,
        label: str,
        file_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        repo = Path(repo_path).resolve()
        checkpoint_id = f"ckpt_{uuid4().hex[:10]}"
        root = conversation_root(conversation_id) / "checkpoints" / checkpoint_id
        files_root = root / "files"
        files_root.mkdir(parents=True, exist_ok=True)

        selected = file_paths if file_paths is not None else self._changed_files(repo)
        entries: list[dict[str, Any]] = []
        for relative in selected:
            target = self._resolve_inside(repo, relative)
            snapshot = files_root / relative
            existed = target.exists()
            if existed and target.is_file():
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, snapshot)
            entries.append(
                {
                    "relativePath": relative,
                    "existed": existed,
                    "snapshotPath": str(snapshot) if existed else None,
                    "size": target.stat().st_size if existed and target.is_file() else 0,
                }
            )

        manifest = {
            "id": checkpoint_id,
            "conversationId": conversation_id,
            "repoPath": str(repo),
            "label": label,
            "files": entries,
            "createdAt": now_iso(),
        }
        write_json(root / "manifest.json", manifest)
        return manifest

    def list(self, conversation_id: str) -> list[dict[str, Any]]:
        root = conversation_root(conversation_id) / "checkpoints"
        if not root.exists():
            return []
        manifests = [read_json(path / "manifest.json", None) for path in root.iterdir() if path.is_dir()]
        return sorted([item for item in manifests if item], key=lambda item: item.get("createdAt", ""), reverse=True)

    def restore(self, conversation_id: str, checkpoint_id: str) -> dict[str, Any]:
        manifest_path = conversation_root(conversation_id) / "checkpoints" / checkpoint_id / "manifest.json"
        manifest = read_json(manifest_path, None)
        if not manifest:
            raise RuntimeError("检查点不存在。")

        repo = Path(manifest["repoPath"]).resolve()
        restored: list[str] = []
        removed: list[str] = []
        for entry in manifest.get("files", []):
            relative = entry["relativePath"]
            target = self._resolve_inside(repo, relative)
            if entry.get("existed"):
                snapshot = Path(entry["snapshotPath"])
                if snapshot.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(snapshot, target)
                    restored.append(relative)
            elif target.exists():
                target.unlink()
                removed.append(relative)

        return {
            "ok": True,
            "checkpointId": checkpoint_id,
            "restoredFiles": restored,
            "removedFiles": removed,
            "summary": f"已恢复检查点 {checkpoint_id}，恢复 {len(restored)} 个文件，删除 {len(removed)} 个新文件。",
        }

    def restore_file(self, conversation_id: str, checkpoint_id: str, relative_path: str) -> dict[str, Any]:
        manifest_path = conversation_root(conversation_id) / "checkpoints" / checkpoint_id / "manifest.json"
        manifest = read_json(manifest_path, None)
        if not manifest:
            raise RuntimeError("检查点不存在。")

        repo = Path(manifest["repoPath"]).resolve()
        normalized = str(self._resolve_inside(repo, relative_path).relative_to(repo)).replace("\\", "/")
        entry = next((item for item in manifest.get("files", []) if item.get("relativePath") == normalized), None)
        if not entry:
            raise RuntimeError("这个检查点没有记录该文件。")

        target = self._resolve_inside(repo, normalized)
        restored: list[str] = []
        removed: list[str] = []
        if entry.get("existed"):
            snapshot = Path(entry["snapshotPath"])
            if not snapshot.exists():
                raise RuntimeError("检查点快照文件不存在。")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snapshot, target)
            restored.append(normalized)
        elif target.exists():
            target.unlink()
            removed.append(normalized)

        return {
            "ok": True,
            "checkpointId": checkpoint_id,
            "relativePath": normalized,
            "restoredFiles": restored,
            "removedFiles": removed,
            "summary": f"已从检查点 {checkpoint_id} 回退文件 {normalized}。",
        }

    def restore_hunk(self, conversation_id: str, checkpoint_id: str, relative_path: str, hunk_index: int) -> dict[str, Any]:
        manifest_path = conversation_root(conversation_id) / "checkpoints" / checkpoint_id / "manifest.json"
        manifest = read_json(manifest_path, None)
        if not manifest:
            raise RuntimeError("检查点不存在。")
        if hunk_index < 0:
            raise RuntimeError("hunkIndex 不能小于 0。")

        repo = Path(manifest["repoPath"]).resolve()
        normalized = str(self._resolve_inside(repo, relative_path).relative_to(repo)).replace("\\", "/")
        entry = next((item for item in manifest.get("files", []) if item.get("relativePath") == normalized), None)
        if not entry:
            raise RuntimeError("这个检查点没有记录该文件。")

        old_text, current_text = self._checkpoint_text_pair(repo, entry)
        old_lines = old_text.splitlines()
        current_lines = current_text.splitlines()
        hunks = self._grouped_hunks(old_lines, current_lines)
        if hunk_index >= len(hunks):
            raise RuntimeError("hunkIndex 超出当前 diff 范围。")

        hunk = hunks[hunk_index]
        old_start = min(opcode[1] for opcode in hunk)
        old_end = max(opcode[2] for opcode in hunk)
        current_start = min(opcode[3] for opcode in hunk)
        current_end = max(opcode[4] for opcode in hunk)
        next_lines = current_lines[:current_start] + old_lines[old_start:old_end] + current_lines[current_end:]

        target = self._resolve_inside(repo, normalized)
        removed: list[str] = []
        restored: list[str] = []
        if not entry.get("existed") and not next_lines:
            if target.exists():
                target.unlink()
                removed.append(normalized)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self._join_lines(next_lines, old_text.endswith("\n") or current_text.endswith("\n")), encoding="utf-8")
            restored.append(normalized)

        return {
            "ok": True,
            "checkpointId": checkpoint_id,
            "relativePath": normalized,
            "hunkIndex": hunk_index,
            "restoredFiles": restored,
            "removedFiles": removed,
            "summary": f"已从检查点 {checkpoint_id} 回退 {normalized} 的第 {hunk_index + 1} 个变更块。",
        }

    def _changed_files(self, repo: Path) -> list[str]:
        result = subprocess.run(["git", "diff", "--name-only"], cwd=repo, capture_output=True, text=True, timeout=15, check=False)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _checkpoint_text_pair(self, repo: Path, entry: dict[str, Any]) -> tuple[str, str]:
        target = self._resolve_inside(repo, str(entry.get("relativePath", "")))
        old_text = ""
        snapshot_path = entry.get("snapshotPath")
        if entry.get("existed") and snapshot_path:
            snapshot = Path(snapshot_path)
            if snapshot.exists() and snapshot.is_file():
                old_text = snapshot.read_text(encoding="utf-8-sig", errors="replace")
        current_text = target.read_text(encoding="utf-8-sig", errors="replace") if target.exists() and target.is_file() else ""
        return old_text, current_text

    def _grouped_hunks(self, old_lines: list[str], current_lines: list[str]) -> list[list[tuple[str, int, int, int, int]]]:
        matcher = difflib.SequenceMatcher(None, old_lines, current_lines)
        return [list(group) for group in matcher.get_grouped_opcodes(n=3)]

    def _join_lines(self, lines: list[str], trailing_newline: bool) -> str:
        if not lines:
            return ""
        text = "\n".join(lines)
        return f"{text}\n" if trailing_newline else text

    def _resolve_inside(self, root: Path, relative_path: str) -> Path:
        if not relative_path:
            raise RuntimeError("缺少文件路径。")
        target = (root / relative_path).resolve()
        if target != root and root not in target.parents:
            raise RuntimeError("文件路径超出当前沙盒仓库。")
        return target
