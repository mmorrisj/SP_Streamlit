"""Add specific_event_name column to raw_events

Stores LLM-refined event names that are more specific than the original
extraction output. The clustering pipeline uses
COALESCE(specific_event_name, event_name) so renames persist across
document re-extraction.

Revision ID: 20260403_specific_event
Revises: 20260403_hnsw_index
Create Date: 2026-04-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260403_specific_event'
down_revision: Union[str, None] = '20260403_hnsw_index'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('raw_events', sa.Column('specific_event_name', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('raw_events', 'specific_event_name')
