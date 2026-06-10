from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from server_py.core.json_io import now_iso
from server_py.core.paths import conversation_root
from server_py.runtime.events import EventStore


class SandboxManager:
    def __init__(self, events: EventStore) -> None:
        self.events = events

    def create_from_github(self, conversation_id: str, repo_url: str) -> dict[str, Any]:
        root = conversation_root(conversation_id)
        repo_path = root / "repo"
        root.mkdir(parents=True, exist_ok=True)
        if repo_path.exists():
            shutil.rmtree(repo_path)

        self.events.append(conversation_id, "sandbox.create.begin", {"sourceType": "github", "source": repo_url})
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(repo_path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            self.events.append(conversation_id, "sandbox.create.failed", {"stderr": result.stderr.strip(), "stdout": result.stdout.strip()})
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "GitHub 仓库拉取失败。")

        status = self._status(conversation_id, root, repo_path)
        self.events.append(conversation_id, "sandbox.create.end", status)
        return status

    def create_from_local_path(self, conversation_id: str, source_path: str) -> dict[str, Any]:
        source = Path(source_path).resolve()
        if not source.exists() or not source.is_dir():
            raise RuntimeError("本地仓库路径不存在或不是目录。")

        root = conversation_root(conversation_id)
        repo_path = root / "repo"
        root.mkdir(parents=True, exist_ok=True)
        if repo_path.exists():
            shutil.rmtree(repo_path)

        self.events.append(conversation_id, "sandbox.create.begin", {"sourceType": "local", "source": str(source)})
        shutil.copytree(source, repo_path, ignore=shutil.ignore_patterns("node_modules", "dist", ".next", "coverage", "__pycache__"))
        status = self._status(conversation_id, root, repo_path)
        self.events.append(conversation_id, "sandbox.create.end", status)
        return status

    def _status(self, conversation_id: str, root: Path, repo_path: Path) -> dict[str, Any]:
        return {
            "id": f"sandbox_{uuid4().hex[:10]}",
            "conversationId": conversation_id,
            "rootPath": str(root),
            "repoPath": str(repo_path),
            "createdAt": now_iso(),
        }
