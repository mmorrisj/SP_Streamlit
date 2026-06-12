"""Add ingestion_jobs table for UI-driven document ingestion.

Tracks file-upload ingestion runs (results.json / atom.csv): staged file
location, dry-run validation report, live per-stage progress counters, and a
structured per-document error log. See docs/INGESTION_UI_DESIGN.md.

Revision ID: 20260612_ingestion_jobs
Revises: 20260515_agent_workflow
Create Date: 2026-06-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260612_ingestion_jobs"
down_revision: Union[str, None] = "20260515_agent_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from alembic import context
    bind = context.get_bind()

    table_exists = bind.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'ingestion_jobs')"
        )
    ).scalar()
    if table_exists:
        return

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("file_type", sa.String(length=20), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="uploaded"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.Column("validation_report", postgresql.JSONB(), nullable=True),
        sa.Column("progress", postgresql.JSONB(), nullable=True),
        sa.Column("error_log", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
    )
    op.create_index("idx_ingestion_jobs_status", "ingestion_jobs", ["status"])
    op.create_index("idx_ingestion_jobs_created", "ingestion_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_ingestion_jobs_created", table_name="ingestion_jobs")
    op.drop_index("idx_ingestion_jobs_status", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
