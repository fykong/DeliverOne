from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import WORKSPACE_ROOT
from server_py.memory.long_term_store import LongTermMemoryStore


# read-modify-write 串行化:FastAPI 线程池下同仓库并发写会丢数据。
_PATTERN_LOCK = threading.Lock()

PATTERN_LIMIT = 400


FAILURE_KEYWORDS: list[tuple[str, list[str], str]] = [
    ("dependency", ["module not found", "cannot find module", "npm err", "pnpm", "yarn", "package", "dependency", "依赖", "版本"], "先读取 package.json 和 lockfile，再决定安装、降级或替换依赖。"),
    ("typecheck", ["typecheck", "typescript", "tsc", "type error", "类型"], "先定位报错文件和类型定义，再做最小范围类型修复。"),
    ("lint", ["eslint", "lint", "prettier", "格式"], "先确认 lint 规则，再做格式或规则兼容修复。"),
    ("test", ["test failed", "expect(", "assert", "pytest", "vitest", "jest", "测试"], "先读失败用例和目标代码，再修业务行为或测试夹具。"),
    ("build", ["build failed", "vite", "webpack", "rollup", "next build", "构建"], "先复现构建命令，再根据编译链路修配置或源码。"),
    ("preview", ["preview", "localhost", "127.0.0.1", "iframe", "浏览器", "预览"], "先确认沙盒预览进程、端口和页面 HTTP 状态，再做前后端联调。"),
    ("mcp", ["mcp", "server", "stdio", "sse", "tool schema"], "先检查 MCP 配置、schema 和调用参数，再决定是否降级到内置工具。"),
    ("permission", ["approval", "permission", "denied", "unauthorized", "403", "授权", "审批"], "先确认审批范围和风险等级，再重新申请最小权限。"),
    ("rollback", ["rollback", "checkpoint", "restore", "回退"], "先确认 checkpoint 和 diff，再执行文件级或全仓回退。"),
]


SUCCESS_KEYWORDS: list[tuple[str, list[str], str]] = [
    ("delivery", ["delivery", "交付包", "patch", "diff", "completed"], "保留交付包、diff、验证命令和回退点，作为下一轮交付模板。"),
    ("verification", ["pass", "passed", "通过", "green", "ok"], "将通过的验证命令和上下文写入后续计划的默认验证链。"),
    ("preview", ["preview", "screenshot", "浏览器", "预览"], "保留可用端口、启动命令和浏览器检查方式。"),
]


class MemoryPatternStore:
    """Repository-scoped reusable success and failure patterns."""

    def __init__(self, path: Path | None = None, namespace_store: LongTermMemoryStore | None = None) -> None:
        self.path = path or WORKSPACE_ROOT / "memory" / "patterns.json"
        self.namespace_store = namespace_store or LongTermMemoryStore()

    def list(self, repository: dict[str, Any] | None = None, include_workspace: bool = True) -> list[dict[str, Any]]:
        items = read_json(self.path, [])
        if not isinstance(items, list):
            return []
        namespace = self.namespace_store.namespace_for(repository)
        allowed = {namespace}
        if include_workspace:
            allowed.add("workspace")
        return [
            item
            for item in items
            if isinstance(item, dict)
            and not item.get("forgotten")
            and str(item.get("namespace") or "workspace") in allowed
        ]

    def purge_conversation(self, conversation_id: str) -> int:
        """删除会话时清除以该会话为唯一来源的模式条目;
        多会话佐证的模式只摘掉该会话的 example,模式本身保留。"""
        with _PATTERN_LOCK:
            return self._purge_conversation_locked(conversation_id)

    def _purge_conversation_locked(self, conversation_id: str) -> int:
        items = read_json(self.path, [])
        if not isinstance(items, list):
            return 0
        kept: list[dict[str, Any]] = []
        removed = 0
        changed = False
        for item in items:
            if not isinstance(item, dict):
                continue
            before = item.get("examples") or []
            examples = [ex for ex in before if str(ex.get("conversationId") or "") != conversation_id]
            if len(examples) != len(before):
                changed = True
            if str(item.get("conversationId") or "") == conversation_id and not examples:
                removed += 1
                changed = True
                continue
            item["examples"] = examples
            kept.append(item)
        if changed:
            write_json(self.path, kept)
        return removed

    def upsert_from_entries(
        self,
        conversation_id: str,
        entries: list[dict[str, Any]],
        repository: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        with _PATTERN_LOCK:
            return self._upsert_from_entries_locked(conversation_id, entries, repository)

    def _upsert_from_entries_locked(
        self,
        conversation_id: str,
        entries: list[dict[str, Any]],
        repository: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        current = read_json(self.path, [])
        if not isinstance(current, list):
            current = []
        by_id = {str(item.get("id")): item for item in current if isinstance(item, dict) and item.get("id")}
        namespace = self.namespace_store.namespace_for(repository)
        repo_source = str((repository or {}).get("source") or "")
        now = now_iso()

        for entry in entries:
            pattern = self._pattern_from_entry(entry, namespace, repo_source, conversation_id, now)
            if not pattern:
                continue
            existing = by_id.get(pattern["id"], {})
            examples = [*(existing.get("examples") or [])]
            example = pattern["examples"][0]
            if example not in examples:
                examples.insert(0, example)
            merged = {
                **existing,
                **pattern,
                "firstSeenAt": existing.get("firstSeenAt") or now,
                "lastSeenAt": now,
                "hitCount": int(existing.get("hitCount") or 0) + 1,
                "examples": examples[:6],
                "forgotten": bool(existing.get("forgotten", False)),
            }
            merged["content"] = self._content(merged)
            by_id[pattern["id"]] = merged

        items = list(by_id.values())
        items.sort(key=lambda item: (float(item.get("importance") or 1), int(item.get("hitCount") or 0), str(item.get("lastSeenAt") or "")), reverse=True)
        write_json(self.path, items[:PATTERN_LIMIT])
        return self.list(repository)

    def _pattern_from_entry(
        self,
        entry: dict[str, Any],
        namespace: str,
        repo_source: str,
        conversation_id: str,
        created_at: str,
    ) -> dict[str, Any] | None:
        kind = str(entry.get("kind") or "")
        content = str(entry.get("content") or "")
        if not content.strip():
            return None

        if kind == "failure" or "failure" in {str(tag) for tag in entry.get("tags", [])}:
            outcome = "failure"
            category, action = self._classify(content, FAILURE_KEYWORDS, "unknown", "先补充上下文、复现失败，再生成最小修复计划。")
        elif kind in {"delivery", "preview"}:
            outcome = "success" if self._looks_successful(content) else "evidence"
            if outcome != "success":
                return None
            category, action = self._classify(content, SUCCESS_KEYWORDS, kind, "保留可复用证据，下一轮优先复用同类流程。")
        else:
            return None

        title = self._title(outcome, category)
        pattern_id = self._pattern_id(namespace, outcome, category)
        snippet = content.strip()[-900:]
        return {
            "id": pattern_id,
            "kind": "pattern",
            "namespace": namespace,
            "repoSource": repo_source,
            "conversationId": conversation_id,
            "outcome": outcome,
            "category": category,
            "title": title,
            "content": "",
            "recommendedAction": action,
            "sourcePath": entry.get("sourcePath"),
            "sourceEntryId": entry.get("id"),
            "tags": sorted({"pattern", outcome, category}),
            "scope": "repository" if repo_source else "workspace",
            "importance": 3.1 if outcome == "failure" else 2.3,
            "pinned": False,
            "createdAt": created_at,
            "examples": [snippet],
        }

    def _classify(
        self,
        text: str,
        rules: list[tuple[str, list[str], str]],
        default_category: str,
        default_action: str,
    ) -> tuple[str, str]:
        lowered = text.lower()
        for category, keywords, action in rules:
            if any(keyword.lower() in lowered for keyword in keywords):
                return category, action
        return default_category, default_action

    def _looks_successful(self, content: str) -> bool:
        lowered = content.lower()
        return any(token in lowered for token in ["pass", "passed", "ok", "completed", "通过", "完成", "成功", "交付包"])

    def _title(self, outcome: str, category: str) -> str:
        outcome_label = "失败修复策略" if outcome == "failure" else "成功交付模式"
        return f"{outcome_label}：{category}"

    def _content(self, item: dict[str, Any]) -> str:
        examples = item.get("examples") or []
        return "\n".join(
            [
                f"类别：{item.get('category')}",
                f"结果：{item.get('outcome')}",
                f"出现次数：{item.get('hitCount')}",
                f"建议动作：{item.get('recommendedAction')}",
                "最近证据：",
                str(examples[0] if examples else "")[:1000],
            ]
        )

    def _pattern_id(self, namespace: str, outcome: str, category: str) -> str:
        digest = hashlib.sha1(f"{namespace}\n{outcome}\n{category}".encode("utf-8", errors="ignore")).hexdigest()[:14]
        return f"pat_{digest}"
