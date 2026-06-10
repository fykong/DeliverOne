from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


class ArkClient:
    def __init__(self) -> None:
        self.last_metrics: dict[str, Any] = {}

    def complete(self, model: dict[str, Any], messages: list[dict[str, str]]) -> str:
        started = time.perf_counter()
        if model.get("provider") == "mock":
            reply = self._mock_reply(messages)
            self.last_metrics = self._metrics(started, messages, reply, {})
            return reply

        endpoint = model.get("endpoint")
        if not endpoint:
            raise RuntimeError("模型配置缺少 endpoint")

        api_key_env = model.get("apiKeyEnv") or "ARK_API_KEY"
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"缺少环境变量 {api_key_env}")

        model_name = os.environ.get(model.get("modelEnv") or "") or model.get("model")
        body = json.dumps(
            {
                "model": model_name,
                "messages": messages,
                "temperature": 0.2,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"模型调用失败：{error.code} {detail}") from error

        reply = payload["choices"][0]["message"]["content"]
        self.last_metrics = self._metrics(started, messages, reply, payload.get("usage") or {})
        return reply

    def _mock_reply(self, messages: list[dict[str, str]]) -> str:
        requirement = messages[-1]["content"] if messages else ""
        return "\n".join(
            [
                "需求确认：我已经收到当前需求。",
                "",
                "需要澄清：如果涉及具体页面或接口，需要用户确认目标位置。",
                "",
                "执行计划：先读取仓库画像，再搜索相关文件，确认修改范围，建立检查点后再写代码。",
                "",
                f"当前输入摘要：{requirement[:400]}",
                "",
                "风险与确认：写文件前必须创建检查点，命令和回退操作必须在沙盒中执行。",
            ]
        )

    def _metrics(self, started: float, messages: list[dict[str, str]], reply: str, usage: dict[str, Any]) -> dict[str, Any]:
        prompt_text = "\n".join(message.get("content", "") for message in messages)
        prompt_tokens = usage.get("prompt_tokens") or usage.get("promptTokens") or max(1, len(prompt_text) // 4)
        completion_tokens = usage.get("completion_tokens") or usage.get("completionTokens") or max(1, len(reply) // 4)
        return {
            "latencyMs": int((time.perf_counter() - started) * 1000),
            "promptTokens": int(prompt_tokens),
            "completionTokens": int(completion_tokens),
            "totalTokens": int(usage.get("total_tokens") or usage.get("totalTokens") or int(prompt_tokens) + int(completion_tokens)),
        }
