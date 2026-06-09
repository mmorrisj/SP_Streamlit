"""Tests for enterprise gateway JWT forwarding to the LiteLLM endpoint.

Covers the three pieces of the fix:
1. The request-context contextvar (set/get/clear).
2. The pure-ASGI middleware propagating the JWT to a sync endpoint (the
   propagation that BaseHTTPMiddleware would have broken).
3. gai(source="litellm") gating on LITELLM_URL alone and using the gateway
   JWT (not an API key) as the bearer credential.
"""
import sys
import types

import pytest

# shared/utils/utils.py imports `openai` at module top. The package is present
# in CI but may be absent in a bare dev env; inject a minimal stub so the module
# (and these tests) import either way. Per-test fakes (below) override this to
# capture the bearer credential gai() constructs its client with.
if "openai" not in sys.modules:
    try:  # pragma: no cover - prefer the real package when installed
        import openai  # noqa: F401
    except ModuleNotFoundError:
        _stub = types.ModuleType("openai")
        _stub.OpenAI = object
        _stub.AzureOpenAI = object
        sys.modules["openai"] = _stub

from shared.utils.request_context import (
    ENTERPRISE_JWT_HEADER,
    GatewayJWTMiddleware,
    get_gateway_jwt,
    set_gateway_jwt,
)


@pytest.fixture(autouse=True)
def _clear_ctx():
    set_gateway_jwt(None)
    yield
    set_gateway_jwt(None)


def test_contextvar_set_get_clear():
    assert get_gateway_jwt() is None
    set_gateway_jwt("jwt-abc")
    assert get_gateway_jwt() == "jwt-abc"
    set_gateway_jwt("")  # empty string clears
    assert get_gateway_jwt() is None


def test_middleware_propagates_jwt_including_threadpool():
    """The JWT captured by the ASGI middleware must be visible both in the
    async context and after dispatch to the threadpool — the latter is how
    Starlette runs *sync* route handlers (where in-process gai() calls live).

    Driven at the raw-ASGI level to avoid the HTTP test client (the broken
    starlette.testclient in some envs needs httpx2)."""
    anyio = pytest.importorskip("anyio")
    from starlette.concurrency import run_in_threadpool

    captured = {}

    async def inner_app(scope, receive, send):
        captured["async"] = get_gateway_jwt()
        captured["thread"] = await run_in_threadpool(get_gateway_jwt)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = GatewayJWTMiddleware(inner_app)

    async def drive(headers):
        async def receive():
            return {"type": "http.request"}

        async def send(_msg):
            return None

        await mw({"type": "http", "headers": headers}, receive, send)

    anyio.run(drive, [(ENTERPRISE_JWT_HEADER.encode(), b"tok-123")])
    assert captured["async"] == "tok-123"
    assert captured["thread"] == "tok-123"  # propagated across the threadpool boundary

    captured.clear()
    anyio.run(drive, [])  # no header -> cleared, not leaked from prior request
    assert captured["async"] is None
    assert captured["thread"] is None


def _install_fake_openai(monkeypatch, captured):
    """Patch `openai.OpenAI` so gai() doesn't make a network call and we can
    capture the api_key (bearer) it was constructed with."""
    fake_openai = types.ModuleType("openai")

    class _FakeCompletions:
        def create(self, **kwargs):
            msg = types.SimpleNamespace(content='{"ok": true}')
            choice = types.SimpleNamespace(message=msg)
            return types.SimpleNamespace(choices=[choice])

    class _FakeChat:
        def __init__(self):
            self.completions = _FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None, **kwargs):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = _FakeChat()

    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)


def test_gai_litellm_uses_gateway_jwt_without_api_key(monkeypatch):
    from shared.utils import utils

    monkeypatch.setenv("LITELLM_URL", "https://enterprise/v1")
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)

    captured = {}
    _install_fake_openai(monkeypatch, captured)

    set_gateway_jwt("gateway-jwt-xyz")
    result = utils.gai("sys", "user", model="gpt-4o-mini", source="litellm")

    # JWT (not an API key) was used as the bearer; URL alone enabled the path.
    assert captured["api_key"] == "gateway-jwt-xyz"
    assert captured["base_url"] == "https://enterprise/v1"
    assert result == {"ok": True}


def test_gai_litellm_explicit_jwt_arg_wins(monkeypatch):
    from shared.utils import utils

    monkeypatch.setenv("LITELLM_URL", "https://enterprise/v1")
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    captured = {}
    _install_fake_openai(monkeypatch, captured)

    set_gateway_jwt("ctx-jwt")
    utils.gai("sys", "user", source="litellm", jwt="explicit-jwt")
    assert captured["api_key"] == "explicit-jwt"


def test_gai_litellm_raises_when_no_credential(monkeypatch):
    from shared.utils import utils

    monkeypatch.setenv("LITELLM_URL", "https://enterprise/v1")
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    _install_fake_openai(monkeypatch, {})
    set_gateway_jwt(None)

    with pytest.raises(ValueError, match="No credential for LiteLLM"):
        utils.gai("sys", "user", source="litellm")
