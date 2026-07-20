"""OpenAI-compatible provider with native tool-calling support.

Covers OpenAI itself plus on-prem and gateway servers that speak the OpenAI
Chat Completions API: vLLM, Ollama, Azure OpenAI (via base_url), LiteLLM,
and most enterprise-internal proxies.

Native tool-calling is the default. JSON-fallback parsing lives in
agent/llm/modes.py and is invoked by the orchestrator when
AGENT_LLM_TOOL_MODE=json_fallback.

Routing is proxy-first (see resolve_source() for the full contract):
    AGENT_LLM_BASE_URL     -> direct to that URL (explicit dev/ops override)
    AGENT_LLM_SOURCE       -> proxy | litellm | openai | direct
    GAI_DEFAULT_SOURCE     -> same values (shared with gai())
    default                -> proxy: POST {API_URL}/proxy_chat

Credentials (direct/litellm modes; the proxy holds its own in proxy mode):
    gateway JWT > AGENT_LLM_API_KEY > OPENAI_PROJ_API > CLAUDE_KEY
    > LITELLM_API_KEY > OPENAI_API_KEY
Model: AGENT_LLM_MODEL > LITELLM_MODEL > proxy default (gpt-4.1-mini direct).
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
# a single hung call stall an entire workflow stage for ten minutes. The
# default must stay ABOVE the proxy's worst case — /proxy_chat tries up to two
# backends at 90s each (~180s) — or slow-but-successful completions get
# abandoned client-side while still billing server-side.
DEFAULT_REQUEST_TIMEOUT = float(os.getenv("AGENT_LLM_REQUEST_TIMEOUT", "240"))


def resolve_source() -> str:
    """Resolve the LLM routing source, matching the contract the rest of the
    app uses (shared/utils/utils.py::gai).

    Priority:
      AGENT_LLM_BASE_URL set        -> "direct" (explicit dev/ops override)
      AGENT_LLM_SOURCE              -> as given
      GAI_DEFAULT_SOURCE            -> as given (proxy|litellm|azure|openai)
      default                       -> "proxy" (same default as gai())

    "azure" is served via the proxy (the proxy's routing already handles the
    Azure branch), so it maps to "proxy" here. A "proxy" resolution without
    API_URL falls back to "direct" with a warning so bare dev keeps working.
    """
    if os.getenv("AGENT_LLM_BASE_URL"):
        return "direct"
    source = (os.getenv("AGENT_LLM_SOURCE") or os.getenv("GAI_DEFAULT_SOURCE") or "proxy").lower()
    if source == "azure":
        source = "proxy"
    if source == "proxy" and not (os.getenv("API_URL") or "").strip():
        import logging
        logging.getLogger(__name__).warning(
            "agent LLM source resolved to 'proxy' but API_URL is unset; "
            "falling back to direct LLM access"
        )
        return "direct"
    return source


class OpenAICompatProvider(Provider):
    name = "openai_compat"

    def __init__(self) -> None:
        # Route the same way the rest of the app does (gai()): proxy by
        # default, LiteLLM/OpenAI when configured. On enterprise deployments
        # only the proxy has LLM egress — the agent must never assume direct
        # connectivity.
        self.source = resolve_source()
        # In proxy mode only an explicitly configured model is sent — when
        # neither env is set the payload omits it so the proxy applies its own
        # LITELLM_MODEL/default (the proxy may know the approved model name
        # when this container does not).
        self.configured_model = (
            os.getenv("AGENT_LLM_MODEL") or os.getenv("LITELLM_MODEL") or None
        )
        self.model = self.configured_model or "gpt-4.1-mini"
        if self.source == "litellm":
            self.base_url = (os.getenv("LITELLM_URL") or "").strip() or None
            if not self.base_url:
                raise RuntimeError(
                    "agent LLM source is 'litellm' but LITELLM_URL is not set"
                )
        elif self.source == "direct":
            self.base_url = os.getenv("AGENT_LLM_BASE_URL") or os.getenv("LITELLM_URL") or None
        else:  # "openai" or "proxy"
            self.base_url = None
        self.proxy_url = (os.getenv("API_URL") or "").strip().rstrip("/")

    @property
    def target(self) -> str:
        """Human-readable description of where LLM calls go (for /health)."""
        if self.source == "proxy":
            return f"{self.proxy_url}/proxy_chat"
        return self.base_url or "https://api.openai.com"

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
        api_messages = [_to_api_message(m) for m in messages]

        if self.source == "proxy":
            return self._complete_via_proxy(api_messages, tools, temperature, max_tokens)

        client = self._get_client()
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

    def _complete_via_proxy(
        self,
        api_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Route through the app's LLM proxy (/proxy_chat) — the same egress
        path gai(source='proxy') uses, extended for tool-calling. The gateway
        JWT is forwarded as a header so the proxy can authenticate the
        downstream LiteLLM call."""
        import requests

        payload: dict[str, Any] = {
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.configured_model:
            payload["model"] = self.configured_model
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {}
        try:
            from shared.utils.request_context import ENTERPRISE_JWT_HEADER, get_gateway_jwt
            jwt = get_gateway_jwt()
            if jwt:
                headers[ENTERPRISE_JWT_HEADER] = jwt
        except Exception:  # pragma: no cover
            pass

        url = f"{self.proxy_url}/proxy_chat"
        try:
            resp = requests.post(url, json=payload, headers=headers,
                                 timeout=DEFAULT_REQUEST_TIMEOUT)
        except requests.RequestException as e:
            raise RuntimeError(
                f"LLM proxy unreachable at {url}: {e}. Check API_URL points at a "
                f"proxy serving /proxy_chat (server/main.py or scripts/llm_proxy.py)."
            ) from e
        if resp.status_code != 200:
            raise RuntimeError(
                f"LLM proxy call failed ({resp.status_code}) at {url}: {resp.text[:300]}"
            )
        completion = resp.json()
        choices = completion.get("choices") or []
        if not choices:
            raise RuntimeError(f"LLM proxy returned no choices: {str(completion)[:300]}")
        msg = choices[0].get("message") or {}
        return LLMResponse(
            text=msg.get("content") or "",
            tool_calls=_extract_tool_calls(msg),
            finish_reason=choices[0].get("finish_reason") or "stop",
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
    if m.role == "assistant" and m.tool_calls:
        return {
            "role": "assistant",
            # The API requires content to be null (not "") when tool_calls are set.
            "content": m.content or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in m.tool_calls
            ],
        }
    return {"role": m.role, "content": m.content}


def _extract_tool_calls(msg: Any) -> list[ToolCall]:
    # msg is an SDK object (attribute access) on direct paths, or a plain dict
    # when the completion came back as JSON from the /proxy_chat passthrough.
    if isinstance(msg, dict):
        raw_calls = msg.get("tool_calls") or []
    else:
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
            # `or "{}"` (not a .get default): gateways may send arguments=null,
            # and the key existing means the default never applies.
            raw_args = fn.get("arguments") or "{}"
            tc_id = tc.get("id") if isinstance(tc, dict) else None
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except (json.JSONDecodeError, TypeError, ValueError):
            args = {"_raw": raw_args}
        if not name:
            continue
        out.append(ToolCall(id=tc_id or f"call_{len(out)}", name=name, arguments=args))
    return out
