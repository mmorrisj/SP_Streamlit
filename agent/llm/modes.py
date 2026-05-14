"""Tool-call dispatch helpers.

Two execution modes are supported so the agent works against models with and
without native tool-calling:

- native        : parse provider-returned tool_calls
- json_fallback : prompt the model to emit `{"tool": "...", "args": {...}}`
                  and parse that JSON ourselves

TODO: Implement parse_native_tool_calls() and parse_json_fallback().
"""
from __future__ import annotations

import json
import re
from typing import Any

from agent.llm.provider import ToolCall


JSON_FALLBACK_INSTRUCTIONS = """\
When you need to call a tool, respond with ONLY a JSON object of the form:
{"tool": "<tool_name>", "args": {<arguments>}}
Do not include any prose, code fences, or commentary. When you are done calling
tools and ready to write the briefing, respond with:
{"tool": "final_answer", "args": {"text": "<your response>"}}
"""


def parse_json_fallback(text: str) -> ToolCall | None:
    """Best-effort extract a single JSON tool-call from model text."""
    # TODO: harden against code fences and trailing prose
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    name = obj.get("tool")
    args = obj.get("args", {})
    if not isinstance(name, str) or not isinstance(args, dict):
        return None
    return ToolCall(id="fallback-0", name=name, arguments=args)


def normalize_tool_call(raw: Any) -> ToolCall:
    """Normalize a provider-specific tool-call object into our ToolCall dataclass."""
    # TODO: implement per-provider normalization
    raise NotImplementedError
