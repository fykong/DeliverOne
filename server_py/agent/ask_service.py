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

    def answer(self, conversation_id: str, question: str) -> dict[str, Any]:
        question = (question or "").strip()
        if not question:
            raise RuntimeError("问题不能为空。")
        model = self.models.get_default_model()
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

    def _build_context(self, conversation_id: str) -> dict[str, Any]:
        state = self.conversations.get(conversation_id)
        repository = state.get("repository") if isinstance(state.get("repository"), dict) else None
        sandbox = state.get("sandbox") if isinstance(state.get("sandbox"), dict) else None
        messages = state.get("messages") if isinstance(state.get("messages"), list) else []
        recent = [
            {"role": item.get("role"), "content": str(item.get("content") or "")[:600]}
            for item in messages[-8:]
            if isinstance(item, dict)
        ]
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
