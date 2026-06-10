from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import conversation_root
from server_py.runtime.events import EventStore


class GitSubmissionService:
    """提测链路：沙盒改动 -> 提测分支 -> commit -> (可选) push + GitHub PR。

    没有 GITHUB_TOKEN 或 push 失败时，降级为 PR-ready 产物：
    本地分支 + format-patch + PR 描述文件，保证链路终点永远有交付物。
    """

    def __init__(self, events: EventStore) -> None:
        self.events = events

    def submit(
        self,
        conversation_id: str,
        state: dict[str, Any],
        tool_plan: dict[str, Any] | None,
        confirmed: bool,
        title: str | None = None,
        base_branch: str | None = None,
    ) -> dict[str, Any]:
        if not confirmed:
            raise RuntimeError("生成提测分支会在沙盒仓库创建 commit，必须显式确认。")
        sandbox = state.get("sandbox")
        if not sandbox or not sandbox.get("repoPath"):
            raise RuntimeError("生成提测分支需要当前对话沙盒。")
        repo = Path(sandbox["repoPath"]).resolve()
        if not (repo / ".git").exists():
            raise RuntimeError("当前沙盒不是 git 仓库，无法创建提测分支。")

        requirement = str(state.get("lastRequirement") or (tool_plan or {}).get("requirement") or "").strip()
        delivery_root = conversation_root(conversation_id) / "delivery"
        delivery_root.mkdir(parents=True, exist_ok=True)

        self.events.append(conversation_id, "delivery.submit.begin", {"repo": str(repo)}, actor="runtime")

        branch = self._branch_name(conversation_id)
        base = base_branch or self._detect_base_branch(repo)
        pr_title = (title or "").strip() or self._default_title(requirement)

        status = self._git(repo, ["status", "--porcelain", "-uall"])
        if not status.strip():
            raise RuntimeError("沙盒没有任何改动，无法生成提测分支。")

        current_branch = self._git(repo, ["branch", "--show-current"]).strip()
        if current_branch != branch:
            existing = self._git(repo, ["branch", "--list", branch]).strip()
            if existing:
                self._git_checked(repo, ["checkout", branch])
            else:
                self._git_checked(repo, ["checkout", "-b", branch])

        self._git_checked(repo, ["add", "-A"])
        commit_message = self._commit_message(pr_title, requirement, tool_plan)
        commit_result = self._git_with_identity(repo, ["commit", "-m", commit_message])
        if commit_result.returncode != 0 and "nothing to commit" not in (commit_result.stdout + commit_result.stderr):
            raise RuntimeError(f"提测 commit 失败：{(commit_result.stderr or commit_result.stdout)[:500]}")
        commit_sha = self._git(repo, ["rev-parse", "HEAD"]).strip()

        pr_body = self._pr_description(conversation_id, requirement, tool_plan, commit_sha, branch, base)
        pr_body_path = delivery_root / "pr-description.md"
        pr_body_path.write_text(pr_body, encoding="utf-8")

        patch_text = self._git(repo, ["format-patch", "--stdout", f"{base}..HEAD" if self._ref_exists(repo, base) else "-1"])
        patch_path = delivery_root / "submission.patch"
        patch_path.write_text(patch_text, encoding="utf-8")

        remote_result = self._git_raw(repo, ["remote", "get-url", "origin"])
        remote_url = remote_result.stdout.strip() if remote_result.returncode == 0 else ""
        github_repo = self._parse_github_repo(remote_url)
        token = os.environ.get("GITHUB_TOKEN", "").strip()

        push_result: dict[str, Any] = {"attempted": False, "ok": False, "detail": ""}
        pr_result: dict[str, Any] = {"attempted": False, "ok": False, "url": None, "detail": ""}

        if token and github_repo:
            push_result = self._push_branch(repo, branch, token, remote_url)
            if push_result["ok"]:
                pr_result = self._create_pull_request(github_repo, token, branch, base, pr_title, pr_body)
        else:
            push_result["detail"] = "未配置 GITHUB_TOKEN 或 origin 不是 GitHub 仓库，跳过 push；已生成 PR-ready 分支和 patch。"

        record = {
            "id": f"submission_{conversation_id}",
            "conversationId": conversation_id,
            "generatedAt": now_iso(),
            "branch": branch,
            "baseBranch": base,
            "commitSha": commit_sha,
            "title": pr_title,
            "requirement": requirement,
            "remoteUrl": remote_url or None,
            "githubRepo": github_repo,
            "push": push_result,
            "pullRequest": pr_result,
            "artifacts": {
                "prDescriptionPath": str(pr_body_path),
                "patchPath": str(patch_path),
            },
            "mode": "github-pr" if pr_result.get("ok") else "pr-ready-branch",
            "notes": [
                "commit 只发生在当前对话沙盒仓库，原始仓库不受影响。",
                "未配置 GITHUB_TOKEN 时，可用 submission.patch + pr-description.md 人工提测。",
            ],
        }
        write_json(delivery_root / "submission.json", record)
        self.events.append(
            conversation_id,
            "delivery.submit.end",
            {
                "branch": branch,
                "commitSha": commit_sha,
                "mode": record["mode"],
                "prUrl": pr_result.get("url"),
                "pushOk": push_result.get("ok"),
            },
            actor="runtime",
        )
        return record

    def latest(self, conversation_id: str) -> dict[str, Any] | None:
        record = read_json(conversation_root(conversation_id) / "delivery" / "submission.json", None)
        return record if isinstance(record, dict) else None

    def _branch_name(self, conversation_id: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "-", conversation_id)[:48].strip("-")
        return f"workbench/{safe or 'delivery'}"

    def _default_title(self, requirement: str) -> str:
        first_line = (requirement.splitlines() or [""])[0].strip()
        return (first_line[:72] or "AI Delivery Workbench 提测变更")

    def _detect_base_branch(self, repo: Path) -> str:
        head = self._git(repo, ["symbolic-ref", "refs/remotes/origin/HEAD"]).strip()
        if head.startswith("refs/remotes/origin/"):
            return head.rsplit("/", 1)[-1]
        for candidate in ("main", "master"):
            if self._ref_exists(repo, candidate):
                return candidate
        current = self._git(repo, ["branch", "--show-current"]).strip()
        return current or "main"

    def _ref_exists(self, repo: Path, ref: str) -> bool:
        result = self._git_raw(repo, ["rev-parse", "--verify", "--quiet", ref])
        return result.returncode == 0

    def _commit_message(self, title: str, requirement: str, tool_plan: dict[str, Any] | None) -> str:
        lines = [title, ""]
        if requirement:
            lines.extend(["需求：", requirement[:1000], ""])
        if tool_plan:
            steps = [step for step in tool_plan.get("steps", []) if isinstance(step, dict)]
            done = sum(1 for step in steps if step.get("status") == "completed")
            lines.append(f"工具计划 {tool_plan.get('id')}：{done}/{len(steps)} 步完成。")
        lines.append("由 AI Delivery Workbench 在对话沙盒中生成。")
        return "\n".join(lines)

    def _pr_description(
        self,
        conversation_id: str,
        requirement: str,
        tool_plan: dict[str, Any] | None,
        commit_sha: str,
        branch: str,
        base: str,
    ) -> str:
        evidence = (tool_plan or {}).get("evidence") if isinstance((tool_plan or {}).get("evidence"), dict) else {}
        verification_results = evidence.get("verificationResults") if isinstance(evidence.get("verificationResults"), list) else []
        preview_results = evidence.get("previewResults") if isinstance(evidence.get("previewResults"), list) else []
        diff_files = evidence.get("diffFiles") if isinstance(evidence.get("diffFiles"), list) else []

        lines = [
            f"# {self._default_title(requirement)}",
            "",
            "## 需求",
            "",
            requirement or "（见会话记录）",
            "",
            "## 变更摘要",
            "",
            f"- 分支：`{branch}`（基于 `{base}`）",
            f"- Commit：`{commit_sha[:12]}`",
            f"- 会话：`{conversation_id}`",
        ]
        if diff_files:
            lines.extend(["", "## 涉及文件", ""])
            for item in diff_files[:30]:
                path = item.get("path") if isinstance(item, dict) else item
                lines.append(f"- `{path}`")
        if verification_results:
            passed = sum(1 for item in verification_results if isinstance(item, dict) and item.get("ok"))
            lines.extend(["", "## 验证", "", f"- 验证命令：{passed}/{len(verification_results)} 通过"])
        if preview_results:
            passed = sum(1 for item in preview_results if isinstance(item, dict) and item.get("ok"))
            lines.extend([f"- 预览 smoke：{passed}/{len(preview_results)} 通过"])
        lines.extend(
            [
                "",
                "## 过程证据",
                "",
                "- 事件流、工具计划、checkpoint、diff、验证报告与预览截图见会话工作区 delivery/ 目录。",
                "",
                "> 本 PR 由 AI Delivery Workbench 生成，所有改动在对话沙盒中完成并经人工确认。",
            ]
        )
        return "\n".join(lines) + "\n"

    def _push_branch(self, repo: Path, branch: str, token: str, remote_url: str) -> dict[str, Any]:
        result: dict[str, Any] = {"attempted": True, "ok": False, "detail": ""}
        if (repo / ".git" / "shallow").exists():
            unshallow = self._git_raw(repo, ["fetch", "--unshallow", "origin"], timeout=300)
            if unshallow.returncode != 0:
                result["detail"] = f"浅克隆 unshallow 失败：{(unshallow.stderr or unshallow.stdout)[:300]}"
                return result
        push_url = self._token_url(remote_url, token)
        push = self._git_raw(repo, ["push", push_url, f"{branch}:{branch}"], timeout=300)
        result["ok"] = push.returncode == 0
        detail = (push.stderr or push.stdout or "").strip()
        result["detail"] = re.sub(r"x-access-token:[^@]+@", "x-access-token:***@", detail)[:500]
        return result

    def _token_url(self, remote_url: str, token: str) -> str:
        match = re.match(r"^https://github\.com/(.+)$", remote_url.strip())
        if match:
            return f"https://x-access-token:{token}@github.com/{match.group(1)}"
        match = re.match(r"^git@github\.com:(.+)$", remote_url.strip())
        if match:
            return f"https://x-access-token:{token}@github.com/{match.group(1)}"
        return remote_url

    def _parse_github_repo(self, remote_url: str) -> str | None:
        match = re.match(r"^(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?/?$", remote_url.strip())
        return match.group(1) if match else None

    def _create_pull_request(
        self,
        github_repo: str,
        token: str,
        branch: str,
        base: str,
        title: str,
        body: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"attempted": True, "ok": False, "url": None, "detail": ""}
        payload = json.dumps({"title": title, "head": branch, "base": base, "body": body}).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.github.com/repos/{github_repo}/pulls",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "ai-delivery-workbench",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            result["ok"] = True
            result["url"] = data.get("html_url")
            result["number"] = data.get("number")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            result["detail"] = f"HTTP {error.code}: {detail}"
        except urllib.error.URLError as error:
            result["detail"] = f"网络错误：{getattr(error, 'reason', error)}"
        return result

    def _git(self, repo: Path, args: list[str]) -> str:
        result = self._git_raw(repo, args)
        return result.stdout or result.stderr or ""

    def _git_checked(self, repo: Path, args: list[str]) -> str:
        result = self._git_raw(repo, args)
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args[:2])} 失败：{(result.stderr or result.stdout)[:500]}")
        return result.stdout

    def _git_with_identity(self, repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        identity = [
            "-c",
            "user.name=AI Delivery Workbench",
            "-c",
            "user.email=workbench@local",
        ]
        return self._git_raw(repo, identity + args)

    def _git_raw(self, repo: Path, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
