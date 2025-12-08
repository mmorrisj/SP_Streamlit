"""Add material_score to canonical_events

Revision ID: 005_canonical_material
Revises: 004_category_summaries
Create Date: 2025-12-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005_canonical_material'
down_revision: Union[str, None] = '004_category_summaries'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add material_score column to canonical_events
    op.add_column('canonical_events',
                  sa.Column('material_score', sa.Numeric(precision=3, scale=1), nullable=True))

    # Add material_justification column to store reasoning
    op.add_column('canonical_events',
                  sa.Column('material_justification', sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove material_justification column
    op.drop_column('canonical_events', 'material_justification')

    # Remove material_score column
    op.drop_column('canonical_events', 'material_score')
