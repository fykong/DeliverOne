from __future__ import annotations

import re
from typing import Any


MAX_EXPECTED_TEXTS = 6
MAX_REQUIRED_SELECTORS = 6


def build_preview_assertions(requirement: str, memory_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build conservative browser acceptance hints from the user request.

    These hints are intentionally small. They are not a replacement for a real
    product spec; they only prevent preview smoke tests from passing when the
    page is blank or obviously missing requested UI structure.
    """

    text = _combined_text(requirement, memory_snapshot)
    expected_texts = _unique(_extract_quoted_texts(text) + _extract_explicit_text_labels(text), MAX_EXPECTED_TEXTS)
    required_selectors = _unique(_selectors_from_text(text), MAX_REQUIRED_SELECTORS)
    enabled = bool(expected_texts or required_selectors)
    parts: list[str] = []
    if expected_texts:
        parts.append(f"{len(expected_texts)} 条可见文案")
    if required_selectors:
        parts.append(f"{len(required_selectors)} 类页面结构")
    return {
        "source": "local-preview-acceptance",
        "enabled": enabled,
        "expectedTexts": expected_texts,
        "requiredSelectors": required_selectors,
        "summary": "；".join(parts) if parts else "当前需求没有提取到明确的页面验收断言。",
    }


def merge_preview_assertions(input_payload: dict[str, Any], hints: dict[str, Any]) -> dict[str, Any]:
    merged = dict(input_payload)
    if not _string_list(merged.get("expectedTexts")) and hints.get("expectedTexts"):
        merged["expectedTexts"] = list(hints["expectedTexts"])
    if not _string_list(merged.get("requiredSelectors")) and hints.get("requiredSelectors"):
        merged["requiredSelectors"] = list(hints["requiredSelectors"])
    return merged


def _combined_text(requirement: str, memory_snapshot: dict[str, Any] | None) -> str:
    parts = [requirement or ""]
    task_state = (memory_snapshot or {}).get("taskState") if isinstance(memory_snapshot, dict) else None
    if isinstance(task_state, dict):
        parts.extend(str(item) for item in task_state.get("acceptanceCriteria", []) if item)
        current = task_state.get("currentUnderstanding")
        if current:
            parts.append(str(current))
    return "\n".join(parts)


def _extract_quoted_texts(text: str) -> list[str]:
    patterns = [
        r"「([^」]{2,40})」",
        r"『([^』]{2,40})』",
        r"“([^”]{2,40})”",
        r"‘([^’]{2,40})’",
        r'"([^"\n]{2,40})"',
        r"`([^`\n]{2,40})`",
    ]
    values: list[str] = []
    for pattern in patterns:
        values.extend(_clean_text(match.group(1)) for match in re.finditer(pattern, text))
    return [value for value in values if _is_useful_text(value)]


def _extract_explicit_text_labels(text: str) -> list[str]:
    patterns = [
        r"(?:标题|主标题|按钮|按钮文案|页面文案|显示文案|提示文案|必须显示|需要显示|包含文字|出现文字)(?:为|是|叫|包含|显示|出现)?[:：]?\s*([^\n，。；;]{2,32})",
        r"(?:show|display|contain|title|button text)\s+['\"]?([^'\"\n,.。；;]{2,32})['\"]?",
    ]
    values: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _clean_text(match.group(1))
            if _is_useful_text(value):
                values.append(value)
    return values


def _selectors_from_text(text: str) -> list[str]:
    lowered = text.lower()
    selectors: list[str] = []
    if _contains_any(lowered, ["按钮", "button", "点击", "提交", "运行", "确认"]):
        selectors.append("button")
    if _contains_any(lowered, ["输入框", "输入", "表单", "textarea", "input", "搜索框"]):
        selectors.append("input, textarea")
    if _contains_any(lowered, ["表格", "table", "列表数据"]):
        selectors.append("table")
    if _contains_any(lowered, ["列表", "list"]):
        selectors.append("ul, ol, [role=\"list\"]")
    if _contains_any(lowered, ["侧边栏", "左侧", "sidebar", "导航", "历史对话"]):
        selectors.append("aside, nav, [role=\"navigation\"]")
    if _contains_any(lowered, ["标题", "主标题", "heading", "headline"]):
        selectors.append("h1, h2, [role=\"heading\"]")
    if _contains_any(lowered, ["实时预览", "预览 iframe", "iframe"]):
        selectors.append("iframe")
    if _contains_any(lowered, ["代码", "文件树", "diff", "patch"]):
        selectors.append("pre, code, [data-file-tree], [data-diff-viewer]")
    return selectors


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _clean_text(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n'\"`「」『』“”‘’，。；;:")
    return value.strip()


def _is_useful_text(value: str) -> bool:
    if not value or len(value) > 40:
        return False
    if value.lower() in {"true", "false", "null", "undefined", "json", "tsx", "jsx"}:
        return False
    return bool(re.search(r"[\w\u4e00-\u9fff]", value))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _unique(values: list[str], limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        result.append(cleaned)
        seen.add(key)
        if len(result) >= limit:
            break
    return result
