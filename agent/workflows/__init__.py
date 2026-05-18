"""Structured multi-agent workflows.

Distinct from the open-ended ReAct loop in `agent/orchestrator.py`. A workflow
is a fixed DAG of role-specialized stages; each stage is one LLM call (or
deterministic helper) with a focused system prompt, a typed input/output
contract, and stage-specific tool access. Output of stage N is input to
stage N+1.

Use cases:
  * Report generation (agent/workflows/report/) — recipient + date range -> structured report
  * Future workflows (briefing series, alert triage, etc.)
"""
