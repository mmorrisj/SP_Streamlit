"""Add material_score to event_summaries

Revision ID: 002_material_score
Revises: 001_initial_schema
Create Date: 2025-01-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_material_score'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add material_score column to event_summaries
    op.add_column('event_summaries',
                  sa.Column('material_score', sa.Numeric(precision=3, scale=1), nullable=True))

    # Add material_justification column to store reasoning
    op.add_column('event_summaries',
                  sa.Column('material_justification', sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove material_justification column
    op.drop_column('event_summaries', 'material_justification')

    # Remove material_score column
    op.drop_column('event_summaries', 'material_score')
