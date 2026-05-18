"""Anthropic provider.

TODO: Implement complete() using the `anthropic` SDK Messages API with
native tool_use blocks normalized into LLMResponse.tool_calls.
"""
from __future__ import annotations

import os
from typing import Any

from agent.llm.provider import LLMMessage, LLMResponse, Provider


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self) -> None:
        self.api_key = os.getenv("AGENT_LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        self.model = os.getenv("AGENT_LLM_MODEL", "claude-sonnet-4-6")

    def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        # TODO: implement
        raise NotImplementedError("AnthropicProvider.complete not yet implemented")
