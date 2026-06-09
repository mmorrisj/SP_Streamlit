# `agent/` — EXPERIMENTAL (not demo-ready)

> ⚠️ **Status: experimental / incomplete. Do not demo or rely on this in
> production.** This package is an in-progress OSINT-style agent (planner →
> tools → briefing). Several pieces are stubs (`TODO`): LLM providers
> (`agent/llm/`), most tool bodies (`agent/tools/`), and the briefing
> generation in `agent/router.py`.

## Why it's safe to leave mounted

The agent router is included **defensively** in `server/main.py`:

```python
try:
    from agent.router import router as agent_router
    app.include_router(agent_router)
except Exception as _agent_err:  # pragma: no cover - defensive
    logging.getLogger(__name__).warning("agent router not loaded: %s", _agent_err)
```

A broken import here cannot take down the foundational API. Endpoints under
`/api/agent/*` currently return static/placeholder results.

## Disabling it entirely

To keep it out of a build (e.g. for the demo), set the environment variable
and the router will be skipped:

```bash
DISABLE_AGENT=true
```

`server/main.py` honors this flag and skips mounting the router when set.

## Handoff decision needed

Per `docs/MAINTAINABILITY_ASSESSMENT.md` (§4), the maintainer should make an
explicit call before October: **finish** this subsystem, **move it to a
feature branch / separate repo**, or **keep it dormant behind the flag above**.
It should not be handed off in an ambiguous half-implemented state.
