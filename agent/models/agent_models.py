"""SQLAlchemy models for the agent runtime.

These tables are isolated from foundational schema — no foreign keys into
documents/events/entities yet. Add cross-schema FKs in a later migration
once the agent data model has stabilized.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from shared.database.database import Base


class AgentSession(Base):
    """A user-facing conversational session against the agent page."""

    __tablename__ = "agent_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, nullable=True)  # no FK yet; loose coupling
    title = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    meta = Column(JSONB, nullable=True)


class AgentRun(Base):
    """A single /analyze invocation: one query, one workflow, one briefing."""

    __tablename__ = "agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("agent_sessions.id"), nullable=True)
    query = Column(Text, nullable=False)
    time_window_hours = Column(Integer, nullable=True)
    status = Column(String(32), default="pending", nullable=False)  # pending|running|succeeded|failed
    provider = Column(String(64), nullable=True)
    model = Column(String(128), nullable=True)
    tool_mode = Column(String(32), nullable=True)  # native | json_fallback
    workflow = Column(JSONB, nullable=True)        # full WorkflowStep list
    briefing = Column(JSONB, nullable=True)        # final Briefing payload
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    latency_ms = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_agent_runs_session", "session_id"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_started", "started_at"),
    )


class AgentToolCall(Base):
    """One tool invocation within a run — the workflow trace at row granularity."""

    __tablename__ = "agent_tool_calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False)
    step = Column(Integer, nullable=False)
    tool_name = Column(String(128), nullable=False)
    reason = Column(Text, nullable=True)
    input_args = Column(JSONB, nullable=True)
    output_summary = Column(Text, nullable=True)
    output_payload = Column(JSONB, nullable=True)
    citations = Column(JSONB, nullable=True)  # list of doc_ids touched
    status = Column(String(32), default="pending", nullable=False)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    latency_ms = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_agent_tool_calls_run", "run_id"),
        Index("ix_agent_tool_calls_tool", "tool_name"),
    )
