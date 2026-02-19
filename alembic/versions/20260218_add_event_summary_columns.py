"""Add missing columns to event_summaries table

Adds canonical_event_id, doc_ids, alternative_names, materiality_stats,
key_facts, entities_mentioned, overall_summary, outcomes_summary columns
that were defined in the model but never migrated.

Revision ID: 20260218_event_summary_cols
Revises: ed54955faedb
Create Date: 2026-02-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260218_event_summary_cols'
down_revision: Union[str, None] = 'ed54955faedb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('event_summaries', sa.Column('canonical_event_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('canonical_events.id', ondelete='SET NULL'), nullable=True))
    op.add_column('event_summaries', sa.Column('doc_ids', postgresql.ARRAY(sa.Text()), server_default='{}'))
    op.add_column('event_summaries', sa.Column('alternative_names', postgresql.ARRAY(sa.Text()), server_default='{}'))
    op.add_column('event_summaries', sa.Column('materiality_stats', postgresql.JSONB(), server_default='{}'))
    op.add_column('event_summaries', sa.Column('key_facts', postgresql.JSONB(), server_default='{}'))
    op.add_column('event_summaries', sa.Column('entities_mentioned', postgresql.JSONB(), server_default='{}'))
    op.add_column('event_summaries', sa.Column('overall_summary', sa.Text(), nullable=True))
    op.add_column('event_summaries', sa.Column('outcomes_summary', sa.Text(), nullable=True))

    op.create_index('ix_event_summary_canonical_event', 'event_summaries', ['canonical_event_id'])
    op.create_index('ix_event_summary_materiality_stats', 'event_summaries', ['materiality_stats'], postgresql_using='gin')
    op.create_index('ix_event_summary_key_facts', 'event_summaries', ['key_facts'], postgresql_using='gin')
    op.create_index('ix_event_summary_entities', 'event_summaries', ['entities_mentioned'], postgresql_using='gin')


def downgrade() -> None:
    op.drop_index('ix_event_summary_entities', table_name='event_summaries')
    op.drop_index('ix_event_summary_key_facts', table_name='event_summaries')
    op.drop_index('ix_event_summary_materiality_stats', table_name='event_summaries')
    op.drop_index('ix_event_summary_canonical_event', table_name='event_summaries')

    op.drop_column('event_summaries', 'outcomes_summary')
    op.drop_column('event_summaries', 'overall_summary')
    op.drop_column('event_summaries', 'entities_mentioned')
    op.drop_column('event_summaries', 'key_facts')
    op.drop_column('event_summaries', 'materiality_stats')
    op.drop_column('event_summaries', 'alternative_names')
    op.drop_column('event_summaries', 'doc_ids')
    op.drop_column('event_summaries', 'canonical_event_id')
