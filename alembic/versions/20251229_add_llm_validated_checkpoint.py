"""Add llm_validated fields to canonical_events for checkpoint resume

Revision ID: 20251229_llm_validated
Revises: 20241208_entity
Create Date: 2025-12-29

This migration adds checkpoint tracking fields to the canonical_events table
to enable the llm_deconflict_canonical_events.py script to resume from where
it left off if interrupted.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251229_llm_validated'
down_revision = '20241208_entity'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add llm_validated boolean field (default False)
    op.add_column('canonical_events',
                  sa.Column('llm_validated', sa.Boolean(), nullable=False, server_default='false'))

    # Add llm_validated_at timestamp field
    op.add_column('canonical_events',
                  sa.Column('llm_validated_at', sa.DateTime(), nullable=True))

    # Create index on llm_validated for efficient filtering
    op.create_index('ix_canonical_event_llm_validated', 'canonical_events', ['llm_validated'])


def downgrade() -> None:
    # Drop the index
    op.drop_index('ix_canonical_event_llm_validated', table_name='canonical_events')

    # Remove llm_validated_at column
    op.drop_column('canonical_events', 'llm_validated_at')

    # Remove llm_validated column
    op.drop_column('canonical_events', 'llm_validated')
