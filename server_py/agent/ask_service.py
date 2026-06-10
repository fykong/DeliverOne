from __future__ import annotations

from typing import Any

from server_py.conversations.store import ConversationStore
from server_py.models.ark_client import ArkClient
from server_py.models.model_config import ModelConfigService
from server_py.observability.metrics import MetricStore
from server_py.sandbox.diff_service import SandboxDiffService


class AskService:
    """对话/问答模式:用户问项目或改动情况时,基于当前会话真实上下文直接回答,
    不进入澄清→方案→交付管道。

    这是产品的"自然对话"能力:PM 可以问"你是谁/能做什么/这次改了哪些文件/
    解释一下当前方案",得到接地气的回答,而不是被强行当成新需求来澄清。
    """

    def __init__(
        self,
        client: ArkClient,
        models: ModelConfigService,
        conversations: ConversationStore,
        diff: SandboxDiffService,
        metrics: MetricStore,
        tool_call_plans: Any | None = None,
    ) -> None:
        self.client = client
        self.models = models
        self.conversations = conversations
        self.diff = diff
        self.metrics = metrics
        self.tool_call_plans = tool_call_plans

    # 滚动摘要参数:窗口外未摘要的消息攒到该条数才触发一次压缩调用。
    SUMMARY_TRIGGER = 14
    RECENT_WINDOW = 8

    def answer(self, conversation_id: str, question: str) -> dict[str, Any]:
        question = (question or "").strip()
        if not question:
            raise RuntimeError("问题不能为空。")
        model = self.models.get_default_model()
        if model.get("enabled"):
            # 先把窗口外的旧消息压成滚动摘要(到阈值才真正调模型),
            # 再构建上下文——本次回答就能用上刚更新的摘要。
            try:
                self._maybe_update_rolling_summary(conversation_id, model)
            except Exception:
                pass  # 摘要失败不影响回答本身
        context = self._build_context(conversation_id)
        if not model.get("enabled"):
            # 模型不可用时给确定性兜底回答,不让对话直接报错。
            return {
                "reply": self._fallback_answer(question, context, model),
                "modelSource": "rules",
                "context": context,
            }
        try:
            reply = self.client.complete(model, self._messages(question, context))
            self.metrics.record_model_call(conversation_id, "ask", model, self.client.last_metrics)
            return {"reply": reply, "modelSource": "model", "context": context}
        except Exception as error:
            return {
                "reply": f"对话回答失败：{error}",
                "modelSource": "rules",
                "context": context,
            }

    def _maybe_update_rolling_summary(self, conversation_id: str, model: dict[str, Any]) -> None:
        """对话连续性(Claude Code compaction 的等价物):

        最近 RECENT_WINDOW 条消息原文进上下文;更早的消息不是丢弃,而是
        增量压缩成一段事实摘要存在会话状态里。摘要+近窗一起喂模型,
        长对话里"第 9 条之前说过的事"不再失忆,token 仍然有界。
        """
        state = self.conversations.get(conversation_id)
        messages = state.get("messages") if isinstance(state.get("messages"), list) else []
        summary = state.get("chatSummary") if isinstance(state.get("chatSummary"), dict) else {}
        up_to = int(summary.get("upToIndex") or 0)
        cutoff = len(messages) - self.RECENT_WINDOW
        if cutoff - up_to < self.SUMMARY_TRIGGER:
            return
        chunk = [
            f"[{item.get('role')}] {str(item.get('content') or '')[:500]}"
            for item in messages[up_to:cutoff]
            if isinstance(item, dict)
        ]
        if not chunk:
            return
        prompt = [
            {
                "role": "system",
                "content": "你是会话压缩器。把下面的旧对话压缩成不超过 300 字的事实摘要,只保留:用户的需求和决定、改动过的文件、执行/验证结论、未解决的问题。用中文,不要评论,不要客套。已有摘要时把新内容合并进去输出完整新摘要。",
            },
            {
                "role": "user",
                "content": "\n".join(
                    ([f"已有摘要：{summary.get('content')}"] if summary.get("content") else []) + ["新增旧消息：", *chunk]
                ),
            },
        ]
        new_summary = self.client.complete(model, prompt).strip()[:1500]
        self.metrics.record_model_call(conversation_id, "ask_summary", model, self.client.last_metrics)
        state["chatSummary"] = {"content": new_summary, "upToIndex": cutoff}
        self.conversations.save(state)

    def _build_context(self, conversation_id: str) -> dict[str, Any]:
        state = self.conversations.get(conversation_id)
        repository = state.get("repository") if isinstance(state.get("repository"), dict) else None
        sandbox = state.get("sandbox") if isinstance(state.get("sandbox"), dict) else None
        messages = state.get("messages") if isinstance(state.get("messages"), list) else []
        recent = [
            {"role": item.get("role"), "content": str(item.get("content") or "")[:600]}
            for item in messages[-self.RECENT_WINDOW :]
            if isinstance(item, dict)
        ]
        chat_summary = state.get("chatSummary") if isinstance(state.get("chatSummary"), dict) else {}
        plan = self.tool_call_plans.get_plan(conversation_id) if self.tool_call_plans else None
        plan_summary = None
        if isinstance(plan, dict):
            plan_summary = {
                "status": plan.get("status"),
                "requirement": str(plan.get("requirement") or "")[:300],
                "steps": [
                    {"toolId": step.get("toolId"), "title": step.get("title"), "status": step.get("status")}
                    for step in plan.get("steps", [])
                    if isinstance(step, dict)
                ],
            }
        changed_files: list[str] = []
        if sandbox and sandbox.get("repoPath"):
            try:
                current = self.diff.current(conversation_id, sandbox["repoPath"])
                changed_files = [
                    str(item.get("path"))
                    for item in current.get("files", [])
                    if isinstance(item, dict) and item.get("path")
                ][:20]
            except Exception:
                changed_files = []
        return {
            "phase": state.get("phase"),
            "repository": {
                "source": repository.get("source") if repository else None,
                "branch": repository.get("branch") if repository else None,
                "hasSandbox": bool(sandbox),
            },
            "earlierConversationSummary": chat_summary.get("content") or None,
            "recentMessages": recent,
            "currentPlan": plan_summary,
            "changedFiles": changed_files,
        }

    def _messages(self, question: str, context: dict[str, Any]) -> list[dict[str, str]]:
        import json

        return [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "你是 DeliverOne 平台的 AI 交付助手,正在以对话模式回答产品经理(PM)的问题。",
                        "DeliverOne 能把 PM 的自然语言需求端到端交付到全栈项目:澄清→方案→定位→改代码→测试→提测 PR,各阶段可人工介入,也支持托管模式一键直达提测。",
                        "请用中文、简洁、口语化地回答,像一个耐心的工程搭档。",
                        "回答要基于下面提供的真实会话上下文(仓库、最近对话、当前方案、已改动文件);上下文里没有的不要编造。",
                        "如果用户其实是想让你开发某个功能(而不是单纯提问),提醒他在输入框直接描述需求并点『发送给 Agent』进入开发流程。",
                        "不要输出 JSON,直接说人话。",
                    ]
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"question": question, "conversationContext": context},
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]

    def _fallback_answer(self, question: str, context: dict[str, Any], model: dict[str, Any]) -> str:
        lines = [
            "当前模型未接通，先用本地信息回答你：",
            f"- 模型状态：{model.get('unavailableReason') or '不可用'}",
            f"- 当前阶段：{context.get('phase')}",
        ]
        repo = context.get("repository") or {}
        if repo.get("source"):
            lines.append(f"- 已接入仓库：{repo.get('source')}（沙盒：{'已创建' if repo.get('hasSandbox') else '未创建'}）")
        else:
            lines.append("- 还没有接入仓库。可在左侧接入本地仓库或 GitHub 仓库后再开始。")
        changed = context.get("changedFiles") or []
        if changed:
            lines.append(f"- 本次已改动 {len(changed)} 个文件：{', '.join(changed[:8])}")
        lines.append("配置好 .env 里的 ARK_API_KEY 和 ARK_MODEL 并重启后，我就能正常对话了。")
        return "\n".join(lines)
