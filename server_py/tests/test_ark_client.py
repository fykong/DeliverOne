from __future__ import annotations

import urllib.error

import pytest

from server_py.core.env import load_env_file
from server_py.models.ark_client import ArkClient


def test_mock_provider_replies_without_network():
    client = ArkClient()
    reply = client.complete({"provider": "mock"}, [{"role": "user", "content": "你好"}])
    assert "需求确认" in reply
    assert client.last_metrics["totalTokens"] > 0


def test_missing_api_key_message_mentions_env_file(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    client = ArkClient()
    model = {"provider": "ark", "endpoint": "https://example.com", "apiKeyEnv": "ARK_API_KEY"}
    with pytest.raises(RuntimeError, match=".env"):
        client.complete(model, [{"role": "user", "content": "hi"}])


def test_retry_on_url_error_then_raise(monkeypatch):
    client = ArkClient()
    client.RETRY_BACKOFF_SECONDS = (0.0,)
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    model = {"provider": "ark", "endpoint": "https://example.com", "apiKeyEnv": "ARK_API_KEY"}
    with pytest.raises(RuntimeError, match="网络"):
        client.complete(model, [{"role": "user", "content": "hi"}])
    assert calls["count"] == 2  # 1 次原始 + 1 次重试


def test_client_error_not_retried(monkeypatch):
    client = ArkClient()
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise urllib.error.HTTPError("https://example.com", 401, "unauthorized", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("ARK_API_KEY", "bad-key")
    model = {"provider": "ark", "endpoint": "https://example.com", "apiKeyEnv": "ARK_API_KEY"}
    with pytest.raises(RuntimeError, match="401"):
        client.complete(model, [{"role": "user", "content": "hi"}])
    assert calls["count"] == 1


def test_env_file_loading(tmp_path, monkeypatch):
    monkeypatch.delenv("SMOKE_TEST_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text('SMOKE_TEST_KEY="abc123"\n# comment\nEXISTING=新值\n', encoding="utf-8")
    monkeypatch.setenv("EXISTING", "原值")
    loaded = load_env_file(env_file)
    assert loaded["SMOKE_TEST_KEY"] == "abc123"
    import os

    assert os.environ["SMOKE_TEST_KEY"] == "abc123"
    # .env 优先:演示机残留的系统级旧 key 不能覆盖项目配置
    assert os.environ["EXISTING"] == "新值"
