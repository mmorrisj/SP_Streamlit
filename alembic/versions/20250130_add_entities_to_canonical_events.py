"""Add entities_mentioned and updated_at to canonical_events

Revision ID: 20250130_entities_mentioned
Revises: fec28b5b115d
Create Date: 2025-01-30

This migration adds entity tracking fields to the canonical_events table:
- entities_mentioned: JSONB field to store extracted entities (persons, orgs, companies, locations)
- updated_at: Timestamp field to track when the event was last modified
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250130_entities_mentioned'
down_revision = 'fec28b5b115d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add entities_mentioned JSONB field
    op.add_column('canonical_events',
                  sa.Column('entities_mentioned', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # Add updated_at timestamp field
    op.add_column('canonical_events',
                  sa.Column('updated_at', sa.DateTime(), nullable=True))

    # Create index on entities_mentioned for faster queries
    op.create_index(
        'ix_canonical_events_entities_mentioned',
        'canonical_events',
        ['entities_mentioned'],
        postgresql_using='gin'
    )


def downgrade() -> None:
    # Drop index
    op.drop_index('ix_canonical_events_entities_mentioned', table_name='canonical_events')

    # Remove updated_at column
    op.drop_column('canonical_events', 'updated_at')

    # Remove entities_mentioned column
    op.drop_column('canonical_events', 'entities_mentioned')
