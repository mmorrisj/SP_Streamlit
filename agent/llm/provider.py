"""Provider-agnostic LLM gateway.

The agent must run against both commercial APIs (OpenAI, Anthropic) and
customer-hosted enterprise LLMs (vLLM, Ollama, internal OpenAI-compatible
gateways). This module exposes a single `Provider` protocol and a factory
that selects an implementation from environment variables.

Env vars:
    AGENT_LLM_PROVIDER   one of: openai | anthropic | openai_compat
    AGENT_LLM_MODEL      model id (provider-specific)
    AGENT_LLM_BASE_URL   override endpoint (required for openai_compat)
    AGENT_LLM_API_KEY    api key (optional for on-prem deployments)
    AGENT_LLM_TOOL_MODE  native | json_fallback   default: native

Tool execution supports two modes:
    - native       : model returns tool_calls; orchestrator dispatches
    - json_fallback: model returns plain text JSON {"tool": "...", "args": {...}}
                     parsed by the orchestrator. Use for models without
                     native tool-calling support.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LLMMessage:
    role: str  # system | user | assistant | tool
    content: str
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    raw: Any = None


class Provider(Protocol):
    name: str

    def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        ...


def get_provider() -> Provider:
    """Factory: read env and return the configured provider.

    TODO: Implement provider classes in agent/llm/openai_compat.py and
    agent/llm/anthropic.py. This scaffolding returns a stub provider so the
    package imports cleanly before any provider is wired.
    """
    provider_name = os.getenv("AGENT_LLM_PROVIDER", "openai_compat").lower()

    if provider_name == "anthropic":
        from agent.llm.anthropic import AnthropicProvider
        return AnthropicProvider()
    if provider_name in ("openai", "openai_compat"):
        from agent.llm.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider()

    raise ValueError(f"Unknown AGENT_LLM_PROVIDER: {provider_name!r}")


def get_tool_mode() -> str:
    return os.getenv("AGENT_LLM_TOOL_MODE", "native").lower()
