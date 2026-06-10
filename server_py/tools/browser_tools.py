from __future__ import annotations

from typing import Any

from server_py.preview.smoke_test import PreviewSmokeTester
from server_py.tools.types import AgentTool, ToolContext


def create_browser_tools(preview_smoke: PreviewSmokeTester) -> list[AgentTool]:
    def _preview_smoke(payload: Any, context: ToolContext) -> dict[str, Any]:
        record = payload if isinstance(payload, dict) else {}
        port = int(record.get("port", 3000) or 3000)
        path = str(record.get("path", "/") or "/")
        timeout_seconds = min(int(record.get("timeoutSeconds", 30) or 30), 90)
        expected_texts = record.get("expectedTexts") if isinstance(record.get("expectedTexts"), list) else []
        required_selectors = record.get("requiredSelectors") if isinstance(record.get("requiredSelectors"), list) else []
        report = preview_smoke.run(
            context.conversation_id,
            port,
            path,
            timeout_seconds=timeout_seconds,
            expected_texts=[str(item) for item in expected_texts],
            required_selectors=[str(item) for item in required_selectors],
        )
        return {
            "ok": bool(report.get("ok")),
            "summary": report.get("summary", "预览 smoke test 已完成。"),
            "data": report,
        }

    return [
        AgentTool(
            "browser.preview_smoke",
            "浏览器预览验证",
            "在当前对话沙盒的预览端口上运行浏览器 smoke test，保存 HTML、运行后 DOM、控制台、断言、截图和报告。",
            "command",
            _preview_smoke,
            input_schema={
                "port": "number",
                "path": "string",
                "timeoutSeconds": "number",
                "expectedTexts": "string[]",
                "requiredSelectors": "string[]",
                "approved": "boolean",
            },
            managed_command=True,
        )
    ]
