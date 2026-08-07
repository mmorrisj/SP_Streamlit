"""Add survey_responses table for in-app demo feedback.

Stores responses from the survey page: respondent identity from the
enterprise JWT, an extracted overall rating for cheap aggregation, and the
full answer payload as JSONB so the question set can evolve client-side
without further migrations.

Revision ID: 20260807_survey_responses
Revises: 20260612_ingestion_jobs
Create Date: 2026-08-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_survey_responses"
down_revision: Union[str, None] = "20260612_ingestion_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from alembic import context
    bind = context.get_bind()

    table_exists = bind.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'survey_responses')"
        )
    ).scalar()
    if table_exists:
        return

    op.create_table(
        "survey_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("user_role", sa.String(length=20), nullable=True),
        sa.Column("overall_rating", sa.Integer(), nullable=True),
        sa.Column("answers", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_survey_responses_created", "survey_responses", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_survey_responses_created", table_name="survey_responses")
    op.drop_table("survey_responses")
