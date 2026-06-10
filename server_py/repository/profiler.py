from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def _git(args: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15, check=False)
        return result.stdout.strip()
    except Exception:
        return ""


class RepoProfiler:
    def profile(self, repo_id: str, source_type: str, source: str, repo_path: str) -> dict[str, Any]:
        repo = Path(repo_path)
        scripts: dict[str, str] = {}
        package_manager = "unknown"

        package_json = repo / "package.json"
        if package_json.exists():
            try:
                payload = json.loads(package_json.read_text(encoding="utf-8-sig"))
                scripts = payload.get("scripts", {}) or {}
                package_manager = "npm"
            except Exception:
                scripts = {}

        branch = _git(["branch", "--show-current"], repo)
        head = _git(["rev-parse", "--short", "HEAD"], repo)
        dirty = _git(["status", "--porcelain"], repo)

        return {
            "id": repo_id,
            "sourceType": source_type,
            "source": source,
            "branch": branch or None,
            "head": head or None,
            "packageManager": package_manager,
            "scripts": scripts,
            "dirtyFileCount": len([line for line in dirty.splitlines() if line.strip()]),
        }
