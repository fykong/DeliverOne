from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from server_py.sandbox.checkpoint_manager import CheckpointManager
from server_py.tools.types import AgentTool, ToolContext

IGNORED_DIRS = {".git", "node_modules", "dist", "build", ".next", "coverage", "__pycache__"}
TEXT_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".scss",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".yml",
    ".yaml",
}


def _repo_path(context: ToolContext) -> Path:
    if not context.repo_path:
        raise RuntimeError("当前对话还没有可用的沙盒仓库路径。")
    return Path(context.repo_path).resolve()


def _resolve_inside(root: Path, relative_path: str) -> Path:
    if not relative_path:
        raise RuntimeError("缺少文件路径。")
    target = (root / relative_path).resolve()
    if root not in target.parents and target != root:
        raise RuntimeError("文件路径超出当前沙盒仓库。")
    return target


def _walk_files(root: Path, limit: int = 1000) -> list[Path]:
    results: list[Path] = []
    for item in root.rglob("*"):
        if len(results) >= limit:
            break
        if any(part in IGNORED_DIRS for part in item.relative_to(root).parts):
            continue
        if item.is_file():
            results.append(item)
    return results


def _read_text_if_small(path: Path) -> str:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return ""
    if path.stat().st_size > 200_000:
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _git_diff_summary(root: Path) -> dict[str, Any]:
    stat = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    ).stdout.strip()
    names = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    ).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    ).stdout
    tracked_files = [line for line in names.splitlines() if line.strip()]
    untracked_files = [line for line in untracked.splitlines() if line.strip()]
    files = list(dict.fromkeys([*tracked_files, *untracked_files]))
    return {"stat": stat, "files": files, "trackedFiles": tracked_files, "untrackedFiles": untracked_files}


def _search_files(payload: Any, context: ToolContext) -> dict[str, Any]:
    root = _repo_path(context)
    record = payload if isinstance(payload, dict) else {}
    query = str(record.get("query", "")).strip().lower()
    max_results = min(int(record.get("maxResults", 20) or 20), 50)
    files = _walk_files(root)

    if not query:
        return {
            "ok": True,
            "summary": f"已列出 {min(len(files), max_results)} 个仓库文件。",
            "data": {"files": [str(path.relative_to(root)) for path in files[:max_results]]},
        }

    matches: list[dict[str, str]] = []
    for path in files:
        if len(matches) >= max_results:
            break
        relative = str(path.relative_to(root))
        if query in relative.lower():
            matches.append({"path": relative, "reason": "文件名匹配"})
            continue
        if query in _read_text_if_small(path).lower():
            matches.append({"path": relative, "reason": "内容匹配"})

    return {"ok": True, "summary": f"代码搜索完成，找到 {len(matches)} 个候选文件。", "data": {"query": query, "matches": matches}}


def _read_file(payload: Any, context: ToolContext) -> dict[str, Any]:
    root = _repo_path(context)
    record = payload if isinstance(payload, dict) else {}
    relative_path = str(record.get("relativePath", "")).strip()
    max_bytes = min(int(record.get("maxBytes", 80_000) or 80_000), 200_000)
    target = _resolve_inside(root, relative_path)
    content = target.read_text(encoding="utf-8", errors="ignore")[:max_bytes]
    return {
        "ok": True,
        "summary": f"已读取 {relative_path}。",
        "data": {"relativePath": relative_path, "content": content, "truncated": len(content) >= max_bytes},
    }


def _git_diff(_payload: Any, context: ToolContext) -> dict[str, Any]:
    root = _repo_path(context)
    diff = _git_diff_summary(root)
    files = diff["files"]
    summary = f"当前沙盒有 {len(files)} 个文件存在 diff。" if files else "当前沙盒还没有代码 diff。"
    return {"ok": True, "summary": summary, "data": diff}


def _write_file_factory(checkpoints: CheckpointManager):
    def _write_file(payload: Any, context: ToolContext) -> dict[str, Any]:
        root = _repo_path(context)
        record = payload if isinstance(payload, dict) else {}
        relative_path = str(record.get("relativePath", "")).strip()
        content = str(record.get("content", ""))
        reason = str(record.get("reason", "Agent 写入文件"))
        target = _resolve_inside(root, relative_path)
        checkpoint = checkpoints.create(context.conversation_id, str(root), f"写入前：{relative_path}", [relative_path])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        diff = _git_diff_summary(root)
        return {
            "ok": True,
            "summary": f"已写入 {relative_path}，写入前检查点为 {checkpoint['id']}。",
            "data": {"relativePath": relative_path, "checkpoint": checkpoint, "reason": reason, "diff": diff},
        }

    return _write_file


def _apply_patch_factory(checkpoints: CheckpointManager):
    def _apply_patch(payload: Any, context: ToolContext) -> dict[str, Any]:
        root = _repo_path(context)
        record = payload if isinstance(payload, dict) else {}
        reason = str(record.get("reason", "Agent 应用多文件变更"))
        raw_changes = record.get("changes") or record.get("files")
        if not isinstance(raw_changes, list) or not raw_changes:
            raise RuntimeError("缺少 changes。")
        if len(raw_changes) > 30:
            raise RuntimeError("单次补丁最多允许修改 30 个文件。")

        changes: list[dict[str, Any]] = []
        relative_paths: list[str] = []
        for item in raw_changes:
            if not isinstance(item, dict):
                raise RuntimeError("changes 中的每一项都必须是对象。")
            relative_path = str(item.get("relativePath", "")).strip()
            action = str(item.get("action", "write")).strip().lower()
            if action not in {"write", "delete"}:
                raise RuntimeError(f"不支持的补丁动作：{action}")
            target = _resolve_inside(root, relative_path)
            if target.exists() and target.is_dir():
                raise RuntimeError(f"不能通过补丁工具修改目录：{relative_path}")
            changes.append({"relativePath": relative_path, "action": action, "content": str(item.get("content", "")), "target": target})
            if relative_path not in relative_paths:
                relative_paths.append(relative_path)

        checkpoint = checkpoints.create(context.conversation_id, str(root), f"补丁前：{reason}", relative_paths)
        applied: list[dict[str, str]] = []
        for change in changes:
            target = change["target"]
            if change["action"] == "delete":
                if target.exists():
                    target.unlink()
                applied.append({"relativePath": change["relativePath"], "action": "delete"})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(change["content"], encoding="utf-8")
            applied.append({"relativePath": change["relativePath"], "action": "write"})

        diff = _git_diff_summary(root)
        return {
            "ok": True,
            "summary": f"已应用 {len(applied)} 个文件变更，补丁前检查点为 {checkpoint['id']}。",
            "data": {"checkpoint": checkpoint, "applied": applied, "diff": diff, "reason": reason},
        }

    return _apply_patch


def create_code_tools(checkpoints: CheckpointManager) -> list[AgentTool]:
    return [
        AgentTool(
            "code.search_files",
            "代码搜索",
            "在当前对话沙盒仓库中搜索文件名和文本内容。",
            "read",
            _search_files,
            input_schema={"query": "string", "maxResults": "number"},
        ),
        AgentTool(
            "code.read_file",
            "读取文件",
            "读取当前对话沙盒仓库内的单个文本文件。",
            "read",
            _read_file,
            input_schema={"relativePath": "string", "maxBytes": "number"},
        ),
        AgentTool(
            "code.git_diff",
            "查看 Diff",
            "读取当前对话沙盒仓库的 git diff 摘要和文件列表。",
            "read",
            _git_diff,
        ),
        AgentTool(
            "code.write_file",
            "写入文件",
            "写入当前沙盒仓库内的文本文件；写入前自动创建 checkpoint。",
            "write",
            _write_file_factory(checkpoints),
            requires_checkpoint=True,
            input_schema={"relativePath": "string", "content": "string", "reason": "string"},
        ),
        AgentTool(
            "code.apply_patch",
            "应用多文件变更",
            "一次写入或删除多个沙盒文件；应用前为所有涉及文件创建同一个 checkpoint。",
            "write",
            _apply_patch_factory(checkpoints),
            requires_checkpoint=True,
            input_schema={
                "reason": "string",
                "changes": [{"relativePath": "string", "action": "write|delete", "content": "string"}],
            },
        ),
    ]
