from __future__ import annotations

import json
from typing import Any

from server_py.core.json_io import now_iso
from server_py.memory.memory_service import slim_memory_for_model
from server_py.models.ark_client import ArkClient
from server_py.models.model_config import ModelConfigService
from server_py.observability.metrics import MetricStore
from server_py.skills.runtime import SkillRuntime

# Clarifier 逐项检查的歧义维度。需求模式 Skill 还会通过 clarifyChecklist
# 注入模式专属的追问清单，两者一起构成澄清深度。
CLARIFY_DIMENSIONS = [
    "功能目标：用户最终要看到/得到什么？",
    "位置载体：改动落在哪个页面、组件或接口上？",
    "数据来源：展示或写入的数据从哪来，是否需要持久化？",
    "边界范围：哪些东西明确不能动（不改后端/不改样式/不动现有行为）？",
    "验收标准：怎么算做完？空值、零值、异常时的预期行为？",
    "状态权限：未登录、无数据、旧数据场景下的行为？",
]


class AgentRoleSuite:
    """模型驱动的 Clarifier / Reviewer / Verifier。

    三个角色都优先让当前默认模型返回可解析 JSON；如果模型不可用、返回非法
    JSON，或者字段不完整，就回退到确定性规则。确定性规则仍作为安全兜底，
    会和模型审计结果合并，避免模型误放行危险计划。
    """

    def __init__(
        self,
        client: ArkClient | None = None,
        metrics: MetricStore | None = None,
        models: ModelConfigService | None = None,
        skills: SkillRuntime | None = None,
    ) -> None:
        self.client = client
        self.metrics = metrics
        self.models = models
        self.skills = skills

    def clarify(
        self,
        requirement: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        conversation_id: str | None = None,
        memory_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        skill_guidance = self._clarify_skill_guidance(requirement, repository)
        rule_findings = self._clarify_rules(requirement, repository, sandbox)
        fallback = self._record(
            "clarification",
            "Clarifier",
            rule_findings,
            summary="已完成需求清晰度检查。",
            recommendation="如果存在阻断问题，需要先补齐仓库、沙盒或需求边界。",
            model_source="rules",
        )
        fallback["questions"] = self._fallback_questions(rule_findings, skill_guidance)
        result = self._run_model_role(
            conversation_id=conversation_id,
            metric_source="role_clarifier",
            stage="clarification",
            source="Clarifier",
            fallback=fallback,
            task=(
                "你是需求澄清 Agent。第一步先判断输入意图 inputIntent："
                "development=可落地的代码开发需求（哪怕模糊）；question=对系统/项目/改动情况的提问"
                "（如『你是谁』『你能做什么』『改了哪些文件』『解释一下方案』）；chitchat=寒暄闲聊。"
                "inputIntent 不是 development 时，verdict 给 blocked 即可，无需生成澄清问题。"
                "对 development 输入：逐条对照 clarifyDimensions 检查需求是否可执行；"
                "如果命中了 skillGuidance 里的需求模式，还要逐条对照该模式的 clarifyChecklist 和 antiPatterns。"
                "输出：(1) inputIntent；(2) requirementDsl：把已经明确的部分结构化（goal、pages、dataChanges、apiChanges、uiChanges、"
                "acceptanceCriteria、nonGoals、assumptions）；(3) ambiguities：每个未明确的维度生成一条，"
                "包含 dimension、question（具体、可直接回答、能给选项就给选项）、why、blocking(true/false)；"
                "(4) antiPatternFindings：自相矛盾、术语未定义、与仓库现状冲突的地方，给出 type、detail、suggestion。"
                "存在 blocking 歧义或矛盾时 verdict 必须是 blocked，并把追问写进 questions；"
                "需求完整时不要为了提问而提问，直接 pass。"
            ),
            payload={
                "requirement": requirement,
                "repository": repository,
                "sandbox": sandbox,
                "memory": slim_memory_for_model(memory_snapshot),
                "clarifyDimensions": CLARIFY_DIMENSIONS,
                "skillGuidance": skill_guidance,
                "hardRules": [
                    "缺少沙盒时不能进入代码写入链路。",
                    "需求过短或只说优化、调整、不好看时，需要追问目标页面、验收标准和不改动范围。",
                    "自相矛盾的需求（如既要持久化又不许动后端）必须指出矛盾并给出可选路径，不允许自行选一条硬编。",
                    "追问必须具体到可以直接回答，禁止『请提供更多信息』式的空泛问题。",
                    "questions 数量不超过 5 个，按重要性排序，blocking 的在前。",
                    "用户已在回答中对矛盾做出取舍时，按取舍后的需求判定，不要重复追问已回答的问题。",
                    "只输出 JSON，不要输出 Markdown。",
                ],
            },
        )
        # blocked 必须可行动：没有任何追问、也没有 error 级 finding 的 blocked
        # 是死路（用户无从回答），降级为 warning 继续进入方案。
        # 例外:非开发意图(提问/闲聊)的 blocked 无追问是预期行为,由编排器转对话回答。
        if (
            result.get("verdict") == "blocked"
            and result.get("inputIntent", "development") == "development"
            and not result.get("questions")
            and not any(finding.get("severity") == "error" for finding in result.get("findings", []))
        ):
            result["verdict"] = "warning"
            result["recommendation"] = (
                str(result.get("recommendation") or "") + "（blocked 缺少可回答的追问，已降级为 warning 继续推进。）"
            ).strip()
        return result

    def _clarify_skill_guidance(
        self,
        requirement: str,
        repository: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not self.skills:
            return []
        try:
            matched = self.skills.peek(requirement, repository)
        except Exception:
            return []
        guidance: list[dict[str, Any]] = []
        for skill in matched:
            checklist = skill.get("clarifyChecklist")
            anti_patterns = skill.get("antiPatterns")
            if not checklist and not anti_patterns:
                continue
            guidance.append(
                {
                    "skillId": skill.get("id"),
                    "name": skill.get("name"),
                    "kind": skill.get("kind"),
                    "clarifyChecklist": checklist or [],
                    "antiPatterns": anti_patterns or [],
                }
            )
        return guidance

    def _fallback_questions(
        self,
        findings: list[dict[str, Any]],
        skill_guidance: list[dict[str, Any]],
    ) -> list[str]:
        # 模型不可用时的兜底：命中需求模式 Skill 的 clarifyChecklist 直接作为追问，
        # 保证澄清环节在规则模式下仍然能产出具体问题。
        if not findings:
            return []
        questions: list[str] = []
        for guidance in skill_guidance:
            for item in guidance.get("clarifyChecklist", []):
                if item not in questions:
                    questions.append(str(item))
                if len(questions) >= 6:
                    return questions
        return questions

    def review_tool_plan(
        self,
        plan: dict[str, Any],
        conversation_id: str | None = None,
        memory_snapshot: dict[str, Any] | None = None,
        prefer_rules: bool = False,
    ) -> dict[str, Any]:
        fallback = self._record(
            "planning",
            "Reviewer",
            self._review_rules(plan),
            summary="已完成工具计划安全审查。",
            recommendation="工具计划必须先读上下文、检查 diff；写入步骤必须有 checkpoint。",
            model_source="rules",
        )
        if prefer_rules:
            # 只读侦察计划无写入/命令风险，规则审计足够；跳过模型调用以降低时延与 token。
            fallback["fallbackReason"] = "只读计划走规则快速审计（fast-path），未调用模型。"
            return fallback
        return self._run_model_role(
            conversation_id=conversation_id,
            metric_source="role_reviewer",
            stage="planning",
            source="Reviewer",
            fallback=fallback,
            task="审查工具计划是否安全、是否读取上下文、是否包含 diff/checkpoint/验证。发现阻断时必须给出原因。",
            payload={
                "plan": self._compact_plan(plan),
                "memory": slim_memory_for_model(memory_snapshot),
                "hardRules": [
                    "空计划必须 blocked。",
                    "写入步骤必须 requiresCheckpoint=true。",
                    "计划至少要有 diff 检查，否则给 warning。",
                    "Reviewer blocked 时用户不能直接执行计划。",
                ],
            },
        )

    def narrate_execution(
        self,
        plan: dict[str, Any] | None,
        verification: dict[str, Any] | None,
        loop_note: str,
        conversation_id: str | None = None,
    ) -> str | None:
        """把一轮执行讲成第一人称工作日志(纯文本,非 JSON)。

        碎片化的里程碑结论("1 步完成、0 步失败")对 PM 没有信息量;
        模型基于真实步骤结果+Verifier 结论叙述:做了什么(带文件名/命令/
        数字等关键细节)、发现了什么、怎么判断、下一步是什么。
        模型不可用或失败时返回 None,调用方回退到确定性里程碑文本。
        """
        model = self._default_model()
        if not model or not plan:
            return None
        steps = []
        for step in plan.get("steps", []):
            if not isinstance(step, dict):
                continue
            data = (step.get("result") or {}).get("data") if isinstance(step.get("result"), dict) else {}
            steps.append(
                {
                    "title": step.get("title"),
                    "toolId": step.get("toolId"),
                    "status": step.get("status"),
                    "summary": step.get("summary"),
                    "keyOutput": str((data or {}).get("stdoutTail") or (data or {}).get("stderrTail") or "")[-500:] or None,
                }
            )
        payload = {
            "requirement": str(plan.get("requirement") or "")[:400],
            "steps": steps,
            "verifier": {
                "verdict": (verification or {}).get("verdict"),
                "summary": (verification or {}).get("summary"),
                "recommendation": (verification or {}).get("recommendation"),
                "requirementCompleted": (verification or {}).get("requirementCompleted"),
                "findings": [
                    {"title": item.get("title"), "detail": str(item.get("detail") or "")[:200]}
                    for item in ((verification or {}).get("findings") or [])[:4]
                    if isinstance(item, dict)
                ],
            },
            "next": loop_note,
        }
        messages = [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "你是代码交付 Agent 本人,刚执行完一轮工具计划,现在向产品经理口头汇报这一轮。",
                        "用中文第一人称,2-4 个自然段,自然衔接,像同事汇报,不要标题、不要编号列表、不要'本轮''该步骤'这类公文腔。",
                        "必须包含:你实际做了什么(保留关键细节:改了哪个文件、跑了什么命令、几个测试通过/失败、发现的具体问题);你对结果的判断(用自己的话消化 Verifier 的结论,别照抄);接下来要做什么或需要用户做什么(payload.next 是系统已经安排好的下一步,如实转述)。",
                        "只依据 payload 里的事实,不要编造;数字、文件名、命令原样保留。",
                        "直接输出汇报正文,不要 JSON,不要任何前后缀。",
                    ]
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ]
        try:
            reply = self.client.complete(model, messages).strip()
            if conversation_id and self.metrics:
                self.metrics.record_model_call(conversation_id, "narrator", model, self.client.last_metrics)
            return reply or None
        except Exception:
            return None

    def verify_execution(
        self,
        plan: dict[str, Any] | None,
        conversation_id: str | None = None,
        memory_snapshot: dict[str, Any] | None = None,
        prefer_rules: bool = False,
    ) -> dict[str, Any]:
        verify_findings = self._verify_rules(plan)
        fallback = self._record(
            "post_verify",
            "Verifier",
            verify_findings,
            summary="已完成执行结果验证。",
            recommendation="失败时进入修复循环；通过时继续交付包和回退点审查。",
            model_source="rules",
        )
        fallback.update(self._repair_policy_from_plan(plan, verify_findings))
        if prefer_rules:
            # 只读计划没有代码变更与验证命令证据要判读，规则验证足够。
            fallback["fallbackReason"] = "只读计划走规则快速验证（fast-path），未调用模型。"
            return fallback
        return self._run_model_role(
            conversation_id=conversation_id,
            metric_source="role_verifier",
            stage="post_verify",
            source="Verifier",
            fallback=fallback,
            task="基于工具结果、验证输出、diff 和审计记录判断执行是否通过；失败时给出修复方向。",
            payload={
                "plan": self._compact_plan(plan) if plan else None,
                "memory": slim_memory_for_model(memory_snapshot),
                "hardRules": [
                    "存在 failed 步骤时必须 blocked。",
                    "工具结果缺失时至少 warning。",
                    "计划完成但没有 diff 时给 warning，除非需求只是检查。",
                    "前端、页面、UI、预览相关任务必须检查 previewResults；有截图失败、HTTP 失败或 HTML 为空时不能判定交付可靠。",
                    "运行后 DOM 读取失败、运行后可见文本过少、浏览器控制台存在错误时，不能直接判定前端交付可靠。",
                    "如果 previewResults 中 assertions.enabled=true 且 assertions.ok=false，必须判定为未满足验收。",
                    "如果 previewResults 通过，应把截图路径、HTML 标题、运行后 DOM、控制台错误数和报告路径作为交付证据。",
                    "失败时必须给出下一轮修复建议。",
                    "失败时必须输出 failureClass 和 repairPolicy。",
                    "failureClass 只能是 environment、code、plan、requirement、external、unknown。",
                    "依赖未安装、命令不存在、版本冲突属于 environment，不消耗代码修复次数。",
                    "类型错误、lint、测试断言、运行时报错属于 code，消耗代码修复次数。",
                    "读文件不够、工具计划选错属于 plan，应重新规划，不消耗代码修复次数。",
                    "需求方向冲突或验收标准不清属于 requirement，必须停下澄清。",
                    "API key、网络权限、外部 MCP 授权失败属于 external，必须请求配置或授权。",
                ],
            },
        )

    def _run_model_role(
        self,
        conversation_id: str | None,
        metric_source: str,
        stage: str,
        source: str,
        fallback: dict[str, Any],
        task: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        model = self._default_model()
        if not model:
            fallback["fallbackReason"] = "模型不可用，使用确定性规则。"
            return fallback

        try:
            raw_response = self.client.complete(model, self._messages(source, task, payload))
            if conversation_id and self.metrics:
                self.metrics.record_model_call(conversation_id, metric_source, model, self.client.last_metrics)
            parsed = self._parse_json(raw_response)
            model_record = self._record_from_model(stage, source, parsed, model, raw_response)
            merged = self._merge_safety_findings(model_record, fallback)
            merged["modelSource"] = "model"
            if fallback["findings"]:
                merged["ruleFindings"] = fallback["findings"]
            return merged
        except Exception as error:
            fallback["fallbackReason"] = f"模型角色 JSON 解析失败，已回退规则：{error}"
            return fallback

    # 输出示例固定不变,放进 system 静态前缀:同一角色的 system 内容完全一致,
    # 方舟前缀缓存可命中"角色规则+示例"整段,user 消息只剩易变的 task+payload。
    EXPECTED_JSON_EXAMPLE = {
        "verdict": "warning",
        "summary": "一句话说明角色结论。",
        "findings": [
            {
                "id": "example",
                "title": "问题标题",
                "detail": "具体原因和影响。",
                "severity": "warning",
            }
        ],
        "recommendation": "下一步建议。",
        "questions": ["如果需要用户澄清，列出具体问题。"],
        "inputIntent": "development",
        "requirementDsl": {
            "goal": "一句话目标（Clarifier 专用）。",
            "pages": ["涉及页面/组件"],
            "dataChanges": ["数据/模型改动"],
            "apiChanges": ["接口改动"],
            "uiChanges": ["界面改动"],
            "acceptanceCriteria": ["验收标准"],
            "nonGoals": ["明确不做的事"],
            "assumptions": ["待用户确认的默认假设"],
        },
        "ambiguities": [
            {
                "dimension": "数据来源",
                "question": "阅读量从哪里来？A. 前端假数据 B. 后端新增字段",
                "why": "决定纯前端还是跨栈改动。",
                "blocking": True,
            }
        ],
        "antiPatternFindings": [
            {"type": "contradiction", "detail": "矛盾点描述", "suggestion": "给用户的可选路径"}
        ],
        "requirementCompleted": False,
        "failureClass": "code",
        "repairScope": "test-failure",
        "repairPolicy": {
            "failureClass": "code",
            "severity": "major",
            "autoAllowed": True,
            "countsTowardCodeRepairLimit": True,
            "requiresUserConfirmation": False,
            "maxCodeRepairAttempts": 3,
            "maxTotalRepairSteps": 8,
            "reason": "说明为什么可以继续自动修复。",
        },
    }

    def _messages(self, source: str, task: str, payload: dict[str, Any]) -> list[dict[str, str]]:
        # 前缀缓存关键:所有角色共享的静态内容(规则+示例)放最前,
        # 随角色变化的那一行放 system 末尾——方舟隐式缓存按公共前缀识别
        # (≥1024 tokens 才可能命中),角色名在第一行会让前缀从头分叉。
        return [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "你是本地代码交付 Agent 的一个审查角色(具体角色见本消息最后一行)。",
                        "必须用中文思考并输出。",
                        "只输出 JSON，不要输出 Markdown，不要添加解释性前后缀。",
                        "JSON 顶层必须是对象。",
                        "字段：verdict=pass|warning|blocked，summary，findings，recommendation，questions。",
                        "Clarifier 还要输出 inputIntent（development|question|chitchat）、requirementDsl（对象）、ambiguities（数组）、antiPatternFindings（数组）。",
                        "Verifier 失败时还要输出 failureClass、repairScope、repairPolicy。",
                        "Verifier 必须输出 requirementCompleted（布尔）：用户的核心需求本身是否已经真正落地。环境修复、依赖安装、测试通过都不等于需求完成；只有需求要求的代码改动确实存在并验证有效才算 true。",
                        "requirementCompleted 必须与 summary 的结论一致：如果 summary 说核心需求已完成/可进入交付，requirementCompleted 必须是 true；自相矛盾会让系统反复生成无意义的推进计划。不要照抄示例值，要根据本次证据如实判断。",
                        "findings 是数组，每项包含 id、title、detail、severity=info|warning|error。",
                        "repairPolicy 包含 failureClass、severity、autoAllowed、countsTowardCodeRepairLimit、requiresUserConfirmation、maxCodeRepairAttempts、maxTotalRepairSteps、reason。",
                        "blocked 表示不能进入下一阶段；warning 表示可继续但必须提示风险；pass 表示可继续。",
                        "必须遵守 payload.memory.taskState：用户暂停阶段时给 blocked，用户覆盖下一步动作时按覆盖动作审查。",
                        "memory.provenDeadEnds_doNotRetry 中的路径/做法已被真实执行证伪：禁止把它们当成候选、搜索词或追问选项，只能作为排除依据；生成追问选项时优先采用仓库画像/skill 中的真实路径。",
                        "输出 JSON 的结构必须符合下面的 expectedJson 示例（字段值要按本次任务如实填写）：",
                        json.dumps(self.EXPECTED_JSON_EXAMPLE, ensure_ascii=False, indent=2),
                        f"本次你的角色是：{source}。",
                    ]
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"task": task, "payload": payload}, ensure_ascii=False, indent=2),
            },
        ]

    def _default_model(self) -> dict[str, Any] | None:
        if not self.client or not self.models:
            return None
        model = self.models.get_default_model()
        return model if model.get("enabled") else None

    def _parse_json(self, raw_response: str) -> dict[str, Any]:
        text = raw_response.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise RuntimeError("角色模型返回的不是 JSON 对象。")
        return parsed

    def _record_from_model(
        self,
        stage: str,
        source: str,
        parsed: dict[str, Any],
        model: dict[str, Any],
        raw_response: str,
    ) -> dict[str, Any]:
        findings = self._sanitize_findings(parsed.get("findings"))
        verdict = self._normalize_verdict(parsed.get("verdict"), findings)
        clarifier_extras: dict[str, Any] = {}
        if isinstance(parsed.get("requirementDsl"), dict):
            clarifier_extras["requirementDsl"] = parsed["requirementDsl"]
        if isinstance(parsed.get("ambiguities"), list):
            clarifier_extras["ambiguities"] = [item for item in parsed["ambiguities"] if isinstance(item, dict)]
            if any(item.get("blocking") for item in clarifier_extras["ambiguities"]) and verdict == "pass":
                verdict = "blocked"
        if isinstance(parsed.get("antiPatternFindings"), list):
            clarifier_extras["antiPatternFindings"] = [item for item in parsed["antiPatternFindings"] if isinstance(item, dict)]
        intent = str(parsed.get("inputIntent") or "").strip().lower()
        if intent in {"development", "question", "chitchat"}:
            clarifier_extras["inputIntent"] = intent
        # Verifier 对"需求本身是否真正落地"的判断,推进循环据此决定是否继续,
        # 而不是机械的"有 diff + 验证绿"——环境修复的 diff 会骗过机械判定。
        if isinstance(parsed.get("requirementCompleted"), bool):
            clarifier_extras["requirementCompleted"] = parsed["requirementCompleted"]
        return {
            **clarifier_extras,
            "id": f"role_{source.lower()}_{now_iso()}",
            "stage": stage,
            "source": source,
            "verdict": verdict,
            "summary": str(parsed.get("summary") or ""),
            "recommendation": str(parsed.get("recommendation") or ""),
            "questions": [str(item) for item in parsed.get("questions", []) if isinstance(item, str)],
            "failureClass": self._normalize_failure_class(parsed.get("failureClass")),
            "repairScope": str(parsed.get("repairScope") or ""),
            "repairPolicy": self._normalize_repair_policy(parsed.get("repairPolicy"), parsed.get("failureClass")),
            "findings": findings,
            "model": {
                "id": model.get("id"),
                "displayName": model.get("displayName"),
                "provider": model.get("provider"),
            },
            "rawResponse": raw_response,
            "reusedFrom": ["Codex planning gate", "Codex reviewer/verifier separation"],
            "createdAt": now_iso(),
        }

    def _merge_safety_findings(self, model_record: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        merged = dict(model_record)
        findings = list(model_record.get("findings") or [])
        known = {finding.get("id") for finding in findings}
        for finding in fallback.get("findings", []):
            if finding.get("id") not in known:
                findings.append(finding)
                known.add(finding.get("id"))
        merged["findings"] = findings
        merged["verdict"] = self._strictest_verdict(model_record.get("verdict"), fallback.get("verdict"), findings)
        if not merged.get("summary"):
            merged["summary"] = fallback.get("summary", "")
        if not merged.get("recommendation"):
            merged["recommendation"] = fallback.get("recommendation", "")
        if not merged.get("repairPolicy") and fallback.get("repairPolicy"):
            merged["repairPolicy"] = fallback["repairPolicy"]
        if (not merged.get("failureClass") or merged.get("failureClass") == "unknown") and fallback.get("failureClass"):
            merged["failureClass"] = fallback["failureClass"]
        if not merged.get("repairScope") and fallback.get("repairScope"):
            merged["repairScope"] = fallback["repairScope"]
        return merged

    def _strictest_verdict(self, model_verdict: Any, fallback_verdict: Any, findings: list[dict[str, Any]]) -> str:
        if any(finding.get("severity") == "error" for finding in findings):
            return "blocked"
        if model_verdict == "blocked" or fallback_verdict == "blocked":
            return "blocked"
        if model_verdict == "warning" or fallback_verdict == "warning" or findings:
            return "warning"
        return "pass"

    def _normalize_verdict(self, raw: Any, findings: list[dict[str, Any]]) -> str:
        value = str(raw or "").strip().lower()
        if value in {"pass", "warning", "blocked"}:
            return self._strictest_verdict(value, "pass", findings)
        if any(finding.get("severity") == "error" for finding in findings):
            return "blocked"
        return "warning" if findings else "pass"

    def _sanitize_findings(self, raw_findings: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_findings, list):
            return []
        findings: list[dict[str, Any]] = []
        for index, item in enumerate(raw_findings, start=1):
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity") or "warning").lower()
            if severity not in {"info", "warning", "error"}:
                severity = "warning"
            findings.append(
                self._finding(
                    str(item.get("id") or f"model-finding-{index}"),
                    str(item.get("title") or "模型审计发现"),
                    str(item.get("detail") or ""),
                    severity,
                )
            )
        return findings

    def _clarify_rules(
        self,
        requirement: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        text = requirement.strip()
        if len(text) < 12:
            findings.append(self._finding("requirement-too-short", "需求过短", "需求信息不足，建议先追问目标、范围和验收标准。", "warning"))
        if not repository:
            findings.append(self._finding("missing-repository", "缺少仓库", "还没有接入仓库，不能进入代码交付链路。", "warning"))
        if not sandbox:
            findings.append(self._finding("missing-sandbox", "缺少沙盒", "每个对话必须先创建独立沙盒，写入只能发生在沙盒内。", "error"))
        if any(word in text for word in ["优化", "调整", "改一下", "不好看"]) and not any(word in text for word in ["验收", "具体", "文件", "页面"]):
            findings.append(self._finding("ambiguous-change", "需求边界可能不清", "需求包含泛化修改词，建议确认目标页面、验收标准和不希望改动的范围。", "warning"))
        no_backend = any(word in text for word in ["不要动后端", "不改后端", "不动后端", "只改前端", "纯前端"])
        needs_persistence = any(word in text for word in ["保存", "持久", "数据库", "新字段", "加字段", "记录下来"])
        if no_backend and needs_persistence:
            # warning 而非 error：模型是主要的矛盾检测者(能理解用户后续的取舍回答)，
            # 规则只做提示；error 会在合并后的文本上强制 blocked，盖掉模型的正确判断。
            findings.append(
                self._finding(
                    "contradictory-scope",
                    "需求可能自相矛盾",
                    "需求文本同时出现不动后端与持久化数据，请确认用户是否已在澄清回答中做出取舍。",
                    "warning",
                )
            )
        return findings

    def _review_rules(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        steps = plan.get("steps", []) if isinstance(plan.get("steps"), list) else []
        if not steps:
            findings.append(self._finding("empty-plan", "工具计划为空", "没有可审查的工具步骤。", "error"))
        active_steps = [step for step in steps if isinstance(step, dict) and step.get("status") != "skipped" and not step.get("disabled")]
        if steps and not active_steps:
            findings.append(self._finding("no-active-step", "没有可执行步骤", "所有工具步骤都已被禁用，确认执行后不会产生有效证据。", "error"))
        has_diff_check = any(step.get("toolId") == "code.git_diff" for step in active_steps)
        if not has_diff_check:
            findings.append(self._finding("missing-diff-check", "缺少 Diff 检查", "工具计划应包含 diff 检查，避免覆盖已有沙盒改动。", "warning"))
        write_steps = [step for step in active_steps if step.get("riskLevel") == "write"]
        if write_steps and not any(step.get("requiresCheckpoint") for step in write_steps):
            findings.append(self._finding("write-without-checkpoint", "写入缺少 checkpoint", "写入步骤必须绑定 checkpoint。", "error"))
        return findings

    def _verify_rules(self, plan: dict[str, Any] | None) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        if not plan:
            return [self._finding("missing-plan", "缺少工具计划", "没有可验证的工具计划。", "error")]

        evidence = plan.get("evidence", {}) if isinstance(plan.get("evidence"), dict) else {}
        failed_steps = [step for step in plan.get("steps", []) if isinstance(step, dict) and step.get("status") == "failed"]
        if failed_steps:
            findings.append(self._finding("failed-steps", "存在失败步骤", f"{len(failed_steps)} 个工具步骤失败，应进入修复循环。", "error"))
        if not evidence.get("toolResults"):
            findings.append(self._finding("missing-tool-results", "缺少工具结果", "执行后没有工具结果证据。", "warning"))
        if plan.get("status") == "completed" and not evidence.get("diffFiles"):
            findings.append(self._finding("no-diff-after-complete", "没有代码变更", "计划完成但没有 diff 文件，可能只是检查流程。", "warning"))
        return findings

    def _repair_policy_from_plan(self, plan: dict[str, Any] | None, findings: list[dict[str, Any]]) -> dict[str, Any]:
        if not findings:
            return {
                "failureClass": "unknown",
                "repairScope": "",
                "repairPolicy": {
                    "failureClass": "unknown",
                    "severity": "minor",
                    "autoAllowed": False,
                    "countsTowardCodeRepairLimit": False,
                    "requiresUserConfirmation": False,
                    "maxCodeRepairAttempts": 3,
                    "maxTotalRepairSteps": 8,
                    "reason": "当前没有失败，不需要修复。",
                },
            }
        failure_class, scope, reason = self._classify_failure(plan)
        auto_allowed = failure_class in {"environment", "code", "plan", "unknown"}
        requires_user_confirmation = failure_class in {"requirement", "external"}
        counts_code = failure_class == "code"
        severity = "blocked" if failure_class in {"requirement", "external"} else ("major" if failure_class in {"code", "environment"} else "minor")
        return {
            "failureClass": failure_class,
            "repairScope": scope,
            "repairPolicy": {
                "failureClass": failure_class,
                "severity": severity,
                "autoAllowed": auto_allowed,
                "countsTowardCodeRepairLimit": counts_code,
                "requiresUserConfirmation": requires_user_confirmation,
                "maxCodeRepairAttempts": 3,
                "maxTotalRepairSteps": 8,
                "reason": reason,
            },
        }

    def _classify_failure(self, plan: dict[str, Any] | None) -> tuple[str, str, str]:
        if not plan:
            return "plan", "missing-plan", "缺少可验证计划，应该重新规划。"
        failed_steps = [step for step in plan.get("steps", []) if isinstance(step, dict) and step.get("status") == "failed"]
        text = "\n".join(self._step_failure_text(step) for step in failed_steps).lower()
        if any(marker in text for marker in ["api key", "apikey", "authorization", "unauthorized", "forbidden", "permission", "mcp", "network", "econnrefused", "timeout"]):
            return "external", "external-or-permission", "失败与外部服务、权限、网络或 MCP 授权有关，需要配置或授权后继续。"
        if any(marker in text for marker in ["cannot find module", "module not found", "command not found", "not recognized", "enoent", "eresolve", "npm err", "pnpm", "yarn", "missing script", "vite: not found", "dependency"]):
            return "environment", "dependency-or-script", "失败更像依赖、脚本或版本环境问题，应先在沙盒内修复环境，不消耗代码修复次数。"
        if any(marker in text for marker in ["ambiguous", "requirement", "acceptance", "用户", "需求", "验收"]):
            return "requirement", "requirement-boundary", "失败指向需求边界或验收标准不清，需要先澄清方向。"
        if any(marker in text for marker in ["no such file", "file not found", "unknown tool", "工具不存在", "缺少", "empty-plan"]):
            return "plan", "plan-or-context", "失败更像计划或上下文不足，应重新读上下文并生成更具体的计划。"
        if any(marker in text for marker in ["typescript", "tsc", "eslint", "lint", "test", "assert", "failed", "syntax", "type error", "traceback", "exception"]):
            return "code", "code-or-test", "失败来自代码、类型、lint、测试或运行时错误，应生成代码修复。"
        return "unknown", "general-repair", "无法精确分类，但可以继续读取证据并生成保守修复计划。"

    def _step_failure_text(self, step: dict[str, Any]) -> str:
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        parts = [
            str(step.get("title") or ""),
            str(step.get("summary") or ""),
            str(result.get("summary") or ""),
            str(data.get("command") or ""),
            str(data.get("stdout") or data.get("stdoutTail") or ""),
            str(data.get("stderr") or data.get("stderrTail") or ""),
        ]
        return "\n".join(parts)

    def _normalize_failure_class(self, value: Any) -> str:
        normalized = str(value or "unknown").strip().lower()
        if normalized in {"environment", "code", "plan", "requirement", "external", "unknown"}:
            return normalized
        return "unknown"

    def _normalize_repair_policy(self, raw_policy: Any, fallback_class: Any) -> dict[str, Any] | None:
        if not isinstance(raw_policy, dict):
            return None
        failure_class = self._normalize_failure_class(raw_policy.get("failureClass") or fallback_class)
        severity = str(raw_policy.get("severity") or "major").strip().lower()
        if severity not in {"minor", "major", "blocked"}:
            severity = "major"
        return {
            "failureClass": failure_class,
            "severity": severity,
            "autoAllowed": bool(raw_policy.get("autoAllowed", failure_class in {"environment", "code", "plan", "unknown"})),
            "countsTowardCodeRepairLimit": bool(raw_policy.get("countsTowardCodeRepairLimit", failure_class == "code")),
            "requiresUserConfirmation": bool(raw_policy.get("requiresUserConfirmation", failure_class in {"requirement", "external"})),
            "maxCodeRepairAttempts": int(raw_policy.get("maxCodeRepairAttempts") or 3),
            "maxTotalRepairSteps": int(raw_policy.get("maxTotalRepairSteps") or 8),
            "reason": str(raw_policy.get("reason") or ""),
        }

    def _record(
        self,
        stage: str,
        source: str,
        findings: list[dict[str, Any]],
        summary: str = "",
        recommendation: str = "",
        model_source: str = "rules",
    ) -> dict[str, Any]:
        return {
            "id": f"role_{source.lower()}_{now_iso()}",
            "stage": stage,
            "source": source,
            "verdict": "blocked" if any(item["severity"] == "error" for item in findings) else ("warning" if findings else "pass"),
            "summary": summary,
            "recommendation": recommendation,
            "questions": [],
            "failureClass": "unknown",
            "repairScope": "",
            "findings": findings,
            "modelSource": model_source,
            "reusedFrom": ["Codex planning gate", "Codex reviewer/verifier separation"],
            "createdAt": now_iso(),
        }

    def _finding(self, finding_id: str, title: str, detail: str, severity: str) -> dict[str, Any]:
        return {"id": finding_id, "title": title, "detail": detail, "severity": severity}

    def _compact_plan(self, plan: dict[str, Any] | None) -> dict[str, Any] | None:
        if not plan:
            return None
        return {
            "id": plan.get("id"),
            "status": plan.get("status"),
            "requirement": plan.get("requirement"),
            "repairOfPlanId": plan.get("repairOfPlanId"),
            "repairAttempt": plan.get("repairAttempt"),
            "generation": plan.get("generation"),
            "evidence": plan.get("evidence"),
            "audits": plan.get("audits", [])[-6:],
            "steps": [
                {
                    "id": step.get("id"),
                    "order": step.get("order"),
                    "toolId": step.get("toolId"),
                    "title": step.get("title"),
                    "purpose": step.get("purpose"),
                    "riskLevel": step.get("riskLevel"),
                    "requiresCheckpoint": step.get("requiresCheckpoint"),
                    "status": step.get("status"),
                    "summary": step.get("summary"),
                    "input": step.get("input"),
                    "result": self._compact_result(step.get("result")),
                }
                for step in plan.get("steps", [])
                if isinstance(step, dict)
            ],
        }

    def _compact_result(self, result: Any) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {
            "ok": result.get("ok"),
            "summary": result.get("summary"),
            "needsApproval": result.get("needsApproval"),
            "stdoutTail": data.get("stdoutTail"),
            "stderrTail": data.get("stderrTail"),
            "exitCode": data.get("exitCode"),
            "diffFiles": (data.get("diff") or {}).get("files") if isinstance(data.get("diff"), dict) else data.get("files"),
            "reportPath": data.get("reportPath"),
            "htmlTitle": data.get("htmlTitle"),
            "htmlBytes": data.get("htmlBytes"),
            "runtimeDom": data.get("runtimeDom") if isinstance(data.get("runtimeDom"), dict) else None,
            "browserConsole": data.get("browserConsole") if isinstance(data.get("browserConsole"), dict) else None,
            "assertions": data.get("assertions") if isinstance(data.get("assertions"), dict) else None,
            "screenshot": data.get("screenshot") if isinstance(data.get("screenshot"), dict) else None,
            "quality": data.get("quality") if isinstance(data.get("quality"), dict) else None,
            "verificationResults": data.get("results") if isinstance(data.get("results"), list) else None,
        }
