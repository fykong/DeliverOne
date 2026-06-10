from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from server_py.tools.types import AgentTool, ToolContext


def _git(repo: Path, args: list[str]) -> str:
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
    return result.stdout.strip()


def _inspect_repository(_payload: Any, context: ToolContext) -> dict[str, Any]:
    if not context.repo_path:
        raise RuntimeError("当前对话还没有沙盒仓库。")
    repo = Path(context.repo_path).resolve()
    remotes = _git(repo, ["remote", "-v"])
    branch = _git(repo, ["branch", "--show-current"])
    head = _git(repo, ["rev-parse", "--short", "HEAD"])
    latest = _git(repo, ["log", "-1", "--pretty=%h %s"])
    return {
        "ok": True,
        "summary": "已读取当前沙盒仓库的 GitHub / Git 远程信息。",
        "data": {
            "repoPath": str(repo),
            "remotes": remotes,
            "branch": branch,
            "head": head,
            "latestCommit": latest,
        },
    }


def create_github_tools() -> list[AgentTool]:
    return [
        AgentTool(
            "github.inspect_repository",
            "检查 GitHub 仓库",
            "读取当前对话沙盒仓库的 remote、branch、HEAD 和最近提交，用于确认 Agent 正在正确仓库中工作。",
            "read",
            _inspect_repository,
            input_schema={},
        )
    ]
