from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


class ArkClient:
    # 429/5xx 与网络抖动重试：等待秒数即重试间隔，长度即最大重试次数。
    RETRY_BACKOFF_SECONDS = (1.0, 3.0)

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
            raise RuntimeError(f"缺少环境变量 {api_key_env}。请在项目根目录 .env 写入 {api_key_env}=你的key 后重启后端。")

        model_name = os.environ.get(model.get("modelEnv") or "") or model.get("model")
        timeout_seconds = int(model.get("timeoutSeconds") or 60)
        body = json.dumps(
            {
                "model": model_name,
                "messages": messages,
                "temperature": float(model.get("temperature", 0.2)),
                # 跨栈写入计划要在单次输出里携带多个完整文件，默认输出上限会截断 JSON。
                "max_tokens": int(model.get("maxOutputTokens") or 16384),
            }
        ).encode("utf-8")

        payload = self._post_with_retry(endpoint, body, api_key, timeout_seconds)

        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            snippet = json.dumps(payload, ensure_ascii=False)[:400]
            raise RuntimeError(f"模型响应缺少 choices 字段，无法解析回复。原始响应片段：{snippet}")
        reply = str(((choices[0].get("message") or {}).get("content")) or "")
        if not reply:
            raise RuntimeError("模型返回了空回复，请稍后重试或检查模型配额。")
        self.last_metrics = self._metrics(started, messages, reply, payload.get("usage") or {})
        return reply

    def _post_with_retry(self, endpoint: str, body: bytes, api_key: str, timeout_seconds: int) -> dict[str, Any]:
        last_error: Exception | None = None
        attempts = len(self.RETRY_BACKOFF_SECONDS) + 1
        for attempt in range(attempts):
            request = urllib.request.Request(
                endpoint,
                data=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                raw = error.read().decode("utf-8", errors="replace")[:500]
                if error.code == 429:
                    last_error = RuntimeError("模型调用被限流（每分钟次数已达上限），请约 1 分钟后重试。")
                elif error.code in {401, 403}:
                    last_error = RuntimeError("模型鉴权失败（401/403）：请检查 .env 中的 ARK_API_KEY 是否正确并重启。")
                else:
                    last_error = RuntimeError(f"模型调用失败（HTTP {error.code}）：{self._extract_upstream_message(raw)}")
                # 401/403/400 等客户端错误重试无意义，直接报出。
                if error.code not in {429, 500, 502, 503, 504}:
                    raise last_error from error
            except urllib.error.URLError as error:
                reason = getattr(error, "reason", error)
                last_error = RuntimeError(f"模型网络请求失败：{reason}。请检查网络连通性，稍后会自动重试。")
            except TimeoutError:
                last_error = RuntimeError(f"模型调用超过 {timeout_seconds}s 超时。建议错峰调用或稍后重试。")
            except json.JSONDecodeError as error:
                last_error = RuntimeError(f"模型响应不是合法 JSON：{error}")
            if attempt < len(self.RETRY_BACKOFF_SECONDS):
                time.sleep(self.RETRY_BACKOFF_SECONDS[attempt])
        raise last_error if last_error else RuntimeError("模型调用失败：未知错误。")

    def _extract_upstream_message(self, raw: str) -> str:
        """从上游 JSON 错误体里抠出人类可读的 message，避免把整段嵌套 JSON 甩给用户。"""
        try:
            payload = json.loads(raw)
            message = (payload.get("error") or {}).get("message") if isinstance(payload, dict) else None
            if message:
                return str(message)[:200]
        except (json.JSONDecodeError, AttributeError):
            pass
        return raw[:200]

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
