from server_py.models.budget_guard import TRIM_MARKER, estimate_tokens, fit_messages


def test_estimate_tokens_cjk_heavier_than_ascii():
    cjk = estimate_tokens("需求" * 100)
    ascii_text = estimate_tokens("ab" * 100)
    assert cjk > ascii_text
    assert estimate_tokens("") == 0


def test_fit_messages_under_budget_untouched():
    messages = [
        {"role": "system", "content": "角色规则"},
        {"role": "user", "content": "短需求"},
    ]
    fitted, report = fit_messages(messages, 10000)
    assert fitted == messages
    assert report["trimmed"] is False


def test_fit_messages_trims_largest_keeps_head_and_tail():
    head_text = "HEAD开头标记" + "中" * 6000
    tail_text = "尾" * 2000 + "TAIL结尾标记"
    big = head_text + "废" * 30000 + tail_text
    messages = [
        {"role": "system", "content": "角色规则,必须完整保留"},
        {"role": "user", "content": big},
    ]
    fitted, report = fit_messages(messages, 8000)
    assert report["trimmed"] is True
    assert report["inputTokensAfter"] <= 8000
    # system 不动,截的是最大的 user 消息中段,头尾保留
    assert fitted[0]["content"] == messages[0]["content"]
    assert TRIM_MARKER in fitted[1]["content"]
    assert fitted[1]["content"].startswith("HEAD开头标记")
    assert fitted[1]["content"].endswith("TAIL结尾标记")
