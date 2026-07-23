# `agent/` â€” Conversational Analyst Assistant + Report Workflow

The in-app Agent (React page at `/agent`) is a **conversational analyst
assistant**: the model interprets the question, pulls data with tools, and
answers in whatever form the question calls for. The full validated report
pipeline is offered as an explicit action, never run as a side effect.

> An earlier version of this README described the subsystem as stubbed.
> That is outdated â€” the providers, all tools, the ReAct loop, and all 12
> report stages perform real DB queries and LLM calls.

## Execution paths

| Endpoint | What it is | Used by |
|---|---|---|
| `POST /api/agent/converse/stream` | **Primary UX.** Multi-turn conversational ReAct loop over the doctrine tool registry; SSE-streams `tool_call` / `tool_result` / `report_offer` / `answer` / `sources` events | Agent page |
| `POST /api/agent/workflows/report/stream` | Fixed 12-stage validated report DAG (retrieval â†’ narration â†’ sourcing â†’ QA â†’ hallucination validation), SSE per stage | Agent page, via the report-offer card |
| `POST /api/agent/analyze` | Single-shot ReAct loop returning a structured Briefing | legacy/programmatic |
| `POST /api/agent/chat` | Single-call intent classifier (scope form filler) | legacy (no longer used by the UI) |

## Tool registries (`agent/tools/`)

`get_converse_registry()` â€” data-pull tools only (the model composes answers
itself). The doctrine tools bake in the platform's bias controls so the agent
cannot accidentally build answers on raw, Iran-inflated counts:

- **Doctrine / derived analytics** (prefer the `analytics` schema, degrade to
  raw tables when it isn't built):
  `provenance_stats` (self-reported vs third-party split),
  `initiative_ledger` (corroboration-gated named initiatives),
  `activity_series` (monthly tempo + detected changepoints),
  `search_insight_reports` (the verified reports in `docs/reports/`)
- **Corpus retrieval:** `document_search` (hybrid, via
  `services/chat/rag_service.intelligent_search`), `entity_lookup`,
  `entity_graph`, `event_timeline`, `bilateral_context`,
  `citation_resolver`, `materiality_filter`, `corroboration_check`,
  `country_grouping`
- **Action offer:** `propose_report` â€” validates a report scope and emits a
  `report_offer` event; the pipeline only runs when the analyst clicks.

`get_registry()` â€” the original set (includes briefing/writing synthesis
tools), still used by `/analyze`.

## Key modules

- `orchestrator.py` â€” `converse()` (streaming multi-turn loop, primary),
  `analyze()` (single-shot briefing), `classify_intent()` (legacy). Every
  tool call is persisted to `agent_tool_calls`; runs to `agent_runs`.
- `prompts.py` â€” `CONVERSE_SYSTEM_TEMPLATE` carries the analytic doctrine
  (volume â‰  activity, corroborated-initiative gate, check verified reports
  first, cite only tool-returned facts).
- `llm/` â€” provider abstraction; `openai_compat` (real; OpenAI/LiteLLM,
  per-request gateway-JWT auth). `anthropic.py` / `modes.json_fallback`
  remain unimplemented â€” only reachable via non-default env values.
- `workflows/report/` â€” the 12-stage DAG (all stages implemented).

## Configuration

| Env | Default | Notes |
|---|---|---|
| `DISABLE_AGENT` | unset | `true` skips mounting the router entirely |
| `AGENT_LLM_MODEL` | `gpt-4.1-mini` | falls back to `LITELLM_MODEL` |
| `AGENT_LLM_BASE_URL` | unset | falls back to `LITELLM_URL`, else api.openai.com |
| `AGENT_MAX_TURNS` | `24` | tool-call budget per turn |
| `AGENT_LLM_REQUEST_TIMEOUT` | `60` | seconds per LLM call |

The router is mounted defensively in `server/main.py` (a broken import cannot
take down the API).

## Known gaps

- `category_mode="breakdown"` on the report workflow is accepted but treated
  as `flat` (reserved Phase 2).
- Region resolution maps any region name to the config's recipient list
  (effectively Middle East) until `config.yaml` grows a `regions:` mapping.
- `/analyze` and `/chat` are retained for compatibility; the UI uses
  `/converse/stream` exclusively.
