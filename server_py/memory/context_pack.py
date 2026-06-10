from __future__ import annotations

from typing import Any

from server_py.core.json_io import now_iso


class ContextPackBuilder:
    def build(
        self,
        conversation_id: str,
        repository: dict[str, Any] | None,
        requirement: str | None,
        matched_skills: list[dict[str, Any]],
        memory_notes: dict[str, str] | None = None,
        recall_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        sections: list[dict[str, Any]] = []
        notes = memory_notes or {}
        recalled = recall_items or []

        if requirement and requirement.strip():
            sections.append({"id": "requirement", "title": "当前需求", "content": requirement.strip()})

        if repository:
            sections.append(
                {
                    "id": "repo-profile",
                    "title": "仓库画像",
                    "content": "\n".join(
                        [
                            f"来源：{repository.get('sourceType')}",
                            f"地址：{repository.get('source')}",
                            f"分支：{repository.get('branch') or '未知'}",
                            f"提交：{repository.get('head') or '未知'}",
                            f"包管理器：{repository.get('packageManager') or 'unknown'}",
                            f"可用脚本：{', '.join(repository.get('scripts', {}).keys()) or '未识别'}",
                        ]
                    ),
                }
            )

        if matched_skills:
            sections.append(
                {
                    "id": "matched-skills",
                    "title": "匹配 Skill",
                    "content": "\n".join(f"{skill['name']}：{skill['description']}" for skill in matched_skills),
                }
            )

        if recalled:
            instruction_items = [item for item in recalled if item.get("pinned") or "instructions" in item.get("tags", [])]
            durable_items = [item for item in recalled if item.get("scope") in {"workspace", "repository"} and item not in instruction_items]
            task_items = [item for item in recalled if item not in instruction_items and item not in durable_items]
            ordered = [*instruction_items, *durable_items, *task_items]
            sections.append(
                {
                    "id": "memory-recall",
                    "title": "相关记忆召回",
                    "content": "\n\n".join(
                        [
                            "\n".join(
                                [
                                    f"### {item.get('title')}",
                                    f"类型：{item.get('kind')}；范围：{item.get('scope', 'conversation')}；分数：{item.get('score')}",
                                    f"原因：{item.get('reason') or '综合相关'}",
                                    f"来源：{item.get('sourcePath')}",
                                    str(item.get("content") or ""),
                                ]
                            )
                            for item in ordered[:8]
                        ]
                    ),
                }
            )

        for key, title in [
            ("runtimeControl", "任务状态机人工控制"),
            ("decisions", "用户决策"),
            ("failures", "失败经验"),
            ("delivery", "交付记录"),
            ("preview", "预览验证"),
        ]:
            content = notes.get(key, "").strip()
            if content:
                sections.append({"id": key, "title": title, "content": content[-4000:]})

        return {
            "conversationId": conversation_id,
            "summary": "；".join(
                [
                    "已接入仓库上下文" if repository else "尚未接入仓库上下文",
                    "已记录当前需求" if requirement and requirement.strip() else "尚未记录当前需求",
                    f"匹配 {len(matched_skills)} 个 Skill",
                    f"召回 {len(recalled)} 条相关记忆",
                ]
            ),
            "sections": sections,
            "generatedAt": now_iso(),
        }
