from __future__ import annotations

import json
import re
from typing import Any

from server_py.core.json_io import now_iso
from server_py.models.ark_client import ArkClient
from server_py.observability.metrics import MetricStore


PATH_RE = re.compile(r"(?:[A-Za-z0-9_.@-]+[\\/])+[A-Za-z0-9_.@-]+")
WORD_RE = re.compile(r"[A-Za-z0-9_./:@-]{3,}")


class SearchIntentService:
    """Turns a requirement into explicit local retrieval intent.

    This is not reranking and does not require embeddings. The model only
    decomposes the task into searchable hints. Local retrieval still owns the
    actual candidate lookup and scoring.
    """

    def __init__(self, client: ArkClient, metrics: MetricStore | None = None) -> None:
        self.client = client
        self.metrics = metrics

    def generate(
        self,
        conversation_id: str,
        requirement: str | None,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        model: dict[str, Any] | None,
        memory_snapshot: dict[str, Any] | None = None,
        available_commands: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        text = (requirement or "").strip()
        fallback = self._fallback(text, repository, available_commands, "rules", None)
        if not text:
            return fallback
        if not model or not model.get("enabled"):
            return self._fallback(text, repository, available_commands, "rules", "model unavailable")

        try:
            raw_response = self.client.complete(
                model,
                self._messages(text, repository, sandbox, memory_snapshot, available_commands),
            )
            if self.metrics:
                self.metrics.record_model_call(conversation_id, "search_intent", model, self.client.last_metrics)
            parsed = self._parse_json(raw_response)
            return self._normalize(parsed, text, repository, raw_response)
        except Exception as error:
            return self._fallback(text, repository, available_commands, "rules", str(error))

    def query_text(self, requirement: str | None, intent: dict[str, Any] | None) -> str:
        parts = [requirement or ""]
        if not intent:
            return "\n".join(part for part in parts if part)
        for key in ["searchQueries", "fileHints", "memoryQueries", "businessEntities", "riskHints", "verificationHints"]:
            values = intent.get(key)
            if isinstance(values, list):
                parts.extend(str(value) for value in values if str(value).strip())
        summary = str(intent.get("summary") or "").strip()
        if summary:
            parts.append(summary)
        return "\n".join(part for part in parts if part)

    def _messages(
        self,
        requirement: str,
        repository: dict[str, Any] | None,
        sandbox: dict[str, Any] | None,
        memory_snapshot: dict[str, Any] | None,
        available_commands: dict[str, str] | None,
    ) -> list[dict[str, str]]:
        recall_items = ((memory_snapshot or {}).get("recall") or {}).get("items") or []
        curated = ((memory_snapshot or {}).get("curatedMemory") or {}).get("items") or []
        return [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "你是本地代码 Agent 的搜索意图分析器。",
                        "只输出 JSON，不要输出 Markdown，不要解释。",
                        "你的任务不是回答用户，也不是生成计划，而是把需求拆成后端可检索的搜索线索。",
                        "不要编造文件路径；如果只是猜测，放到 searchQueries，不要放到 fileHints。",
                        "输出字段必须包含：summary, businessEntities, fileHints, memoryQueries, riskHints, verificationHints, searchQueries, confidence。",
                    ]
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "requirement": requirement,
                        "repository": repository,
                        "sandbox": sandbox,
                        "availableCommands": available_commands or {},
                        "initialRecall": [
                            {
                                "id": item.get("id"),
                                "kind": item.get("kind"),
                                "title": item.get("title"),
                                "reason": item.get("reason"),
                            }
                            for item in recall_items[:10]
                        ],
                        "curatedMemory": [
                            {
                                "id": item.get("id"),
                                "title": item.get("title"),
                                "tags": item.get("tags"),
                            }
                            for item in curated[:10]
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]

    def _normalize(self, parsed: dict[str, Any], requirement: str, repository: dict[str, Any] | None, raw_response: str) -> dict[str, Any]:
        fallback = self._fallback(requirement, repository, {}, "model", None)
        normalized = {
            **fallback,
            "source": "model",
            "rawResponse": raw_response[:8000],
            "fallbackReason": None,
            "summary": str(parsed.get("summary") or fallback["summary"])[:800],
            "confidence": self._bounded_float(parsed.get("confidence"), 0.72),
        }
        for key in ["businessEntities", "fileHints", "memoryQueries", "riskHints", "verificationHints", "searchQueries"]:
            normalized[key] = self._string_list(parsed.get(key), fallback.get(key, []), limit=14 if key == "searchQueries" else 10)
        if not normalized["searchQueries"]:
            normalized["searchQueries"] = fallback["searchQueries"]
        return normalized

    def _fallback(
        self,
        requirement: str,
        repository: dict[str, Any] | None,
        available_commands: dict[str, str] | None,
        source: str,
        fallback_reason: str | None,
    ) -> dict[str, Any]:
        paths = [path.replace("\\", "/") for path in PATH_RE.findall(requirement or "")]
        words = [word.lower() for word in WORD_RE.findall(requirement or "")]
        important = [word for word in words if not word.isdigit()][:12]
        scripts = list((available_commands or {}).keys())
        verification = [name for name in ["typecheck", "lint", "test", "build"] if name in scripts]
        if not verification:
            verification = [name for name in scripts if any(token in name.lower() for token in ["type", "lint", "test", "build"])][:4]
        risk_hints = self._risk_hints(requirement)
        search_queries = [requirement, *paths, *important]
        return {
            "source": source,
            "summary": requirement[:500] if requirement else "尚未输入需求。",
            "businessEntities": important[:8],
            "fileHints": paths[:10],
            "memoryQueries": [requirement[:240], *risk_hints][:8] if requirement else [],
            "riskHints": risk_hints,
            "verificationHints": verification,
            "searchQueries": [query for query in search_queries if query][:16],
            "confidence": 0.45 if fallback_reason else 0.55,
            "fallbackReason": fallback_reason,
            "generatedAt": now_iso(),
        }

    def _risk_hints(self, requirement: str) -> list[str]:
        lowered = requirement.lower()
        hints: list[str] = []
        if any(token in lowered for token in ["stripe", "webhook", "api key", "auth", "permission"]):
            hints.append("权限、密钥或外部服务风险")
        if any(token in lowered for token in ["ui", "页面", "button", "layout", "css", "preview"]):
            hints.append("前端布局和预览风险")
        if any(token in lowered for token in ["test", "lint", "type", "build"]):
            hints.append("验证命令失败风险")
        if any(token in lowered for token in ["mcp", "browser", "github"]):
            hints.append("外部工具调用风险")
        return hints[:6]

    def _parse_json(self, raw_response: str) -> dict[str, Any]:
        text = raw_response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("search intent response is not an object")
        return parsed

    def _string_list(self, value: Any, fallback: list[str], limit: int) -> list[str]:
        if not isinstance(value, list):
            return fallback[:limit]
        result: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in result:
                result.append(text[:300])
            if len(result) >= limit:
                break
        return result or fallback[:limit]

    def _bounded_float(self, value: Any, fallback: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return fallback
        return round(min(max(number, 0.0), 1.0), 3)
