from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from server_py.core.json_io import now_iso, read_json
from server_py.core.paths import PROJECT_ROOT, conversation_root


MODEL_PRICING_PATH = PROJECT_ROOT / "config" / "model-pricing.json"


class MetricStore:
    def record_model_call(self, conversation_id: str, source: str, model: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
        prompt_tokens = int(metrics.get("promptTokens") or 0)
        completion_tokens = int(metrics.get("completionTokens") or 0)
        cost = self._cost(model.get("id") or model.get("model"), prompt_tokens, completion_tokens)
        return self._append(
            conversation_id,
            {
                "kind": "model",
                "source": source,
                "modelId": model.get("id"),
                "modelName": model.get("model"),
                "provider": model.get("provider"),
                "latencyMs": metrics.get("latencyMs"),
                "promptTokens": prompt_tokens,
                "completionTokens": completion_tokens,
                "totalTokens": prompt_tokens + completion_tokens,
                "estimatedCost": cost,
            },
        )

    def record_tool_call(self, conversation_id: str, tool_id: str, duration_ms: int, ok: bool, risk_level: str) -> dict[str, Any]:
        return self._append(
            conversation_id,
            {
                "kind": "tool",
                "toolId": tool_id,
                "durationMs": duration_ms,
                "ok": ok,
                "riskLevel": risk_level,
            },
        )

    def list(self, conversation_id: str, limit: int = 500) -> list[dict[str, Any]]:
        path = conversation_root(conversation_id) / "metrics.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows[-limit:]

    def summary(self, conversation_id: str) -> dict[str, Any]:
        rows = self.list(conversation_id)
        model_rows = [row for row in rows if row.get("kind") == "model"]
        tool_rows = [row for row in rows if row.get("kind") == "tool"]
        return {
            "conversationId": conversation_id,
            "modelCallCount": len(model_rows),
            "toolCallCount": len(tool_rows),
            "totalTokens": sum(int(row.get("totalTokens") or 0) for row in model_rows),
            "promptTokens": sum(int(row.get("promptTokens") or 0) for row in model_rows),
            "completionTokens": sum(int(row.get("completionTokens") or 0) for row in model_rows),
            "totalEstimatedCost": round(sum(float(row.get("estimatedCost", {}).get("amount") or 0) for row in model_rows), 8),
            "toolDurationMs": sum(int(row.get("durationMs") or 0) for row in tool_rows),
            "failedToolCalls": len([row for row in tool_rows if not row.get("ok")]),
            "updatedAt": now_iso(),
        }

    def _append(self, conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        metric = {"id": f"metric_{uuid4().hex[:12]}", "conversationId": conversation_id, "createdAt": now_iso(), **payload}
        path = conversation_root(conversation_id) / "metrics.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(metric, ensure_ascii=False) + "\n")
        return metric

    def _cost(self, model_id: str | None, prompt_tokens: int, completion_tokens: int) -> dict[str, Any]:
        pricing = read_json(MODEL_PRICING_PATH, {"currency": "USD", "models": {}})
        model_price = (pricing.get("models") or {}).get(model_id or "", {})
        input_price = float(model_price.get("inputPer1M") or 0)
        output_price = float(model_price.get("outputPer1M") or 0)
        amount = (prompt_tokens / 1_000_000 * input_price) + (completion_tokens / 1_000_000 * output_price)
        return {
            "amount": round(amount, 8),
            "currency": pricing.get("currency", "USD"),
            "estimated": True,
            "pricingConfigured": input_price > 0 or output_price > 0,
        }
