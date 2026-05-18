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


# ---------------------------------------------------------------------------
# Chat orchestrator — natural-language entry point to the workflow runner.
# Separate from /analyze (which is a ReAct tool-calling loop). The chat
# endpoint makes a single classification LLM call; the analyst confirms
# before any workflow actually runs.
# ---------------------------------------------------------------------------

class ChatTurn(BaseModel):
    """One turn in the chat history, sent back from the client each turn.

    Server is stateless across turns; the client maintains the thread.
    """
    role: str  # "user" | "assistant"
    content: str


class ChatScope(BaseModel):
    """Mirror of the report workflow filters — kept in sync with the UI's
    scope panel. The orchestrator may update any subset on a given turn.
    """
    influencer: Optional[str] = None
    recipient: Optional[str] = None
    region: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    category_mode: Optional[str] = "flat"


class ChatTurnRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []
    current_scope: ChatScope = Field(default_factory=ChatScope)


class ChatTurnResponse(BaseModel):
    action: str  # "propose_run" | "update_scope" | "clarify" | "chat"
    workflow: Optional[str] = None  # set only for propose_run
    scope: ChatScope  # always returned — UI uses this to refresh filters
    message: str  # assistant reply to render in the chat thread
    ready_to_run: bool = False  # convenience flag: propose_run with no missing params
