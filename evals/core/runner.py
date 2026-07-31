"""Eval registry, runner, and report writer.

Each eval component registers a callable returning an EvalResult. The runner
executes selected components, tolerates per-component failure, and writes a
JSON artifact plus a human-readable markdown report under evals/results/.
"""
from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


@dataclass
class EvalResult:
    component: str
    metrics: dict = field(default_factory=dict)
    # Per-case records for drill-down (kept small; large blobs truncated).
    cases: list = field(default_factory=list)
    # Free-text observations the component author wants surfaced verbatim.
    notes: list = field(default_factory=list)
    # Caveats: known validity limits of this eval (sampling, judge bias, ...).
    caveats: list = field(default_factory=list)
    error: str | None = None
    duration_s: float = 0.0


_REGISTRY: dict[str, Callable[..., EvalResult]] = {}


def register(name: str):
    def deco(fn):
        _REGISTRY[name] = fn
        return fn

    return deco


def available() -> list[str]:
    return sorted(_REGISTRY)


def run(components: list[str] | None = None, **kwargs) -> list[EvalResult]:
    names = components or available()
    results = []
    for name in names:
        fn = _REGISTRY.get(name)
        if fn is None:
            results.append(
                EvalResult(component=name, error=f"unknown component {name!r}; "
                          f"available: {available()}"))
            continue
        t0 = time.time()
        try:
            res = fn(**kwargs)
        except Exception:
            res = EvalResult(component=name, error=traceback.format_exc())
        res.duration_s = round(time.time() - t0, 2)
        results.append(res)
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _fmt(v):
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def write_reports(results: list[EvalResult], tag: str = "") -> tuple[Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stem = f"eval_{stamp}{('_' + tag) if tag else ''}"

    json_path = RESULTS_DIR / f"{stem}.json"
    payload = [
        {
            "component": r.component,
            "metrics": r.metrics,
            "cases": r.cases,
            "notes": r.notes,
            "caveats": r.caveats,
            "error": r.error,
            "duration_s": r.duration_s,
        }
        for r in results
    ]
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    md = [f"# Evaluation Report — {stamp} UTC\n"]
    md.append("Corpus caveat: source data carries a media-lens bias (notably "
              "over-representation of Iranian state media). All metrics below are "
              "*internal* measures — faithfulness to the corpus and methodological "
              "soundness of each component — not measures of ground-truth accuracy "
              "about world events.\n")
    for r in results:
        md.append(f"\n## {r.component}  ({r.duration_s}s)\n")
        if r.error:
            md.append(f"**ERROR**\n```\n{r.error[-2000:]}\n```\n")
            continue
        if r.metrics:
            md.append("| metric | value |\n|---|---|")
            for k, v in r.metrics.items():
                if isinstance(v, dict):
                    for k2, v2 in v.items():
                        md.append(f"| {k}.{k2} | {_fmt(v2)} |")
                else:
                    md.append(f"| {k} | {_fmt(v)} |")
            md.append("")
        for n in r.notes:
            md.append(f"- {n}")
        if r.caveats:
            md.append("\n*Caveats:*")
            for c in r.caveats:
                md.append(f"- {c}")
        md.append("")
    md_path = RESULTS_DIR / f"{stem}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    return json_path, md_path
