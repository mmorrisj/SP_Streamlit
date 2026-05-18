"""Tool protocol: every MCP-style tool implements this interface.

The base class produces two parallel schema views — JSON-Schema (OpenAI-style)
and Anthropic-style — so the orchestrator can drive either provider without
per-tool conditional logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    citations: list[str] = field(default_factory=list)
    summary: str | None = None  # short human-readable line for the workflow trace


class Tool(ABC):
    """Base class for all agent tools."""

    name: str
    description: str
    input_schema: dict[str, Any]
    foundation_dependency: str | None = None

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool. Implementations should be deterministic and side-effect free
        on the foundation services (read-only by default)."""
        raise NotImplementedError

    # ----- schema adapters --------------------------------------------------

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def as_anthropic_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
