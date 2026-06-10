from __future__ import annotations

import re
from typing import Any

CJK_RE = re.compile(r"[一-鿿　-〿＀-￯]")

# 发送前最后一道闸门的安全余量:估算偏差 + 协议开销。
SAFETY_MARGIN_TOKENS = 2048
# 截断时保留的头/尾比例:头部带任务定义和高优先级证据,尾部带 expectedJson/最新结果。
HEAD_RATIO = 0.72
TAIL_RATIO = 0.16
TRIM_MARKER = "\n…………【上下文超预算,中段已按头尾保留策略截断;关键结论以保留部分为准】…………\n"


def estimate_tokens(text: str) -> int:
    """粗估 token 数,只为预算判断,不求精确。

    doubao 分词器对中文约 1 字/token,ASCII 约 3.5 字符/token。
    故意往大估(宁可多裁不可超限):中文按 1.05、其余按 3.2 折算。
    """
    if not text:
        return 0
    cjk = len(CJK_RE.findall(text))
    other = len(text) - cjk
    return int(cjk * 1.05 + other / 3.2) + 1


def fit_messages(
    messages: list[dict[str, str]],
    max_input_tokens: int,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """发送前的全局预算守卫:整组消息超预算时截最大那条的中段。

    各字段的局部上限(stdoutTail/召回条目等)是第一道防线;这里是最后一道,
    防止证据异常膨胀(超大 diff、超长审计)把请求顶爆。截断保留头+尾:
    头部是任务与角色规则,尾部通常是 expectedJson 与最新结果,中段最可弃。
    """
    total = sum(estimate_tokens(message.get("content", "")) for message in messages)
    report: dict[str, Any] = {"inputTokensEstimated": total, "budget": max_input_tokens, "trimmed": False}
    if total <= max_input_tokens or not messages:
        return messages, report

    fitted = [dict(message) for message in messages]
    # 永远只截内容最大的那条(通常是携带 payload 的 user 消息),
    # system 角色规则与小消息保持完整。
    for _ in range(4):
        total = sum(estimate_tokens(message.get("content", "")) for message in fitted)
        if total <= max_input_tokens:
            break
        largest = max(fitted, key=lambda message: len(message.get("content", "")))
        content = largest.get("content", "")
        overshoot_tokens = total - max_input_tokens
        # token 超额换算回字符数(保守 1 token≈1.2 字符,中文场景偏多裁)。
        excess_chars = int(overshoot_tokens * 1.2) + len(TRIM_MARKER)
        keep = len(content) - excess_chars
        if keep < 2000:
            keep = 2000
        head = int(keep * (HEAD_RATIO / (HEAD_RATIO + TAIL_RATIO)))
        tail = keep - head
        if head + tail >= len(content):
            break
        largest["content"] = content[:head] + TRIM_MARKER + content[len(content) - tail :]
        report["trimmed"] = True

    report["inputTokensAfter"] = sum(estimate_tokens(message.get("content", "")) for message in fitted)
    if report["trimmed"]:
        report["trimmedTokens"] = report["inputTokensEstimated"] - report["inputTokensAfter"]
    return fitted, report
