"""Add canonical event integration to event_summaries

Revision ID: 20250130_canonical_integration
Revises: 20250130_entities_mentioned
Create Date: 2025-01-30

This migration enhances the event_summaries table with canonical event integration:
- canonical_event_id: Foreign key linking to canonical_events
- doc_ids: Array of document IDs for denormalized access
- alternative_names: Array of alternative event names
- materiality_stats: JSONB for event-level materiality statistics
- key_facts: JSONB for structured facts from canonical event
- entities_mentioned: JSONB for named entities (persons, orgs, companies, locations)
- overall_summary: Text field for comprehensive 2-3 paragraph narrative
- outcomes_summary: Text field for 1-2 paragraph results/impacts summary
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250130_canonical_integration'
down_revision = '20250130_entities_mentioned'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add canonical_event_id foreign key
    op.add_column('event_summaries',
                  sa.Column('canonical_event_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_event_summary_canonical_event',
        'event_summaries', 'canonical_events',
        ['canonical_event_id'], ['id'],
        ondelete='SET NULL'
    )

    # Add denormalized data arrays
    op.add_column('event_summaries',
                  sa.Column('doc_ids', postgresql.ARRAY(sa.Text()), nullable=True, server_default='{}'))
    op.add_column('event_summaries',
                  sa.Column('alternative_names', postgresql.ARRAY(sa.Text()), nullable=True, server_default='{}'))

    # Add event metadata JSONB fields
    op.add_column('event_summaries',
                  sa.Column('materiality_stats', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('event_summaries',
                  sa.Column('key_facts', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('event_summaries',
                  sa.Column('entities_mentioned', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # Add comprehensive summary fields
    op.add_column('event_summaries',
                  sa.Column('overall_summary', sa.Text(), nullable=True))
    op.add_column('event_summaries',
                  sa.Column('outcomes_summary', sa.Text(), nullable=True))

    # Create indexes for efficient queries
    op.create_index(
        'ix_event_summary_canonical_event',
        'event_summaries',
        ['canonical_event_id']
    )
    op.create_index(
        'ix_event_summary_materiality_stats',
        'event_summaries',
        ['materiality_stats'],
        postgresql_using='gin'
    )
    op.create_index(
        'ix_event_summary_key_facts',
        'event_summaries',
        ['key_facts'],
        postgresql_using='gin'
    )
    op.create_index(
        'ix_event_summary_entities',
        'event_summaries',
        ['entities_mentioned'],
        postgresql_using='gin'
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_event_summary_entities', table_name='event_summaries')
    op.drop_index('ix_event_summary_key_facts', table_name='event_summaries')
    op.drop_index('ix_event_summary_materiality_stats', table_name='event_summaries')
    op.drop_index('ix_event_summary_canonical_event', table_name='event_summaries')

    # Drop columns
    op.drop_column('event_summaries', 'outcomes_summary')
    op.drop_column('event_summaries', 'overall_summary')
    op.drop_column('event_summaries', 'entities_mentioned')
    op.drop_column('event_summaries', 'key_facts')
    op.drop_column('event_summaries', 'materiality_stats')
    op.drop_column('event_summaries', 'alternative_names')
    op.drop_column('event_summaries', 'doc_ids')

    # Drop foreign key and column
    op.drop_constraint('fk_event_summary_canonical_event', 'event_summaries', type_='foreignkey')
    op.drop_column('event_summaries', 'canonical_event_id')
