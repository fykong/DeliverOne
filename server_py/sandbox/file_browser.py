from __future__ import annotations

import os
from pathlib import Path
from typing import Any

IGNORED_DIRS = {".git", "node_modules", "dist", "build", ".next", "coverage", "__pycache__", ".pytest_cache"}
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


class SandboxFileBrowser:
    def list_tree(self, repo_path: str, max_items: int = 1200) -> dict[str, Any]:
        root = Path(repo_path).resolve()
        if not root.exists() or not root.is_dir():
            raise RuntimeError("沙盒仓库路径不存在。")

        items: list[dict[str, Any]] = []
        for current_root, dirs, files in os.walk(root):
            current = Path(current_root)
            dirs[:] = sorted([name for name in dirs if name not in IGNORED_DIRS])
            relative_dir = current.relative_to(root)
            if str(relative_dir) != ".":
                items.append(self._item(root, current, "directory"))
            for name in sorted(files):
                if len(items) >= max_items:
                    break
                path = current / name
                items.append(self._item(root, path, "file"))
            if len(items) >= max_items:
                break

        return {"rootPath": str(root), "items": items[:max_items], "truncated": len(items) >= max_items}

    def read_file(self, repo_path: str, relative_path: str, max_bytes: int = 200_000) -> dict[str, Any]:
        root = Path(repo_path).resolve()
        target = self._resolve_inside(root, relative_path)
        if not target.exists() or not target.is_file():
            raise RuntimeError("文件不存在或不是普通文件。")
        if target.stat().st_size > max_bytes:
            content = target.read_bytes()[:max_bytes].decode("utf-8", errors="replace")
            truncated = True
        else:
            content = target.read_text(encoding="utf-8-sig", errors="replace")
            truncated = False
        return {
            "path": str(target.relative_to(root)).replace("\\", "/"),
            "name": target.name,
            "size": target.stat().st_size,
            "language": self._language_for(target),
            "content": content,
            "truncated": truncated,
        }

    def _item(self, root: Path, path: Path, item_type: str) -> dict[str, Any]:
        relative = path.relative_to(root)
        relative_text = str(relative).replace("\\", "/")
        depth = len(relative.parts) - 1
        return {
            "path": relative_text,
            "name": path.name,
            "type": item_type,
            "depth": depth,
            "size": path.stat().st_size if path.is_file() else 0,
            "isText": path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS,
        }

    def _resolve_inside(self, root: Path, relative_path: str) -> Path:
        if not relative_path.strip():
            raise RuntimeError("缺少文件路径。")
        target = (root / relative_path).resolve()
        if target != root and root not in target.parents:
            raise RuntimeError("文件路径超出当前沙盒仓库。")
        if any(part in IGNORED_DIRS for part in target.relative_to(root).parts):
            raise RuntimeError("该路径属于忽略目录，不能通过文件浏览器读取。")
        return target

    def _language_for(self, path: Path) -> str:
        suffix = path.suffix.lower()
        return {
            ".css": "css",
            ".html": "html",
            ".js": "javascript",
            ".json": "json",
            ".jsx": "jsx",
            ".md": "markdown",
            ".mjs": "javascript",
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".yml": "yaml",
            ".yaml": "yaml",
        }.get(suffix, "text")
