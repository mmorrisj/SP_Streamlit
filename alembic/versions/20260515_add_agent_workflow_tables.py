"""Add agent_workflow_runs and agent_workflow_steps tables for structured workflows.

These tables are independent of agent_runs / agent_tool_calls (which serve
the ReAct loop) so the two execution models can evolve separately.

Revision ID: 20260515_agent_workflow
Revises: 20260514_agent_tables
Create Date: 2026-05-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260515_agent_workflow"
down_revision: Union[str, None] = "20260514_agent_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from alembic import context
    bind = context.get_bind()

    tables_exist = bind.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'agent_workflow_runs')"
        )
    ).scalar()
    if tables_exist:
        return

    op.create_table(
        "agent_workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_name", sa.String(length=128), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("skipped_stages", postgresql.JSONB(), nullable=True),
        sa.Column("confidence_summary", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
    )
    op.create_index("ix_agent_workflow_runs_name", "agent_workflow_runs", ["workflow_name"])
    op.create_index("ix_agent_workflow_runs_status", "agent_workflow_runs", ["status"])
    op.create_index("ix_agent_workflow_runs_started", "agent_workflow_runs", ["started_at"])

    op.create_table(
        "agent_workflow_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("citations", postgresql.JSONB(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("notes", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
    )
    op.create_index("ix_agent_workflow_steps_run", "agent_workflow_steps", ["run_id"])
    op.create_index("ix_agent_workflow_steps_stage", "agent_workflow_steps", ["stage_name"])


def downgrade() -> None:
    op.drop_index("ix_agent_workflow_steps_stage", table_name="agent_workflow_steps")
    op.drop_index("ix_agent_workflow_steps_run", table_name="agent_workflow_steps")
    op.drop_table("agent_workflow_steps")
    op.drop_index("ix_agent_workflow_runs_started", table_name="agent_workflow_runs")
    op.drop_index("ix_agent_workflow_runs_status", table_name="agent_workflow_runs")
    op.drop_index("ix_agent_workflow_runs_name", table_name="agent_workflow_runs")
    op.drop_table("agent_workflow_runs")
