"""Intel Reports API (`/api/intel-reports/*`).

Serves the analytic insight reports in docs/reports/ (markdown + chart
assets) read-only to the React app. Reports are discovered from the filesystem
at request time, so a new report directory appears in the app without a client
rebuild. This namespace is independent of the Publication feature
(`/api/report/*`).

Slug convention: the report's directory path relative to docs/reports/ with
`/` flattened to `__` (e.g. `mena_theater`, `china`, `by_category__economic`).
"""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text

from shared.database.database import get_session

router = APIRouter()

REPORTS_DIR = (Path(__file__).resolve().parents[2] / "docs" / "reports").resolve()
SLUG_SEP = "__"
_EXCLUDED_DIRS = {"_derived", "assets"}

_ASSET_MEDIA_TYPES = {
    ".png": "image/png",
    ".csv": "text/csv",
    ".json": "application/json",
    ".svg": "image/svg+xml",
}


class IntelReportMeta(BaseModel):
    slug: str
    title: str
    description: Optional[str] = None
    group: str
    updated: str
    figure_count: int


class IntelReportList(BaseModel):
    reports: list[IntelReportMeta]


class IntelReportContent(BaseModel):
    slug: str
    title: str
    group: str
    updated: str
    markdown: str


def _slug_for(report_dir: Path) -> str:
    return report_dir.relative_to(REPORTS_DIR).as_posix().replace("/", SLUG_SEP)


def _dir_for(slug: str) -> Path:
    rel = slug.replace(SLUG_SEP, "/")
    d = (REPORTS_DIR / rel).resolve()
    # Path-traversal guard: resolved dir must stay inside docs/reports.
    if not d.is_relative_to(REPORTS_DIR) or not (d / "report.md").is_file():
        raise HTTPException(status_code=404, detail=f"Unknown report: {slug}")
    return d


def _group_for(slug: str) -> str:
    if slug == "mena_theater":
        return "Theater"
    if slug.startswith("by_category"):
        return "Category"
    if slug.startswith("by_recipient"):
        return "Recipient"
    return "Initiator"


_GROUP_ORDER = {"Theater": 0, "Initiator": 1, "Category": 2, "Recipient": 3}


def _parse_title_and_description(md: str) -> tuple[str, Optional[str]]:
    title, description = "Untitled report", None
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            for follow in lines[i + 1:]:
                text = follow.strip()
                if not text:
                    continue
                if text.startswith("### "):
                    description = text[4:].strip()
                else:
                    description = re.sub(r"[*_`#>\[\]]", "", text).strip()
                break
            break
    if description and len(description) > 220:
        description = description[:217] + "…"
    return title, description


def _discover() -> list[Path]:
    if not REPORTS_DIR.is_dir():
        return []
    found = []
    for md in sorted(REPORTS_DIR.glob("**/report.md")):
        if any(part in _EXCLUDED_DIRS for part in md.relative_to(REPORTS_DIR).parts):
            continue
        found.append(md.parent)
    return found


def _rewrite_markdown(md: str, slug: str, report_dir: Path) -> str:
    """Point relative asset paths at the API and cross-report links at app routes."""
    # assets/<file> (images and CSV links alike)
    md = re.sub(
        r"\(assets/([^)\s]+)\)",
        lambda m: f"(/api/intel-reports/{slug}/asset/{m.group(1)})",
        md,
    )

    # [text](<relative>.md) -> app route if it is another report, else drop link keep text
    def _link(m: re.Match) -> str:
        text, target = m.group(1), m.group(2)
        try:
            resolved = (report_dir / target).resolve()
        except OSError:
            return text
        if resolved.is_relative_to(REPORTS_DIR) and resolved.name == "report.md" and resolved.is_file():
            return f"[{text}](/intel-reports/{_slug_for(resolved.parent)})"
        return text

    md = re.sub(r"\[([^\]]+)\]\((?!https?://|/)((?:[^)\s]+?)\.md)\)", _link, md)

    # Any remaining relative link (e.g. bare directory refs) -> plain text
    md = re.sub(r"\[([^\]]+)\]\((?!https?://|/|#)[^)]*\)", r"\1", md)
    return md


@router.get("/api/intel-reports", response_model=IntelReportList)
def list_intel_reports():
    """Manifest of all finished report products under docs/reports/."""
    reports = []
    for report_dir in _discover():
        md_path = report_dir / "report.md"
        try:
            head = md_path.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        title, description = _parse_title_and_description(head)
        slug = _slug_for(report_dir)
        assets = report_dir / "assets"
        reports.append(IntelReportMeta(
            slug=slug,
            title=title,
            description=description,
            group=_group_for(slug),
            updated=datetime.fromtimestamp(md_path.stat().st_mtime, tz=timezone.utc)
                            .date().isoformat(),
            figure_count=len(list(assets.glob("*.png"))) if assets.is_dir() else 0,
        ))
    reports.sort(key=lambda r: (_GROUP_ORDER.get(r.group, 9), r.title.lower()))
    return IntelReportList(reports=reports)


@router.get("/api/intel-reports/{slug}", response_model=IntelReportContent)
def get_intel_report(slug: str):
    """Full markdown for one report, with asset/report links rewritten for the app."""
    report_dir = _dir_for(slug)
    md_path = report_dir / "report.md"
    md = md_path.read_text(encoding="utf-8", errors="replace")
    title, _ = _parse_title_and_description(md)
    return IntelReportContent(
        slug=slug,
        title=title,
        group=_group_for(slug),
        updated=datetime.fromtimestamp(md_path.stat().st_mtime, tz=timezone.utc)
                        .date().isoformat(),
        markdown=_rewrite_markdown(md, slug, report_dir),
    )


class EvidenceDocument(BaseModel):
    doc_id: str
    date: Optional[str]
    source_name: Optional[str]
    title: Optional[str]
    snippet: Optional[str]
    self_reported: bool


class EvidenceSource(BaseModel):
    source_name: str
    docs: int
    self_reported: bool


class EvidenceResponse(BaseModel):
    event_id: str
    canonical_name: str
    initiating_country: str
    description: Optional[str]
    material_score: Optional[float]
    material_justification: Optional[str]
    first_mention_date: Optional[str]
    last_mention_date: Optional[str]
    top_recipients: list[str]
    total_docs: int
    third_party_docs: int
    distinct_sources: int
    sources: list[EvidenceSource]
    documents: list[EvidenceDocument]


@router.get("/api/intel-evidence", response_model=EvidenceResponse)
def get_intel_evidence(
    name: str = Query(..., min_length=3, description="canonical event name"),
    actor: Optional[str] = Query(None, description="initiating country"),
):
    """Trace a named initiative back to its canonical event and source documents.

    Resolution: exact canonical_name match first (scoped to the actor when
    given), then a contains-match fallback. Documents come via
    daily_event_mentions.doc_ids — the event→document traceability chain.
    """
    with get_session() as s:
        params = {"name": name, "actor": actor}
        ev = s.execute(text("""
            SELECT id, canonical_name, initiating_country, consolidated_description,
                   material_score, material_justification,
                   first_mention_date, last_mention_date, primary_recipients
            FROM canonical_events
            WHERE canonical_name = :name
              AND (:actor IS NULL OR initiating_country = :actor)
            ORDER BY total_articles DESC LIMIT 1
        """), params).fetchone()
        if ev is None:
            ev = s.execute(text("""
                SELECT id, canonical_name, initiating_country, consolidated_description,
                       material_score, material_justification,
                       first_mention_date, last_mention_date, primary_recipients
                FROM canonical_events
                WHERE canonical_name ILIKE '%' || :name || '%'
                  AND (:actor IS NULL OR initiating_country = :actor)
                ORDER BY total_articles DESC LIMIT 1
            """), params).fetchone()
        if ev is None:
            raise HTTPException(status_code=404, detail="No matching event found")

        docs = s.execute(text("""
            SELECT DISTINCT d.doc_id, d.date, d.source_name, d.title,
                   left(d.distilled_text, 320) AS snippet,
                   (d.source_geofocus ILIKE '%' || :init || '%') AS self_reported
            FROM daily_event_mentions dem
            CROSS JOIN LATERAL unnest(dem.doc_ids) AS u(doc_id)
            JOIN documents d ON d.doc_id = u.doc_id
            WHERE dem.canonical_event_id = :eid
            ORDER BY d.date DESC NULLS LAST
        """), {"eid": ev.id, "init": ev.initiating_country}).fetchall()

        source_counts: dict[str, dict] = {}
        for d in docs:
            key = d.source_name or "(unknown)"
            entry = source_counts.setdefault(key, {"docs": 0, "self": False})
            entry["docs"] += 1
            entry["self"] = entry["self"] or bool(d.self_reported)

        recipients = ev.primary_recipients or {}
        top_recipients = [k for k, _ in sorted(recipients.items(), key=lambda x: -x[1])[:6]] \
            if isinstance(recipients, dict) else []

        return EvidenceResponse(
            event_id=str(ev.id),
            canonical_name=ev.canonical_name,
            initiating_country=ev.initiating_country,
            description=ev.consolidated_description,
            material_score=float(ev.material_score) if ev.material_score is not None else None,
            material_justification=ev.material_justification,
            first_mention_date=str(ev.first_mention_date) if ev.first_mention_date else None,
            last_mention_date=str(ev.last_mention_date) if ev.last_mention_date else None,
            top_recipients=top_recipients,
            total_docs=len(docs),
            third_party_docs=sum(1 for d in docs if not d.self_reported),
            distinct_sources=len(source_counts),
            sources=[
                EvidenceSource(source_name=k, docs=v["docs"], self_reported=v["self"])
                for k, v in sorted(source_counts.items(), key=lambda x: -x[1]["docs"])[:15]
            ],
            documents=[
                EvidenceDocument(
                    doc_id=str(d.doc_id), date=str(d.date) if d.date else None,
                    source_name=d.source_name, title=d.title, snippet=d.snippet,
                    self_reported=bool(d.self_reported),
                ) for d in docs[:60]
            ],
        )


@router.get("/api/intel-reports/{slug}/asset/{filename}")
def get_intel_report_asset(slug: str, filename: str):
    """Serve a chart PNG or its sibling CSV from the report's assets directory."""
    report_dir = _dir_for(slug)
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=404, detail="Not found")
    asset = (report_dir / "assets" / filename).resolve()
    if not asset.is_relative_to(REPORTS_DIR) or not asset.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    media_type = _ASSET_MEDIA_TYPES.get(asset.suffix.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(asset, media_type=media_type)
