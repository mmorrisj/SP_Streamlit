"""Pydantic schemas for inter-stage data flow in the report workflow.

Each stage's output is captured in StageResult.data as a free-form dict,
but the canonical shape of that dict for each stage is defined here so
downstream stages have a contract to read against.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------- inputs ----------------------------------------------------------

class ReportInputs(BaseModel):
    recipient: Optional[str] = Field(None, description="Recipient country (single).")
    region: Optional[str] = Field(None, description="Regional grouping (e.g. 'Africa').")
    influencer: Optional[str] = Field(None, description="Influencer country (omit for regional).")
    start_date: str
    end_date: str
    requested_product: Optional[str] = Field(
        None,
        description="Override the auto-selected writing product (e.g. 'sourced_report').",
    )


# ---------- stage outputs ---------------------------------------------------

class QueryIntent(BaseModel):
    scope: Literal["bilateral", "regional"]
    influencer: Optional[str]
    recipient: Optional[str]
    region: Optional[str]
    start_date: str
    end_date: str
    rationale: str


class DataQAReport(BaseModel):
    doc_count: int
    event_count: int
    materiality_distribution: dict[str, int]  # bucket -> count
    top_categories: list[dict[str, Any]]
    gaps: list[str]
    sufficient: bool
    suggested_actions: list[str] = []


class PrioritizedEvent(BaseModel):
    event_id: str
    event_name: str
    materiality_score: float
    coverage_score: float
    composite_score: float
    categories: list[str] = []
    date_span: Optional[str] = None


class EventPriorities(BaseModel):
    events: list[PrioritizedEvent]
    method: str = "materiality_x_coverage"


class Anomaly(BaseModel):
    kind: Literal["new_entity", "category_spike", "materiality_outlier", "unusual_pair"]
    description: str
    magnitude: Optional[float] = None
    evidence_ids: list[str] = []


class ComparativePoint(BaseModel):
    comparison_type: Literal["peer_recipient", "peer_influencer", "prior_period"]
    label: str
    current_value: float
    comparison_value: float
    delta_pct: float
    interpretation: str


class Trajectory(BaseModel):
    direction: Literal["accelerating", "steady", "cooling"]
    confidence: Literal["LOW", "MED", "HIGH"]
    evidence: list[str]
    prior_period_summary: Optional[str] = None


class EventNarrative(BaseModel):
    event_id: str
    overview: str
    outcomes: str


class Claim(BaseModel):
    claim_id: str
    text: str
    claim_type: Literal["stat", "event", "attribution", "date", "judgment"]
    source_stage: str            # which stage produced this claim
    referent_id: Optional[str] = None  # e.g. event_id


class SourcedClaim(BaseModel):
    claim_id: str
    cited_doc_ids: list[str]
    confidence: Literal["LOW", "MED", "HIGH"]
    sourcing_notes: Optional[str] = None


class CuratedEntity(BaseModel):
    canonical_id: str
    name: str
    entity_type: str
    role_synopsis: str
    influence_rationale: str
    associated_event_ids: list[str] = []
    cited_doc_ids: list[str] = []


class ValidationFinding(BaseModel):
    severity: Literal["info", "warning", "error"]
    where: str
    detail: str


class ValidationReport(BaseModel):
    passed: bool
    findings: list[ValidationFinding] = []
    citation_coverage_pct: float
    schema_conformance: bool
