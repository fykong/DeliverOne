from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from server_py.core.json_io import now_iso, read_json, write_json
from server_py.core.paths import conversation_root
from server_py.memory.context_pack import ContextPackBuilder
from server_py.memory.curator import MemoryCurator
from server_py.memory.long_term_store import LongTermMemoryStore
from server_py.memory.pattern_store import MemoryPatternStore
from server_py.memory.retrieval import MemoryRetriever
from server_py.memory.task_ledger import TaskLedgerService

IGNORED_DIRS = {".git", "node_modules", "dist", "build", ".next", "coverage", "__pycache__", ".venv"}
SOURCE_EXTENSIONS = {".css", ".html", ".js", ".jsx", ".md", ".mjs", ".py", ".ts", ".tsx", ".vue", ".json", ".yml", ".yaml"}
AGENT_DOC_NAMES = ("AGENTS.override.md", "AGENTS.md")


def slim_memory_for_model(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """把完整 memory snapshot 裁剪成喂模型用的精简视图。

    完整 snapshot(~13.8 万字符)里 longTerm/patterns/curatedMemory 的原始全量
    转储占 ~75%,而模型真正需要的是 recall(已检索排序的精华子集)+ contextPack
    (叙事)+ taskState/taskLedger(人工控制)。原始转储留给 UI 记忆面板和诊断,
    不进模型 prompt——直接把每次角色调用的 prompt 从 ~6 万 token 压到 ~1.5 万。
    """
    if not isinstance(snapshot, dict):
        return snapshot
    recall = snapshot.get("recall") if isinstance(snapshot.get("recall"), dict) else {}
    recall_items = recall.get("items") if isinstance(recall.get("items"), list) else []
    # 召回列表按多样性分组返回,并非分数序;给模型的 top10 必须按分数取,
    # 否则高分的"已交付方案"条目可能被截掉。
    ranked = sorted(
        (item for item in recall_items if isinstance(item, dict)),
        key=lambda item: float(item.get("score") or 0),
        reverse=True,
    )
    def _is_dead_end(item: dict[str, Any]) -> bool:
        text = f"{item.get('title') or ''}\n{item.get('content') or ''}"
        tags = {str(tag) for tag in (item.get("tags") or [])}
        return (
            item.get("kind") == "failure"
            or "do-not-repeat" in tags
            or "doNotRepeat" in str(item.get("sourcePath") or "")
            or "不存在" in text[:300]
            or "找不到" in text[:300]
        )

    # 失败经验/已证伪路径单独成区:混在普通召回里,模型会把
    # "ArticleCard 不存在"里的路径名当成候选去搜(阅读量任务实测翻车)。
    # 字段名即指令:这些是禁区,不是建议。
    dead_ends = [
        {"title": item.get("title"), "fact": str(item.get("content") or "")[:300]}
        for item in ranked
        if _is_dead_end(item)
    ][:6]
    slim_items = [
        {
            "title": item.get("title"),
            "kind": item.get("kind"),
            "content": str(item.get("content") or "")[:600],
            "scope": item.get("scope"),
            "reason": item.get("reason"),
            "score": item.get("score"),
        }
        for item in ranked[:10]
        if not _is_dead_end(item)
    ]
    ledger = snapshot.get("taskLedger") if isinstance(snapshot.get("taskLedger"), dict) else None
    slim_ledger = None
    if ledger:
        stages = ledger.get("stages") if isinstance(ledger.get("stages"), list) else []
        slim_ledger = {
            "status": ledger.get("status"),
            "stages": [
                {"id": s.get("id"), "title": s.get("title"), "status": s.get("status")}
                for s in stages
                if isinstance(s, dict)
            ],
        }
    return {
        "conversationId": snapshot.get("conversationId"),
        "repo": (snapshot.get("repo") or {}).get("summary") if isinstance(snapshot.get("repo"), dict) else None,
        "contextPack": snapshot.get("contextPack"),
        "recall": {"query": recall.get("query"), "items": slim_items},
        # 已证伪的死路:这些路径/做法已被真实执行证明不存在或失败,
        # 禁止再作为搜索词、读取目标或方案选项;只能作为排除项。
        "provenDeadEnds_doNotRetry": dead_ends or None,
        "taskState": snapshot.get("taskState"),
        "taskLedger": slim_ledger,
        "searchIntent": snapshot.get("searchIntent"),
    }


def _meaningful_markdown(text: str, ignored_lines: set[str]) -> str:
    lines = []
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned in ignored_lines or cleaned.startswith(("更新时间：", "时间：")):
            continue
        lines.append(cleaned)
    return "\n".join(lines).strip()


class MemoryService:
    def __init__(
        self,
        context_builder: ContextPackBuilder | None = None,
        retriever: MemoryRetriever | None = None,
        long_term_store: LongTermMemoryStore | None = None,
        pattern_store: MemoryPatternStore | None = None,
        curator: MemoryCurator | None = None,
        task_ledger: TaskLedgerService | None = None,
    ) -> None:
        self.context_builder = context_builder or ContextPackBuilder()
        self.retriever = retriever or MemoryRetriever()
        self.long_term_store = long_term_store or LongTermMemoryStore()
        self.pattern_store = pattern_store or MemoryPatternStore(namespace_store=self.long_term_store)
        self.curator = curator or MemoryCurator(namespace_store=self.long_term_store)
        self.task_ledger = task_ledger or TaskLedgerService()

    def _paths(self, conversation_id: str) -> dict[str, Path]:
        root = conversation_root(conversation_id) / "memory"
        return {
            "root": root,
            "repo": root / "repo",
            "conversation": root / "conversation",
            "delivery": root / "delivery",
            "skill": root / "skill",
            "repo_profile": root / "repo" / "repo-profile.json",
            "route_map": root / "repo" / "route-map.json",
            "package_scripts": root / "repo" / "package-scripts.json",
            "project_instructions": root / "repo" / "project-instructions.md",
            "memory_entries": root / "conversation" / "memory-entries.json",
            "recall_items": root / "conversation" / "recall-items.json",
            "recall_diagnostics": root / "conversation" / "recall-diagnostics.json",
            "search_intent": root / "conversation" / "search-intent.json",
            "task_ledger": root / "conversation" / "task-ledger.json",
            "task_state": conversation_root(conversation_id) / "runtime" / "task-state-machine.json",
            "requirement": root / "conversation" / "requirement.md",
            "decisions": root / "conversation" / "decisions.md",
            "failures": root / "conversation" / "failures.md",
            "agent_turns": root / "conversation" / "agent-turns.md",
            "checkpoints": root / "delivery" / "checkpoints.json",
            "verification_report": root / "delivery" / "verification-report.json",
            "delivery_summaries": root / "delivery" / "delivery-summaries.md",
            "preview_summaries": root / "delivery" / "preview-summaries.md",
            "matched_skills": root / "skill" / "matched-skills.json",
            "success_patterns": root / "skill" / "success-patterns.md",
            "rejected_patterns": root / "skill" / "rejected-patterns.md",
        }

    def _empty_snapshot(self, conversation_id: str) -> dict[str, Any]:
        return {
            "conversationId": conversation_id,
            "repo": {"summary": ["尚未接入仓库"]},
            "conversation": {"summary": ["尚未记录需求"]},
            "delivery": {"changedFiles": 0, "rollbackPointCount": 0},
            "skill": {"matchedSkillIds": []},
            "contextPack": {"sections": [], "summary": "尚未形成上下文。"},
            "searchIntent": {},
            "taskLedger": None,
            "taskState": None,
            "recall": {"query": "", "items": [], "entryCount": 0, "candidateCount": 0},
            "longTerm": {"count": 0, "namespace": "workspace", "items": []},
            "patterns": {"count": 0, "items": []},
            "curatedMemory": {"counts": {"total": 0}, "items": [], "namespace": "workspace"},
            "updatedAt": now_iso(),
        }

    def ensure_layout(self, conversation_id: str) -> dict[str, Path]:
        paths = self._paths(conversation_id)
        for key in ["repo", "conversation", "delivery", "skill"]:
            paths[key].mkdir(parents=True, exist_ok=True)
        defaults = {
            "route_map": '{"modules": []}\n',
            "package_scripts": "{}\n",
            "project_instructions": "# 项目说明\n\n",
            "memory_entries": "[]\n",
            "recall_items": "[]\n",
            "recall_diagnostics": "{}\n",
            "search_intent": "{}\n",
            "task_ledger": "{}\n",
            "requirement": "# 当前需求\n\n",
            "decisions": "# 用户确认与关键决策\n\n",
            "failures": "# 失败经验\n\n",
            "agent_turns": "# Agent 输出记录\n\n",
            "checkpoints": "[]\n",
            "verification_report": "{}\n",
            "delivery_summaries": "# 交付记录\n\n",
            "preview_summaries": "# 预览验证\n\n",
            "matched_skills": "[]\n",
            "success_patterns": "# 成功模式\n\n",
            "rejected_patterns": "# 失败和拒绝模式\n\n",
        }
        for key, content in defaults.items():
            if not paths[key].exists():
                paths[key].write_text(content, encoding="utf-8")
        return paths

    def record_requirement(self, conversation_id: str, requirement: str) -> None:
        paths = self.ensure_layout(conversation_id)
        paths["requirement"].write_text(
            "\n".join(["# 当前需求", "", f"更新时间：{now_iso()}", "", requirement.strip(), ""]),
            encoding="utf-8",
        )

    def capture_repository(self, conversation_id: str, repository: dict[str, Any] | None, sandbox: dict[str, Any] | None = None) -> None:
        if not repository:
            self.ensure_layout(conversation_id)
            return
        paths = self.ensure_layout(conversation_id)
        write_json(paths["repo_profile"], repository)
        write_json(paths["package_scripts"], repository.get("scripts", {}))
        route_map = self._build_route_map(repository, sandbox)
        write_json(paths["route_map"], route_map)
        paths["project_instructions"].write_text(self._collect_project_instructions(sandbox), encoding="utf-8")

    def record_matched_skills(self, conversation_id: str, matched_skills: list[dict[str, Any]]) -> None:
        paths = self.ensure_layout(conversation_id)
        write_json(paths["matched_skills"], matched_skills)

    def record_decision(self, conversation_id: str, title: str, detail: str) -> None:
        paths = self.ensure_layout(conversation_id)
        with paths["decisions"].open("a", encoding="utf-8") as file:
            file.write("\n".join([f"## {title}", "", f"时间：{now_iso()}", "", detail.strip(), ""]) + "\n")

    def record_failure(self, conversation_id: str, title: str, detail: str, source: str = "runtime") -> None:
        paths = self.ensure_layout(conversation_id)
        with paths["failures"].open("a", encoding="utf-8") as file:
            file.write(
                "\n".join(
                    [
                        f"## {title}",
                        "",
                        f"时间：{now_iso()}",
                        f"来源：{source}",
                        "",
                        detail.strip(),
                        "",
                    ]
                )
                + "\n"
            )

    def record_solution(
        self,
        conversation_id: str,
        repository: dict[str, Any] | None,
        requirement: str,
        changed_files: list[str],
        verification: str,
        branch: str | None = None,
        commit_sha: str | None = None,
    ) -> None:
        """把已验证的交付方案沉淀为长期记忆。

        锚点：历史需求结构化沉淀,相似新需求自动召回旧方案。条目按仓库
        命名空间存储、高重要度,跨会话 recall 时与新需求做相似度匹配。
        """
        cleaned = (requirement or "").strip()
        if not cleaned:
            return
        title = f"已交付方案：{cleaned.splitlines()[0][:80]}"
        lines = [
            f"需求：{cleaned[:600]}",
            f"改动文件：{', '.join(changed_files[:12]) or '（见交付包）'}",
            f"验证：{verification}",
        ]
        if branch:
            lines.append(f"提测分支：{branch}（{(commit_sha or '')[:12]}）")
        try:
            self.long_term_store.upsert_manual(
                conversation_id=conversation_id,
                repository=repository,
                title=title,
                content="\n".join(lines),
                kind="delivery",
                tags=["solution", "delivered"],
                importance=4.2,
            )
        except Exception:
            # 记忆沉淀失败不阻断交付链路
            pass

    def record_delivery_report(self, conversation_id: str, report: dict[str, Any]) -> None:
        paths = self.ensure_layout(conversation_id)
        changed = report.get("changedFiles", [])
        with paths["delivery_summaries"].open("a", encoding="utf-8") as file:
            file.write(
                "\n".join(
                    [
                        f"## 交付包 {report.get('id')}",
                        "",
                        f"时间：{report.get('generatedAt') or now_iso()}",
                        f"变更文件数：{len(changed) if isinstance(changed, list) else 0}",
                        f"报告：{report.get('artifacts', {}).get('markdownPath')}",
                        f"Patch：{report.get('artifacts', {}).get('patchPath')}",
                        "",
                    ]
                )
                + "\n"
            )

    def record_preview_smoke(self, conversation_id: str, report: dict[str, Any]) -> None:
        paths = self.ensure_layout(conversation_id)
        with paths["preview_summaries"].open("a", encoding="utf-8") as file:
            file.write(
                "\n".join(
                    [
                        f"## 预览验证 {report.get('url')}",
                        "",
                        f"时间：{report.get('generatedAt') or now_iso()}",
                        f"结果：{'通过' if report.get('ok') else '未通过'}",
                        f"HTTP：{report.get('httpStatus')}",
                        f"标题：{report.get('htmlTitle') or '未识别'}",
                        f"截图：{(report.get('screenshot') or {}).get('path')}",
                        "",
                    ]
                )
                + "\n"
            )

    def record_agent_turn(self, conversation_id: str, turn: dict[str, Any]) -> None:
        paths = self.ensure_layout(conversation_id)
        audits = ", ".join(audit.get("verdict", "unknown") for audit in turn.get("audits", [])) or "无"
        with paths["agent_turns"].open("a", encoding="utf-8") as file:
            file.write(
                "\n".join(
                    [
                        f"## {turn.get('phase')}",
                        "",
                        f"时间：{turn.get('createdAt')}",
                        f"模型：{turn.get('model', {}).get('displayName')}",
                        f"审计：{audits}",
                        "",
                        str(turn.get("reply", "")).strip(),
                        "",
                    ]
                )
            )

    def snapshot(
        self,
        conversation_id: str,
        repository: dict[str, Any] | None = None,
        requirement: str | None = None,
        matched_skills: list[dict[str, Any]] | None = None,
        search_intent: dict[str, Any] | None = None,
        sandbox: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 只读快照:会话还没有任何记忆且本次不带需求/仓库时,不创建目录树,
        # 避免"打开页面什么都没做就多出一堆空壳 conv_xxx 目录"的孤儿污染。
        memory_root = conversation_root(conversation_id) / "memory"
        if not memory_root.exists() and not requirement and not repository and not matched_skills:
            return self._empty_snapshot(conversation_id)
        paths = self.ensure_layout(conversation_id)
        repo = repository or read_json(paths["repo_profile"], None)
        skills = matched_skills if matched_skills is not None else read_json(paths["matched_skills"], [])
        requirement_text = _meaningful_markdown(requirement or paths["requirement"].read_text(encoding="utf-8"), {"# 当前需求"})
        decisions_text = _meaningful_markdown(paths["decisions"].read_text(encoding="utf-8"), {"# 用户确认与关键决策"})
        failures_text = _meaningful_markdown(paths["failures"].read_text(encoding="utf-8"), {"# 失败经验"})
        turns_text = _meaningful_markdown(paths["agent_turns"].read_text(encoding="utf-8"), {"# Agent 输出记录"})
        delivery_text = _meaningful_markdown(paths["delivery_summaries"].read_text(encoding="utf-8"), {"# 交付记录"})
        preview_text = _meaningful_markdown(paths["preview_summaries"].read_text(encoding="utf-8"), {"# 预览验证"})
        task_state = read_json(paths["task_state"], {}) or {}
        task_state_summary = self._task_state_summary(task_state)
        runtime_control_text = self._runtime_control_text(task_state_summary)
        entries = self._build_entries(
            paths,
            repo,
            requirement_text,
            decisions_text,
            failures_text,
            turns_text,
            delivery_text,
            preview_text,
            runtime_control_text,
            skills,
        )
        write_json(paths["memory_entries"], entries)
        long_term_entries = self.long_term_store.upsert_from_entries(conversation_id, entries, repo)
        pattern_entries = self.pattern_store.upsert_from_entries(conversation_id, entries, repo)
        curated_memory = self.curator.curate(conversation_id, entries, pattern_entries, repo)
        curated_entries = self.curator.entries_for(repo)
        active_search_intent = search_intent or read_json(paths["search_intent"], {})
        if active_search_intent:
            write_json(paths["search_intent"], active_search_intent)
            entries.append(self._search_intent_entry(active_search_intent, paths["search_intent"]))
        recall_query = self._recall_query(requirement_text or requirement or "", active_search_intent)
        recall_result = self.retriever.recall([*entries, *long_term_entries, *pattern_entries, *curated_entries], recall_query, limit=12)
        recall_items = recall_result["items"]
        checkpoints = read_json(paths["checkpoints"], [])
        verification_report = read_json(paths["verification_report"], {})
        task_signals = {
            "hasAgentTurn": bool(turns_text),
            "hasDelivery": bool(delivery_text),
            "hasPreview": bool(preview_text),
            "checkpointCount": len(checkpoints) if isinstance(checkpoints, list) else 0,
            "hasVerification": bool(verification_report and verification_report.get("status")),
            "hasFailures": bool(failures_text),
            "pausedStageCount": len(task_state_summary.get("control", {}).get("pausedStageIds", [])),
            "hasManualNextActions": bool(task_state_summary.get("control", {}).get("manualNextActionIds")),
        }
        task_ledger = self.task_ledger.update(
            paths["task_ledger"],
            conversation_id,
            requirement_text or requirement or "",
            repo,
            sandbox,
            active_search_intent,
            recall_items,
            skills,
            task_signals,
        )
        self.long_term_store.mark_used([item["id"] for item in recall_items if str(item.get("id", "")).startswith("lt_")])
        write_json(paths["recall_items"], recall_items)
        write_json(
            paths["recall_diagnostics"],
            {
                **recall_result,
                "items": [
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "score": item.get("score"),
                        "scope": item.get("scope"),
                        "reason": item.get("reason"),
                        "matchSignals": item.get("matchSignals"),
                    }
                    for item in recall_items
                ],
                "longTermPath": str(self.long_term_store.path),
                "longTermCount": len(long_term_entries),
                "patternPath": str(self.pattern_store.path),
                "patternCount": len(pattern_entries),
                "curatedCount": len(curated_entries),
                "curatedMemoryPath": curated_memory.get("repoMemoryPath"),
                "searchIntentPath": str(paths["search_intent"]),
                "taskLedgerPath": str(paths["task_ledger"]),
            },
        )

        context_pack = self.context_builder.build(
            conversation_id,
            repo,
            requirement_text,
            skills,
            {
                "decisions": decisions_text,
                "failures": failures_text,
                "delivery": delivery_text,
                "preview": preview_text,
                "runtimeControl": runtime_control_text,
            },
            recall_items=recall_items,
        )

        return {
            "conversationId": conversation_id,
            "rootPath": str(paths["root"]),
            "repo": {
                "profilePath": str(paths["repo_profile"]),
                "routeMapPath": str(paths["route_map"]),
                "packageScriptsPath": str(paths["package_scripts"]),
                "projectInstructionsPath": str(paths["project_instructions"]),
                "summary": (
                    [f"仓库：{repo.get('source')}", f"分支：{repo.get('branch') or '未知'}", f"脚本数：{len(repo.get('scripts', {}))}"]
                    if repo
                    else ["尚未接入仓库"]
                ),
            },
            "conversation": {
                "requirementPath": str(paths["requirement"]),
                "decisionsPath": str(paths["decisions"]),
                "failuresPath": str(paths["failures"]),
                "agentTurnsPath": str(paths["agent_turns"]),
                "memoryEntriesPath": str(paths["memory_entries"]),
                "recallItemsPath": str(paths["recall_items"]),
                "recallDiagnosticsPath": str(paths["recall_diagnostics"]),
                "searchIntentPath": str(paths["search_intent"]),
                "taskLedgerPath": str(paths["task_ledger"]),
                "summary": [
                    "已记录需求" if requirement_text else "尚未记录需求",
                    "已有用户决策记录" if decisions_text else "尚无用户决策记录",
                    "已有失败经验记录" if failures_text else "尚无失败经验记录",
                    "已有 Agent 输出记录" if turns_text else "尚无 Agent 输出记录",
                ],
            },
            "delivery": {
                "checkpointsPath": str(paths["checkpoints"]),
                "verificationReportPath": str(paths["verification_report"]),
                "deliverySummariesPath": str(paths["delivery_summaries"]),
                "previewSummariesPath": str(paths["preview_summaries"]),
                "changedFiles": 0,
                "rollbackPointCount": 0,
            },
            "skill": {
                "matchedSkillIds": [skill["id"] for skill in skills],
                "successPatternsPath": str(paths["success_patterns"]),
                "rejectedPatternsPath": str(paths["rejected_patterns"]),
            },
            "contextPack": context_pack,
            "searchIntent": active_search_intent,
            "taskLedger": task_ledger,
            "taskState": task_state_summary,
            "recall": {
                "query": recall_query,
                "items": recall_items,
                "entryCount": len(entries),
                "candidateCount": recall_result.get("candidateCount", len(entries) + len(long_term_entries) + len(pattern_entries) + len(curated_entries)),
                "longTermCount": len(long_term_entries),
                "patternCount": len(pattern_entries),
                "curatedCount": len(curated_entries),
                "strategy": recall_result.get("strategy"),
                "path": str(paths["recall_items"]),
                "diagnosticsPath": str(paths["recall_diagnostics"]),
                "longTermPath": str(self.long_term_store.path),
            },
            "longTerm": {
                "namespace": self.long_term_store.namespace_for(repo),
                "path": str(self.long_term_store.path),
                "count": len(long_term_entries),
                "items": [self._long_term_snapshot_item(item) for item in long_term_entries[:80]],
            },
            "patterns": {
                "count": len(pattern_entries),
                "path": str(self.pattern_store.path),
                "items": pattern_entries[:20],
            },
            "curatedMemory": curated_memory,
            "updatedAt": now_iso(),
        }

    def _recall_query(self, requirement: str, search_intent: dict[str, Any] | None) -> str:
        parts = [requirement]
        if isinstance(search_intent, dict):
            summary = str(search_intent.get("summary") or "")
            if summary:
                parts.append(summary)
            for key in ["searchQueries", "fileHints", "memoryQueries", "businessEntities", "riskHints", "verificationHints"]:
                values = search_intent.get(key)
                if isinstance(values, list):
                    parts.extend(str(value) for value in values if str(value).strip())
        return "\n".join(part for part in parts if part)

    def _search_intent_entry(self, search_intent: dict[str, Any], source_path: Path) -> dict[str, Any]:
        content = "\n".join(
            [
                f"summary: {search_intent.get('summary') or ''}",
                self._intent_line(search_intent, "searchQueries"),
                self._intent_line(search_intent, "fileHints"),
                self._intent_line(search_intent, "memoryQueries"),
                self._intent_line(search_intent, "riskHints"),
                self._intent_line(search_intent, "verificationHints"),
            ]
        )
        digest = hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return {
            "id": f"intent_{digest}",
            "kind": "search_intent",
            "title": "搜索意图",
            "content": content,
            "sourcePath": str(source_path),
            "tags": ["search-intent", "intent", str(search_intent.get("source") or "rules")],
            "weight": 1.4,
            "importance": 2.4,
            "scope": "conversation",
            "pinned": False,
            "createdAt": now_iso(),
        }

    def _intent_line(self, search_intent: dict[str, Any], key: str) -> str:
        values = search_intent.get(key)
        if not isinstance(values, list):
            return f"{key}: "
        return f"{key}: {', '.join(str(item) for item in values[:12])}"

    def _long_term_snapshot_item(self, item: dict[str, Any]) -> dict[str, Any]:
        importance = float(item.get("importance") or 1.0)
        return {
            "id": item.get("id"),
            "kind": item.get("kind") or "memory",
            "title": item.get("title") or "长期记忆",
            "content": str(item.get("content") or ""),
            "score": importance,
            "sourcePath": item.get("sourcePath") or str(self.long_term_store.path),
            "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
            "createdAt": item.get("firstSeenAt") or item.get("createdAt"),
            "scope": item.get("scope") or "repository",
            "importance": importance,
            "pinned": bool(item.get("pinned")),
            "reason": "长期记忆库",
            "namespace": item.get("namespace"),
            "manual": bool(item.get("manual")),
            "updatedAt": item.get("updatedAt") or item.get("lastSeenAt"),
            "sourcePhase": item.get("sourcePhase") or self._source_phase_from_item(item),
            "sourceConversationId": item.get("conversationId"),
            "sourceEntryId": item.get("sourceEntryId"),
            "lastPatch": item.get("lastPatch") if isinstance(item.get("lastPatch"), dict) else None,
            "patchHistory": item.get("patchHistory", [])[-12:] if isinstance(item.get("patchHistory"), list) else [],
        }

    def _source_phase_from_item(self, item: dict[str, Any]) -> str:
        kind = str(item.get("kind") or "")
        tags = {str(tag) for tag in item.get("tags", [])} if isinstance(item.get("tags"), list) else set()
        if "model-memory-patch" in tags:
            return "模型记忆草案"
        if "memory-patch" in tags:
            return "记忆整理"
        if "runtime" in tags or "task-state" in tags:
            return "任务状态机"
        if "repair" in tags or kind == "failure":
            return "验证与修复"
        if kind == "preview":
            return "预览验证"
        if kind == "delivery":
            return "交付"
        if kind == "skill":
            return "Skill 路由"
        if kind == "repo":
            return "仓库画像"
        if item.get("manual"):
            return "用户手动维护"
        if kind == "decision":
            return "用户决策"
        return "上下文召回"

    def _build_route_map(self, repository: dict[str, Any], sandbox: dict[str, Any] | None) -> dict[str, Any]:
        repo_path = Path(str((sandbox or {}).get("repoPath") or ""))
        modules: list[dict[str, Any]] = []
        key_files: list[str] = []
        if repo_path.exists() and repo_path.is_dir():
            for item in sorted(repo_path.iterdir(), key=lambda path: path.name.lower()):
                if item.name in IGNORED_DIRS or item.name.startswith("."):
                    continue
                if item.is_dir():
                    files = self._count_source_files(item, repo_path)
                    modules.append({"path": item.name, "kind": "directory", "sourceFiles": files})
                elif item.is_file() and item.suffix.lower() in SOURCE_EXTENSIONS:
                    key_files.append(item.name)

        return {
            "source": repository.get("source"),
            "branch": repository.get("branch"),
            "head": repository.get("head"),
            "packageManager": repository.get("packageManager"),
            "modules": modules[:40],
            "keyFiles": key_files[:40],
            "note": "按沙盒根目录扫描生成的仓库画像，用于下一轮上下文召回。",
            "updatedAt": now_iso(),
        }

    def _count_source_files(self, root: Path, repo_root: Path) -> int:
        count = 0
        for current, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in IGNORED_DIRS and not name.startswith(".")]
            current_path = Path(current)
            try:
                if any(part in IGNORED_DIRS for part in current_path.relative_to(repo_root).parts):
                    continue
            except ValueError:
                continue
            for file_name in files:
                if Path(file_name).suffix.lower() not in SOURCE_EXTENSIONS:
                    continue
                count += 1
                if count >= 500:
                    return count
        return count

    def _collect_project_instructions(self, sandbox: dict[str, Any] | None) -> str:
        repo_path = Path(str((sandbox or {}).get("repoPath") or ""))
        lines = ["# 项目说明", ""]
        if not repo_path.exists() or not repo_path.is_dir():
            return "\n".join([*lines, "尚未发现沙盒仓库。", ""])

        found: list[Path] = []
        for current, dirs, files in os.walk(repo_path):
            dirs[:] = [name for name in dirs if name not in IGNORED_DIRS and not name.startswith(".")]
            current_path = Path(current)
            for name in AGENT_DOC_NAMES:
                if name in files:
                    found.append(current_path / name)
                    if len(found) >= 8:
                        break
            if len(found) >= 8:
                break

        if not found:
            return "\n".join([*lines, "未发现 AGENTS.md 或 AGENTS.override.md。", ""])

        for file_path in found[:8]:
            relative = file_path.relative_to(repo_path)
            content = file_path.read_text(encoding="utf-8", errors="replace")[:8000]
            lines.extend([f"## {relative}", "", content.strip(), "", "---", ""])
        return "\n".join(lines)

    def _build_entries(
        self,
        paths: dict[str, Path],
        repo: dict[str, Any] | None,
        requirement_text: str,
        decisions_text: str,
        failures_text: str,
        turns_text: str,
        delivery_text: str,
        preview_text: str,
        runtime_control_text: str,
        skills: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        route_map = read_json(paths["route_map"], {})
        project_instructions = _meaningful_markdown(paths["project_instructions"].read_text(encoding="utf-8"), {"# 项目说明"})
        entries: list[dict[str, Any]] = []

        def add(kind: str, title: str, content: str, source_path: Path, tags: list[str] | None = None, weight: float = 1.0) -> None:
            text = content.strip()
            if not text:
                return
            tag_set = set(tags or [])
            importance = self._importance(kind, tag_set, weight)
            entries.append(
                {
                    "id": self._entry_id(kind, title, text),
                    "kind": kind,
                    "title": title,
                    "content": text[-5000:],
                    "sourcePath": str(source_path),
                    "tags": sorted(tag_set),
                    "weight": weight,
                    "importance": importance,
                    "scope": "conversation",
                    "pinned": "instructions" in tag_set,
                    "createdAt": now_iso(),
                }
            )

        if repo:
            add("repo", "仓库画像", "\n".join((repo.get("source") or "", f"分支：{repo.get('branch') or '未知'}", f"脚本：{', '.join((repo.get('scripts') or {}).keys())}")), paths["repo_profile"], ["repo"], 1.2)
        add("repo", "模块地图", self._route_map_text(route_map), paths["route_map"], ["repo", "route-map"], 1.1)
        add("repo", "项目说明", project_instructions, paths["project_instructions"], ["repo", "instructions", "AGENTS.md"], 1.4)
        add("requirement", "当前需求", requirement_text, paths["requirement"], ["requirement"], 1.5)
        add("decision", "用户决策", decisions_text, paths["decisions"], ["decision"], 1.1)
        add("failure", "失败经验", failures_text, paths["failures"], ["failure", "repair"], 1.3)
        add("agent", "Agent 输出记录", turns_text, paths["agent_turns"], ["agent"], 0.8)
        add("delivery", "交付记录", delivery_text, paths["delivery_summaries"], ["delivery"], 1.0)
        add("preview", "预览验证", preview_text, paths["preview_summaries"], ["preview"], 1.0)
        add("runtime_control", "任务状态机人工控制", runtime_control_text, paths["task_state"], ["runtime", "task-state", "user-control"], 1.6)
        if skills:
            add(
                "skill",
                "命中 Skills",
                "\n".join(f"{skill.get('id')}：{skill.get('name')} - {skill.get('description')}" for skill in skills),
                paths["matched_skills"],
                ["skill"],
                1.2,
            )
        return entries

    def _route_map_text(self, route_map: dict[str, Any]) -> str:
        modules = route_map.get("modules") if isinstance(route_map.get("modules"), list) else []
        key_files = route_map.get("keyFiles") if isinstance(route_map.get("keyFiles"), list) else []
        lines = [
            f"来源：{route_map.get('source') or '未知'}",
            f"包管理器：{route_map.get('packageManager') or 'unknown'}",
            "模块：",
            *[f"- {item.get('path')}：{item.get('sourceFiles')} 个源码文件" for item in modules[:30] if isinstance(item, dict)],
            "关键文件：",
            *[f"- {item}" for item in key_files[:30]],
        ]
        return "\n".join(lines)

    def _importance(self, kind: str, tags: set[str], weight: float) -> float:
        base = {
            "repo": 2.2,
            "requirement": 1.8,
            "decision": 2.7,
            "failure": 2.9,
            "agent": 1.1,
            "delivery": 2.0,
            "preview": 1.8,
            "skill": 2.0,
            "runtime_control": 3.2,
        }.get(kind, 1.0)
        if "instructions" in tags:
            base += 1.1
        if "repair" in tags or "failure" in tags:
            base += 0.5
        if "rollback" in tags or "checkpoint" in tags:
            base += 0.4
        return round(min(base + max(weight - 1.0, 0.0) * 0.4, 5.0), 3)

    def _entry_id(self, kind: str, title: str, content: str) -> str:
        digest = hashlib.sha1(f"{kind}\n{title}\n{content[:1000]}".encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"mem_{digest}"

    def _task_state_summary(self, task_state: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(task_state, dict) or not task_state:
            return {}
        controls = task_state.get("stageControls") if isinstance(task_state.get("stageControls"), dict) else {}
        override = task_state.get("nextActionOverride") if isinstance(task_state.get("nextActionOverride"), dict) else None
        paused = sorted(stage_id for stage_id, control in controls.items() if isinstance(control, dict) and control.get("paused"))
        annotated = sorted(stage_id for stage_id, control in controls.items() if isinstance(control, dict) and control.get("note"))
        return {
            "status": task_state.get("status"),
            "activeStage": task_state.get("activeStage"),
            "summary": task_state.get("summary"),
            "path": task_state.get("path"),
            "control": {
                "pausedStageIds": paused,
                "annotatedStageIds": annotated,
                "manualNextActionIds": override.get("actionIds", []) if isinstance(override, dict) else [],
                "manualNextActionNote": override.get("note") if isinstance(override, dict) else None,
                "editCount": len(task_state.get("editHistory", [])) if isinstance(task_state.get("editHistory"), list) else 0,
            },
            "blockers": task_state.get("blockers", []) if isinstance(task_state.get("blockers"), list) else [],
            "nextActions": task_state.get("nextActions", []) if isinstance(task_state.get("nextActions"), list) else [],
            "updatedAt": task_state.get("updatedAt"),
        }

    def _runtime_control_text(self, task_state_summary: dict[str, Any]) -> str:
        if not task_state_summary:
            return ""
        control = task_state_summary.get("control") if isinstance(task_state_summary.get("control"), dict) else {}
        lines = [
            f"状态：{task_state_summary.get('status') or 'unknown'}",
            f"当前阶段：{task_state_summary.get('activeStage') or 'unknown'}",
            f"摘要：{task_state_summary.get('summary') or '无'}",
        ]
        paused = control.get("pausedStageIds") if isinstance(control.get("pausedStageIds"), list) else []
        if paused:
            lines.append(f"用户暂停阶段：{', '.join(str(item) for item in paused)}")
        manual_actions = control.get("manualNextActionIds") if isinstance(control.get("manualNextActionIds"), list) else []
        if manual_actions:
            lines.append(f"用户覆盖下一步动作：{', '.join(str(item) for item in manual_actions)}")
            if control.get("manualNextActionNote"):
                lines.append(f"覆盖原因：{control.get('manualNextActionNote')}")
        blockers = task_state_summary.get("blockers") if isinstance(task_state_summary.get("blockers"), list) else []
        if blockers:
            lines.append("阻断原因：")
            lines.extend(f"- {item}" for item in blockers[:8])
        next_actions = task_state_summary.get("nextActions") if isinstance(task_state_summary.get("nextActions"), list) else []
        if next_actions:
            lines.append("当前允许下一步：")
            for action in next_actions[:8]:
                if isinstance(action, dict):
                    lines.append(f"- {action.get('id')}：{action.get('label') or action.get('id')}")
        if task_state_summary.get("path"):
            lines.append(f"状态机文件：{task_state_summary.get('path')}")
        return "\n".join(lines)
