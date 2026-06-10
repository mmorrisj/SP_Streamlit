"""Regression tests for multi-turn tool-call message linkage.

OpenAI-compatible servers reject role="tool" messages unless the preceding
assistant message carries a tool_calls list with matching IDs:

    "messages with role 'tool' must be a response to a preceding message
     with 'tool_calls'"

The orchestrator echoes the assistant turn into history before appending tool
results, so that echo must include the tool_calls — and the provider must
serialize them in OpenAI wire format. These tests cover both halves.
"""
import json
import sys
import types

import pytest

from agent.llm.provider import LLMMessage, ToolCall


# ---------------------------------------------------------------------------
# Provider serialization (_to_api_message)
# ---------------------------------------------------------------------------
def test_assistant_message_with_tool_calls_serializes_linkage():
    from agent.llm.openai_compat import _to_api_message

    msg = LLMMessage(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="call_1", name="document_search", arguments={"query": "x"})],
    )
    out = _to_api_message(msg)
    assert out["role"] == "assistant"
    assert out["content"] is None  # API requires null, not "", alongside tool_calls
    tc = out["tool_calls"][0]
    assert tc["id"] == "call_1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "document_search"
    assert json.loads(tc["function"]["arguments"]) == {"query": "x"}


def test_assistant_message_without_tool_calls_unchanged():
    from agent.llm.openai_compat import _to_api_message

    out = _to_api_message(LLMMessage(role="assistant", content="final answer"))
    assert out == {"role": "assistant", "content": "final answer"}


def test_tool_message_keeps_tool_call_id():
    from agent.llm.openai_compat import _to_api_message

    out = _to_api_message(
        LLMMessage(role="tool", content='{"ok": true}', tool_call_id="call_1", name="t")
    )
    assert out["tool_call_id"] == "call_1"


# ---------------------------------------------------------------------------
# Orchestrator loop: end-to-end two-turn history
# ---------------------------------------------------------------------------
class _ScriptedProvider:
    """Turn 1: request a tool call. Turn 2: assert the history is linked,
    then finish."""

    name = "scripted"
    model = "test"

    def __init__(self):
        self.calls = 0
        self.second_turn_messages = None

    def complete(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        from agent.llm.provider import LLMResponse

        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                text="",
                tool_calls=[ToolCall(id="call_9", name="fake_tool", arguments={})],
            )
        self.second_turn_messages = list(messages)
        return LLMResponse(text='{"title": "T", "executive_summary": "S"}')


class _FakeTool:
    name = "fake_tool"
    description = "test tool"
    input_schema = {"type": "object", "properties": {}}
    foundation_dependency = None

    def as_openai_tool(self):
        return {"type": "function", "function": {"name": self.name, "parameters": self.input_schema}}

    def run(self, **kwargs):
        from agent.tools.base import ToolResult
        return ToolResult(ok=True, data={"hit": 1}, summary="ok")


def test_orchestrator_echoes_tool_calls_into_history(monkeypatch):
    from agent.orchestrator import Orchestrator, _RunCtx
    from agent.schemas import AnalyzeRequest
    from uuid import uuid4

    orch = Orchestrator.__new__(Orchestrator)  # skip __init__ registry load
    orch.tools = {"fake_tool": _FakeTool()}
    # Persistence is best-effort and import-guarded; let it no-op against a
    # missing DB rather than mocking it.
    monkeypatch.setattr(Orchestrator, "_insert_tool_call", lambda self, **kw: None)

    provider = _ScriptedProvider()
    ctx = _RunCtx(run_id=uuid4(), request=AnalyzeRequest(query="q"))
    briefing = orch._run_loop(ctx, provider)

    assert provider.calls == 2
    history = provider.second_turn_messages
    # Find the echoed assistant turn and the tool result that follows it.
    assistant_idx = next(
        i for i, m in enumerate(history) if m.role == "assistant" and m.tool_calls
    )
    assert history[assistant_idx].tool_calls[0].id == "call_9"
    tool_msg = history[assistant_idx + 1]
    assert tool_msg.role == "tool"
    assert tool_msg.tool_call_id == "call_9"
    assert briefing is not None and briefing.title == "T"
