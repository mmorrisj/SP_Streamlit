"""Pydantic request/response schemas for the agent API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    query: str = Field(..., description="Natural-language analyst question")
    time_window_hours: Optional[int] = Field(None, ge=1, le=24 * 365)
    session_id: Optional[UUID] = None


class WorkflowStep(BaseModel):
    step: int
    tool: str
    reason: str
    status: str = "pending"  # pending | running | succeeded | failed | skipped
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    output_summary: Optional[str] = None


class EvidenceItem(BaseModel):
    source_id: str
    title: Optional[str] = None
    date: Optional[str] = None
    confidence: Optional[float] = None
    snippet: Optional[str] = None
    url: Optional[str] = None


class TimelineEntry(BaseModel):
    timestamp: str
    event: str
    source_ids: list[str] = []


class EntityRef(BaseModel):
    canonical_id: Optional[str] = None
    name: str
    entity_type: Optional[str] = None
    role: Optional[str] = None


class Briefing(BaseModel):
    title: str
    executive_summary: str
    key_judgments: list[str] = []
    timeline: list[TimelineEntry] = []
    key_entities: list[EntityRef] = []
    evidence: list[EvidenceItem] = []
    confidence_assessment: Optional[str] = None
    information_gaps: list[str] = []
    recommended_followup: list[str] = []


class AnalyzeResponse(BaseModel):
    run_id: UUID
    briefing: Optional[Briefing] = None
    workflow: list[WorkflowStep] = []
    evidence: list[EvidenceItem] = []
    entities: list[EntityRef] = []
    timeline: list[TimelineEntry] = []


class ToolDescriptor(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    foundation_dependency: Optional[str] = Field(
        None,
        description="Which underlying service/module this tool wraps, for traceability.",
    )


class ToolListResponse(BaseModel):
    tools: list[ToolDescriptor]
