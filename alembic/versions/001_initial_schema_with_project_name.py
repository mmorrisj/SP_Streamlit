"""Initial schema with project_name field

Revision ID: 001_initial_schema
Revises:
Create Date: 2025-01-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Create documents table ###
    op.create_table('documents',
    sa.Column('doc_id', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('source_name', sa.Text(), nullable=True),
    sa.Column('source_geofocus', sa.Text(), nullable=True),
    sa.Column('source_consumption', sa.Text(), nullable=True),
    sa.Column('source_description', sa.Text(), nullable=True),
    sa.Column('source_medium', sa.Text(), nullable=True),
    sa.Column('source_location', sa.Text(), nullable=True),
    sa.Column('source_editorial', sa.Text(), nullable=True),
    sa.Column('date', sa.Date(), nullable=True),
    sa.Column('collection_name', sa.Text(), nullable=True),
    sa.Column('gai_engine', sa.Text(), nullable=True),
    sa.Column('gai_promptid', sa.Text(), nullable=True),
    sa.Column('gai_promptversion', sa.Integer(), nullable=True),
    sa.Column('salience', sa.Text(), nullable=True),
    sa.Column('salience_justification', sa.Text(), nullable=True),
    sa.Column('salience_bool', sa.Text(), nullable=True),
    sa.Column('category', sa.Text(), nullable=True),
    sa.Column('category_justification', sa.Text(), nullable=True),
    sa.Column('subcategory', sa.Text(), nullable=True),
    sa.Column('initiating_country', sa.Text(), nullable=True),
    sa.Column('recipient_country', sa.Text(), nullable=True),
    sa.Column('_projects', sa.Text(), nullable=True),
    sa.Column('lat_long', sa.Text(), nullable=True),
    sa.Column('location', sa.Text(), nullable=True),
    sa.Column('monetary_commitment', sa.Text(), nullable=True),
    sa.Column('distilled_text', sa.Text(), nullable=True),
    sa.Column('event_name', sa.Text(), nullable=True),
    sa.Column('project_name', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('doc_id')
    )

    # ### Create normalized relationship tables ###
    op.create_table('categories',
    sa.Column('doc_id', sa.Text(), nullable=False),
    sa.Column('category', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['doc_id'], ['documents.doc_id'], ),
    sa.PrimaryKeyConstraint('doc_id', 'category')
    )

    op.create_table('subcategories',
    sa.Column('doc_id', sa.Text(), nullable=False),
    sa.Column('subcategory', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['doc_id'], ['documents.doc_id'], ),
    sa.PrimaryKeyConstraint('doc_id', 'subcategory')
    )

    op.create_table('initiating_countries',
    sa.Column('doc_id', sa.Text(), nullable=False),
    sa.Column('initiating_country', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['doc_id'], ['documents.doc_id'], ),
    sa.PrimaryKeyConstraint('doc_id', 'initiating_country')
    )

    op.create_table('recipient_countries',
    sa.Column('doc_id', sa.Text(), nullable=False),
    sa.Column('recipient_country', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['doc_id'], ['documents.doc_id'], ),
    sa.PrimaryKeyConstraint('doc_id', 'recipient_country')
    )

    op.create_table('raw_events',
    sa.Column('doc_id', sa.Text(), nullable=False),
    sa.Column('event_name', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['doc_id'], ['documents.doc_id'], ),
    sa.PrimaryKeyConstraint('doc_id', 'event_name')
    )

    # ### Create consolidated event summary tables ###
    op.create_table('period_summaries',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('period_type', sa.Enum('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY', name='periodtype'), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('initiating_country', sa.Text(), nullable=False),
    sa.Column('overview', sa.Text(), nullable=True),
    sa.Column('outcome', sa.Text(), nullable=True),
    sa.Column('metrics', sa.Text(), nullable=True),
    sa.Column('total_events', sa.Integer(), nullable=False),
    sa.Column('total_documents', sa.Integer(), nullable=False),
    sa.Column('total_sources', sa.Integer(), nullable=False),
    sa.Column('aggregated_categories', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('aggregated_recipients', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('aggregated_sources', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint('period_start <= period_end', name='ck_valid_period_summary'),
    sa.CheckConstraint('total_events >= 0', name='ck_positive_event_count'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('period_type', 'period_start', 'period_end', 'initiating_country', name='uq_period_summary')
    )
    op.create_index('ix_period_summary_country_period', 'period_summaries', ['initiating_country', 'period_type', 'period_start'], unique=False)

    op.create_table('event_summaries',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('period_type', sa.Enum('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY', name='periodtype'), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('event_name', sa.Text(), nullable=False),
    sa.Column('initiating_country', sa.Text(), nullable=False),
    sa.Column('first_observed_date', sa.Date(), nullable=False),
    sa.Column('last_observed_date', sa.Date(), nullable=False),
    sa.Column('status', sa.Enum('ACTIVE', 'INACTIVE', 'ARCHIVED', name='eventstatus'), nullable=False),
    sa.Column('period_summary_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.String(length=255), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('category_count', sa.Integer(), nullable=False),
    sa.Column('subcategory_count', sa.Integer(), nullable=False),
    sa.Column('recipient_count', sa.Integer(), nullable=False),
    sa.Column('source_count', sa.Integer(), nullable=False),
    sa.Column('total_documents_across_categories', sa.Integer(), nullable=False),
    sa.Column('total_documents_across_subcategories', sa.Integer(), nullable=False),
    sa.Column('total_documents_across_recipients', sa.Integer(), nullable=False),
    sa.Column('total_documents_across_sources', sa.Integer(), nullable=False),
    sa.Column('count_by_category', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('count_by_subcategory', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('count_by_recipient', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('count_by_source', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint('category_count >= 0', name='ck_positive_category_count'),
    sa.CheckConstraint('first_observed_date <= last_observed_date', name='ck_valid_observation'),
    sa.CheckConstraint('period_start <= period_end', name='ck_valid_period'),
    sa.CheckConstraint('source_count >= 0', name='ck_positive_source_count'),
    sa.ForeignKeyConstraint(['period_summary_id'], ['period_summaries.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('period_type', 'period_start', 'period_end', 'initiating_country', 'event_name', name='uq_event_summary_period')
    )
    op.create_index('ix_event_summary_category_jsonb', 'event_summaries', ['count_by_category'], unique=False, postgresql_using='gin')
    op.create_index('ix_event_summary_country_period', 'event_summaries', ['initiating_country', 'period_type', 'period_start'], unique=False)
    op.create_index('ix_event_summary_dates', 'event_summaries', ['first_observed_date', 'last_observed_date'], unique=False)
    op.create_index('ix_event_summary_name', 'event_summaries', ['event_name'], unique=False)
    op.create_index('ix_event_summary_source_jsonb', 'event_summaries', ['count_by_source'], unique=False, postgresql_using='gin')
    op.create_index('ix_event_summary_status', 'event_summaries', ['status', 'is_deleted'], unique=False)

    op.create_table('event_source_links',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('event_summary_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('doc_id', sa.Text(), nullable=False),
    sa.Column('contribution_weight', sa.Float(), nullable=True),
    sa.Column('linked_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['doc_id'], ['documents.doc_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['event_summary_id'], ['event_summaries.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_summary_id', 'doc_id', name='uq_event_source_link')
    )
    op.create_index('ix_event_source_doc', 'event_source_links', ['doc_id'], unique=False)
    op.create_index('ix_event_source_event', 'event_source_links', ['event_summary_id'], unique=False)

    # ### Create canonical event tracking tables ###
    op.create_table('canonical_events',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('canonical_name', sa.Text(), nullable=False),
    sa.Column('initiating_country', sa.Text(), nullable=False),
    sa.Column('first_mention_date', sa.Date(), nullable=False),
    sa.Column('last_mention_date', sa.Date(), nullable=False),
    sa.Column('total_mention_days', sa.Integer(), nullable=True),
    sa.Column('total_articles', sa.Integer(), nullable=True),
    sa.Column('story_phase', sa.String(length=50), nullable=True),
    sa.Column('days_since_last_mention', sa.Integer(), nullable=True),
    sa.Column('unique_sources', postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column('source_count', sa.Integer(), nullable=True),
    sa.Column('peak_mention_date', sa.Date(), nullable=True),
    sa.Column('peak_daily_article_count', sa.Integer(), nullable=True),
    sa.Column('consolidated_description', sa.Text(), nullable=True),
    sa.Column('key_facts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('embedding_vector', postgresql.ARRAY(sa.Float()), nullable=True),
    sa.Column('alternative_names', postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column('primary_categories', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('primary_recipients', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_canonical_event_country_dates', 'canonical_events', ['initiating_country', 'first_mention_date', 'last_mention_date'], unique=False)
    op.create_index('ix_canonical_event_days_since', 'canonical_events', ['days_since_last_mention'], unique=False)
    op.create_index('ix_canonical_event_story_phase', 'canonical_events', ['story_phase'], unique=False)

    op.create_table('daily_event_mentions',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('canonical_event_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('initiating_country', sa.Text(), nullable=False),
    sa.Column('mention_date', sa.Date(), nullable=False),
    sa.Column('article_count', sa.Integer(), nullable=True),
    sa.Column('consolidated_headline', sa.Text(), nullable=True),
    sa.Column('daily_summary', sa.Text(), nullable=True),
    sa.Column('source_names', postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column('source_diversity_score', sa.Float(), nullable=True),
    sa.Column('mention_context', sa.Text(), nullable=True),
    sa.Column('news_intensity', sa.String(length=20), nullable=True),
    sa.Column('doc_ids', postgresql.ARRAY(sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['canonical_event_id'], ['canonical_events.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('canonical_event_id', 'mention_date', name='uq_daily_mention')
    )
    op.create_index('ix_daily_mention_context', 'daily_event_mentions', ['mention_context'], unique=False)
    op.create_index('ix_daily_mention_country_date', 'daily_event_mentions', ['initiating_country', 'mention_date'], unique=False)
    op.create_index('ix_daily_mention_date', 'daily_event_mentions', ['mention_date'], unique=False)


def downgrade() -> None:
    # Drop tables in reverse order (respect foreign keys)
    op.drop_index('ix_daily_mention_date', table_name='daily_event_mentions')
    op.drop_index('ix_daily_mention_country_date', table_name='daily_event_mentions')
    op.drop_index('ix_daily_mention_context', table_name='daily_event_mentions')
    op.drop_table('daily_event_mentions')

    op.drop_index('ix_canonical_event_story_phase', table_name='canonical_events')
    op.drop_index('ix_canonical_event_days_since', table_name='canonical_events')
    op.drop_index('ix_canonical_event_country_dates', table_name='canonical_events')
    op.drop_table('canonical_events')

    op.drop_index('ix_event_source_event', table_name='event_source_links')
    op.drop_index('ix_event_source_doc', table_name='event_source_links')
    op.drop_table('event_source_links')

    op.drop_index('ix_event_summary_status', table_name='event_summaries')
    op.drop_index('ix_event_summary_source_jsonb', table_name='event_summaries')
    op.drop_index('ix_event_summary_name', table_name='event_summaries')
    op.drop_index('ix_event_summary_dates', table_name='event_summaries')
    op.drop_index('ix_event_summary_country_period', table_name='event_summaries')
    op.drop_index('ix_event_summary_category_jsonb', table_name='event_summaries')
    op.drop_table('event_summaries')

    op.drop_index('ix_period_summary_country_period', table_name='period_summaries')
    op.drop_table('period_summaries')

    op.drop_table('raw_events')
    op.drop_table('recipient_countries')
    op.drop_table('initiating_countries')
    op.drop_table('subcategories')
    op.drop_table('categories')
    op.drop_table('documents')
