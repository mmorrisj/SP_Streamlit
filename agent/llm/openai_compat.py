"""OpenAI-compatible provider.

Covers OpenAI itself plus most enterprise gateways and on-prem servers that
speak the OpenAI Chat Completions API (vLLM, Ollama, Azure OpenAI, internal
proxies, etc.).

TODO: Implement complete() using the `openai` SDK with base_url override,
including tool-call response normalization into LLMResponse.tool_calls.
"""
from __future__ import annotations

import os
from typing import Any

from agent.llm.provider import LLMMessage, LLMResponse, Provider


class OpenAICompatProvider(Provider):
    name = "openai_compat"

    def __init__(self) -> None:
        self.base_url = os.getenv("AGENT_LLM_BASE_URL")  # optional for openai.com
        self.api_key = os.getenv("AGENT_LLM_API_KEY") or os.getenv("CLAUDE_KEY")
        self.model = os.getenv("AGENT_LLM_MODEL", "gpt-4o-mini")

    def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        # TODO: implement
        raise NotImplementedError("OpenAICompatProvider.complete not yet implemented")
