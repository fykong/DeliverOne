from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import server_py.delivery.git_submission as submission_module
import server_py.runtime.events as events_module
from server_py.delivery.git_submission import GitSubmissionService
from server_py.runtime.events import EventStore


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@pytest.fixture()
def sandbox_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("v1", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")

    def fake_root(conversation_id: str) -> Path:
        return tmp_path / "conv" / conversation_id

    monkeypatch.setattr(submission_module, "conversation_root", fake_root)
    monkeypatch.setattr(events_module, "conversation_root", fake_root, raising=False)
    return repo


def test_submit_creates_pr_ready_branch(sandbox_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    (sandbox_repo / "a.txt").write_text("v2", encoding="utf-8")
    (sandbox_repo / "newdir").mkdir()
    (sandbox_repo / "newdir" / "b.txt").write_text("new", encoding="utf-8")

    service = GitSubmissionService(EventStore())
    state = {"sandbox": {"id": "sb", "repoPath": str(sandbox_repo)}, "lastRequirement": "测试需求"}
    record = service.submit("conv_submit_test", state, None, confirmed=True)

    assert record["mode"] == "pr-ready-branch"
    assert record["branch"].startswith("workbench/")
    assert record["baseBranch"] == "main"
    assert Path(record["artifacts"]["prDescriptionPath"]).exists()
    patch_text = Path(record["artifacts"]["patchPath"]).read_text(encoding="utf-8")
    assert "newdir/b.txt" in patch_text
    # 提交后工作区干净
    assert _git(sandbox_repo, "status", "--porcelain").stdout.strip() == ""


def test_submit_requires_confirmation(sandbox_repo):
    service = GitSubmissionService(EventStore())
    state = {"sandbox": {"id": "sb", "repoPath": str(sandbox_repo)}}
    with pytest.raises(RuntimeError):
        service.submit("conv_submit_test2", state, None, confirmed=False)


def test_submit_rejects_clean_worktree(sandbox_repo):
    service = GitSubmissionService(EventStore())
    state = {"sandbox": {"id": "sb", "repoPath": str(sandbox_repo)}, "lastRequirement": "x"}
    with pytest.raises(RuntimeError, match="没有任何改动"):
        service.submit("conv_submit_test3", state, None, confirmed=True)
