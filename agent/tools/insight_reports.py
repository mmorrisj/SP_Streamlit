"""Search the finished analytic insight reports (docs/reports/**/report.md).

The reports are adversarially verified analysis — for many questions the best
first move is citing an already-verified finding rather than recomputing from
scratch. Splits each report into heading-delimited sections and ranks them by
keyword overlap with the query.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "docs" / "reports"
_EXCLUDED = {"_derived", "assets"}
_STOP = {
    "the", "a", "an", "and", "or", "of", "in", "on", "to", "for", "with", "by",
    "is", "are", "was", "were", "what", "which", "who", "how", "does", "did",
    "about", "between", "from", "its", "their", "has", "have",
}


@lru_cache(maxsize=1)
def _load_sections() -> list[dict[str, Any]]:
    """Parse every report.md into (slug, heading, text) sections. Cached."""
    sections: list[dict[str, Any]] = []
    if not REPORTS_DIR.is_dir():
        return sections
    for md in sorted(REPORTS_DIR.glob("**/report.md")):
        rel = md.relative_to(REPORTS_DIR)
        if any(part in _EXCLUDED for part in rel.parts):
            continue
        slug = rel.parent.as_posix().replace("/", "__")
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        title = slug
        m = re.search(r"^# (.+)$", text, re.M)
        if m:
            title = m.group(1).strip()
        # Split on h2/h3 headings; keep the heading with its body.
        parts = re.split(r"^(#{2,3} .+)$", text, flags=re.M)
        current_heading = "(intro)"
        for chunk in parts:
            if re.match(r"^#{2,3} ", chunk or ""):
                current_heading = chunk.lstrip("#").strip()
                continue
            body = (chunk or "").strip()
            if len(body) < 80:
                continue
            sections.append({
                "slug": slug,
                "report_title": title,
                "heading": current_heading,
                "text": body,
                "tokens": _tokenize(f"{title} {current_heading} {body}"),
            })
    return sections


def _tokenize(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z\-']+", s.lower()) if w not in _STOP}


class InsightReportsTool(Tool):
    name = "search_insight_reports"
    description = (
        "Search the platform's finished, adversarially-verified analytic insight "
        "reports (theater assessment, per-initiator deep dives, category "
        "contests, recipient cards). Returns the most relevant report sections. "
        "Check here FIRST for strategic questions — a verified finding beats "
        "recomputing from scratch, and you can cite the report by slug."
    )
    foundation_dependency = "docs/reports/**/report.md"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "keywords or a question"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 15, "default": 6},
        },
        "required": ["query"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        query = (kwargs.get("query") or "").strip()
        limit = max(1, min(int(kwargs.get("limit") or 6), 15))
        if not query:
            return ToolResult(ok=False, error="query is required")

        sections = _load_sections()
        if not sections:
            return ToolResult(
                ok=True,
                data={"results": [], "note": "no insight reports found on this deployment"},
                summary="search_insight_reports: no reports available",
            )

        q_tokens = _tokenize(query)
        if not q_tokens:
            return ToolResult(ok=False, error="query contained no searchable terms")

        scored = []
        for s in sections:
            overlap = q_tokens & s["tokens"]
            if not overlap:
                continue
            score = len(overlap) / len(q_tokens)
            scored.append((score, len(overlap), s))
        scored.sort(key=lambda x: (-x[0], -x[1]))

        results = []
        for score, _, s in scored[:limit]:
            body = s["text"]
            results.append({
                "report": s["report_title"],
                "slug": s["slug"],
                "app_link": f"/intel-reports/{s['slug']}",
                "section": s["heading"],
                "match_score": round(score, 2),
                "excerpt": body if len(body) <= 4000 else body[:4000] + "…",
            })

        return ToolResult(
            ok=True,
            data={
                "results": results,
                "note": "These findings passed adversarial verification at report time; "
                        "cite the report and section when using them.",
            },
            summary=f"search_insight_reports: {len(results)} matching sections "
                    f"across {len({r['slug'] for r in results})} reports",
        )


TOOL = InsightReportsTool()
