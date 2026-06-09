"""Tests for the agent LLM provider's enterprise wiring.

The agent page's endpoints (/chat, /workflows/report/stream) drive the LLM
through OpenAICompatProvider. In the enterprise enclave it must authenticate
to the LiteLLM endpoint with the gateway JWT (no static API key), and resolve
that credential per request (the JWT changes between requests, so the client
must not be cached with a stale token).
"""
import sys
import types

import pytest

from shared.utils.request_context import set_gateway_jwt


@pytest.fixture(autouse=True)
def _clear_ctx():
    set_gateway_jwt(None)
    yield
    set_gateway_jwt(None)


def _install_fake_openai(monkeypatch):
    """Patch `openai.OpenAI` to capture constructor kwargs and avoid network."""
    captured = {"clients": []}
    fake_openai = types.ModuleType("openai")

    class _Completions:
        def create(self, **kwargs):
            msg = types.SimpleNamespace(content="hello", tool_calls=None)
            choice = types.SimpleNamespace(message=msg, finish_reason="stop")
            return types.SimpleNamespace(choices=[choice])

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None, **kwargs):
            captured["clients"].append({"api_key": api_key, "base_url": base_url})
            self.chat = types.SimpleNamespace(completions=_Completions())

    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    return captured


def _msg():
    from agent.llm.provider import LLMMessage
    return [LLMMessage(role="user", content="hi")]


def test_provider_uses_gateway_jwt_and_litellm_url(monkeypatch):
    from agent.llm.openai_compat import OpenAICompatProvider

    monkeypatch.setenv("LITELLM_URL", "https://enterprise/v1")
    monkeypatch.setenv("LITELLM_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("AGENT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_PROJ_API", raising=False)
    monkeypatch.delenv("CLAUDE_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    captured = _install_fake_openai(monkeypatch)

    set_gateway_jwt("gw-jwt-1")
    provider = OpenAICompatProvider()
    resp = provider.complete(_msg())

    assert resp.text == "hello"
    assert captured["clients"][-1]["api_key"] == "gw-jwt-1"
    assert captured["clients"][-1]["base_url"] == "https://enterprise/v1"


def test_provider_resolves_jwt_per_request_no_stale_cache(monkeypatch):
    from agent.llm.openai_compat import OpenAICompatProvider

    monkeypatch.setenv("LITELLM_URL", "https://enterprise/v1")
    captured = _install_fake_openai(monkeypatch)
    provider = OpenAICompatProvider()

    set_gateway_jwt("jwt-req-A")
    provider.complete(_msg())
    set_gateway_jwt("jwt-req-B")
    provider.complete(_msg())

    keys = [c["api_key"] for c in captured["clients"]]
    assert keys == ["jwt-req-A", "jwt-req-B"]  # not pinned to the first request


def test_provider_falls_back_to_static_key_without_jwt(monkeypatch):
    from agent.llm.openai_compat import OpenAICompatProvider

    monkeypatch.delenv("LITELLM_URL", raising=False)
    monkeypatch.setenv("AGENT_LLM_API_KEY", "static-key")
    captured = _install_fake_openai(monkeypatch)

    set_gateway_jwt(None)
    OpenAICompatProvider().complete(_msg())
    assert captured["clients"][-1]["api_key"] == "static-key"


def test_provider_raises_without_any_credential(monkeypatch):
    from agent.llm.openai_compat import OpenAICompatProvider

    for var in ("AGENT_LLM_API_KEY", "OPENAI_PROJ_API", "CLAUDE_KEY",
                "LITELLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    _install_fake_openai(monkeypatch)
    set_gateway_jwt(None)

    with pytest.raises(RuntimeError, match="No LLM credential"):
        OpenAICompatProvider().complete(_msg())
