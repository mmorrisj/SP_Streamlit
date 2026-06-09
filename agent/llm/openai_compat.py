"""OpenAI-compatible provider with native tool-calling support.

Covers OpenAI itself plus on-prem and gateway servers that speak the OpenAI
Chat Completions API: vLLM, Ollama, Azure OpenAI (via base_url), LiteLLM,
and most enterprise-internal proxies.

Native tool-calling is the default. JSON-fallback parsing lives in
agent/llm/modes.py and is invoked by the orchestrator when
AGENT_LLM_TOOL_MODE=json_fallback.

Env vars (in priority order for credentials):
    AGENT_LLM_API_KEY  > OPENAI_PROJ_API > CLAUDE_KEY
    AGENT_LLM_BASE_URL (optional; omit for api.openai.com)
    AGENT_LLM_MODEL    (default: gpt-4o-mini)
"""
from __future__ import annotations

import json
import os
from typing import Any

from agent.llm.provider import LLMMessage, LLMResponse, Provider, ToolCall


def _resolve_api_key() -> str | None:
    """Resolve the bearer credential for the LLM call.

    In the enterprise enclave the LiteLLM endpoint authenticates by the gateway
    JWT (x-kiosk-gateway-jwt), captured per-request into the shared request
    context — so it takes priority. Static keys are the dev/non-enterprise
    fallback, matching the precedence used elsewhere in the codebase.
    """
    try:
        from shared.utils.request_context import get_gateway_jwt
        gateway_jwt = get_gateway_jwt()
    except Exception:  # pragma: no cover - request_context always importable
        gateway_jwt = None

    return (
        gateway_jwt
        or os.getenv("AGENT_LLM_API_KEY")
        or os.getenv("OPENAI_PROJ_API")
        or os.getenv("CLAUDE_KEY")
        or os.getenv("LITELLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )


# Per-request timeout in seconds. The OpenAI SDK default is 600s, which lets
# a single hung call stall an entire workflow stage for ten minutes. Cap at
# 60s so failures surface fast and the workflow can move on to the next event.
DEFAULT_REQUEST_TIMEOUT = float(os.getenv("AGENT_LLM_REQUEST_TIMEOUT", "60"))


class OpenAICompatProvider(Provider):
    name = "openai_compat"

    def __init__(self) -> None:
        # Fall back to the enterprise LiteLLM endpoint/model so the agent works
        # out of the box against the same LLM the rest of the app uses, without
        # requiring separate AGENT_LLM_* config.
        self.base_url = os.getenv("AGENT_LLM_BASE_URL") or os.getenv("LITELLM_URL") or None
        self.model = os.getenv("AGENT_LLM_MODEL") or os.getenv("LITELLM_MODEL") or "gpt-4o-mini"

    def _get_client(self):
        # Built per call (not cached): the gateway JWT is per-request, so a
        # cached client would pin a stale token across requests.
        from openai import OpenAI

        api_key = _resolve_api_key()
        if not api_key:
            raise RuntimeError(
                "No LLM credential found: gateway JWT (x-kiosk-gateway-jwt) was not "
                "present and no static key (AGENT_LLM_API_KEY / OPENAI_PROJ_API / "
                "LITELLM_API_KEY) is set."
            )
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": DEFAULT_REQUEST_TIMEOUT,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return OpenAI(**kwargs)

    def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        client = self._get_client()

        api_messages = [_to_api_message(m) for m in messages]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        completion = client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        msg = choice.message

        return LLMResponse(
            text=msg.content or "",
            tool_calls=_extract_tool_calls(msg),
            finish_reason=choice.finish_reason or "stop",
            raw=completion,
        )


def _to_api_message(m: LLMMessage) -> dict[str, Any]:
    """Translate our LLMMessage into the dict shape the OpenAI SDK expects.

    Tool-result messages need role="tool" and a tool_call_id — that linkage
    is what allows multi-turn tool dispatch to work."""
    if m.role == "tool":
        out: dict[str, Any] = {"role": "tool", "content": m.content}
        if m.tool_call_id:
            out["tool_call_id"] = m.tool_call_id
        if m.name:
            out["name"] = m.name
        return out
    return {"role": m.role, "content": m.content}


def _extract_tool_calls(msg: Any) -> list[ToolCall]:
    raw_calls = getattr(msg, "tool_calls", None) or []
    out: list[ToolCall] = []
    for tc in raw_calls:
        # Provider variants: object with .function.name/.function.arguments
        # OR a dict in the same shape (OpenAI SDK uses pydantic objects).
        try:
            name = tc.function.name
            raw_args = tc.function.arguments or "{}"
            tc_id = tc.id
        except AttributeError:
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            name = fn.get("name")
            raw_args = fn.get("arguments", "{}")
            tc_id = tc.get("id") if isinstance(tc, dict) else None
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except json.JSONDecodeError:
            args = {"_raw": raw_args}
        if not name:
            continue
        out.append(ToolCall(id=tc_id or f"call_{len(out)}", name=name, arguments=args))
    return out
