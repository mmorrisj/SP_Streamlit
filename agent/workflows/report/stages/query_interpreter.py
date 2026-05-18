"""Stage 1: Query Interpreter.

Reads the raw workflow inputs (recipient/region/influencer/date range) and
decides:
  * scope: bilateral if (recipient AND influencer) else regional
  * normalized country names, normalized date range
  * a one-sentence rationale for downstream stages to reference

When a region is supplied, expand it into the explicit recipient list
defined in shared/config/config.yaml so downstream SQL stages can scope
their queries with WHERE recipient IN (...) instead of treating "regional"
as "any recipient on the planet".

LLM role: small judgment call (resolve ambiguity, normalize aliases).
TODO: replace stub with an LLM call once a deterministic helper isn't enough.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from agent.workflows.base import Stage, StageResult, WorkflowContext


_CONFIG_PATH = Path(__file__).resolve().parents[4] / "shared" / "config" / "config.yaml"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    """Load shared/config/config.yaml once per process."""
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _resolve_region_recipients(region: str | None) -> list[str] | None:
    """Map a region label to the explicit list of recipient countries.

    Phase 1: the config carries a single flat `recipients` list that
    implicitly defines the Middle East scope. Any non-empty region value
    resolves to this list. When additional regions are added to the
    config (e.g. as a `regions: {Middle East: [...], Africa: [...]}`
    mapping), extend this function to dispatch by key.
    """
    if not region:
        return None
    cfg = _load_config()
    recipients = cfg.get("recipients") or []
    return [str(r) for r in recipients] if recipients else None


class QueryInterpreterStage(Stage):
    name = "query_interpreter"
    description = "Resolve scope (bilateral vs regional) and normalize inputs."
    required = True
    depends_on: list[str] = []

    def run(self, ctx: WorkflowContext) -> StageResult:
        inp = ctx.inputs
        recipient = (inp.get("recipient") or "").strip() or None
        influencer = (inp.get("influencer") or "").strip() or None
        region = (inp.get("region") or "").strip() or None
        category = (inp.get("category") or "").strip() or None
        subcategory = (inp.get("subcategory") or "").strip() or None
        # category_mode: "flat" (no filter), "filter" (single-category scope),
        # or "breakdown" (planned for Phase 2 — currently treated as "flat").
        category_mode = (inp.get("category_mode") or "flat").strip() or "flat"

        # In "flat" / "breakdown" mode, we ignore the category param even if
        # supplied — it's just metadata at that point. Only "filter" mode
        # actually narrows the SQL scope.
        effective_category = category if category_mode == "filter" else None
        effective_subcategory = subcategory if category_mode == "filter" else None

        if influencer and recipient:
            scope = "bilateral"
            rationale = f"Both influencer ({influencer}) and recipient ({recipient}) supplied."
        elif region:
            scope = "regional"
            rationale = f"Region {region} supplied without bilateral pair."
        elif recipient and not influencer:
            scope = "regional"
            rationale = f"Recipient {recipient} without influencer; treating as recipient-centric regional."
        else:
            return StageResult(
                ok=False,
                error="Must supply at least one of: (influencer + recipient), region, or recipient.",
            )

        # When scope is regional, resolve to the explicit recipient list so
        # downstream SQL stages can apply WHERE recipient IN (...) instead
        # of "any recipient anywhere". Bilateral scope leaves this as None.
        region_recipients = _resolve_region_recipients(region) if scope == "regional" else None

        data = {
            "scope": scope,
            "influencer": influencer,
            "recipient": recipient,
            "region": region,
            "region_recipients": region_recipients,
            "start_date": inp.get("start_date"),
            "end_date": inp.get("end_date"),
            "category": effective_category,
            "subcategory": effective_subcategory,
            "category_mode": category_mode,
            # Preserve the user-declared category even when it isn't applied
            # as a filter, so the validator + UI can still surface it.
            "declared_category": category,
            "declared_subcategory": subcategory,
            "rationale": rationale,
        }
        return StageResult(
            ok=True,
            data=data,
            confidence=1.0,
            summary=f"scope={scope}" + (f", category={effective_category}" if effective_category else ""),
        )


STAGE = QueryInterpreterStage()
