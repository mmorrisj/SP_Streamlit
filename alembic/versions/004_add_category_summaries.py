"""add category summary tables

Revision ID: 004_category_summaries
Revises: 003_bilateral_rel
Create Date: 2025-12-01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_category_summaries'
down_revision = '003_bilateral_rel'
branch_labels = None
depends_on = None


def upgrade():
    # Create country_category_summaries table
    op.create_table(
        'country_category_summaries',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('initiating_country', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('first_interaction_date', sa.Date(), nullable=False),
        sa.Column('last_interaction_date', sa.Date(), nullable=False),
        sa.Column('analysis_generated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('total_documents', sa.Integer(), nullable=False),
        sa.Column('total_daily_events', sa.Integer(), nullable=False),
        sa.Column('total_weekly_events', sa.Integer(), nullable=False),
        sa.Column('total_monthly_events', sa.Integer(), nullable=False),
        sa.Column('count_by_recipient', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('count_by_subcategory', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('count_by_source', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('activity_by_month', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('category_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('material_score_histogram', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('material_score_avg', sa.Float(), nullable=True),
        sa.Column('material_score_median', sa.Float(), nullable=True),
        sa.Column('material_score', sa.Float(), nullable=True),
        sa.Column('material_justification', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('initiating_country', 'category', name='uq_country_category'),
        sa.CheckConstraint('first_interaction_date <= last_interaction_date', name='ck_country_category_valid_dates'),
        sa.CheckConstraint('total_documents >= 0', name='ck_country_category_positive_docs')
    )

    # Create indexes for country_category_summaries
    op.create_index('ix_country_category_initiator', 'country_category_summaries', ['initiating_country'])
    op.create_index('ix_country_category_category', 'country_category_summaries', ['category'])
    op.create_index('ix_country_category_dates', 'country_category_summaries', ['first_interaction_date', 'last_interaction_date'])
    op.create_index('ix_country_category_updated', 'country_category_summaries', ['updated_at'])
    op.create_index('ix_country_category_recipient_jsonb', 'country_category_summaries', ['count_by_recipient'], postgresql_using='gin')

    # Create bilateral_category_summaries table
    op.create_table(
        'bilateral_category_summaries',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('initiating_country', sa.Text(), nullable=False),
        sa.Column('recipient_country', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('first_interaction_date', sa.Date(), nullable=False),
        sa.Column('last_interaction_date', sa.Date(), nullable=False),
        sa.Column('analysis_generated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('total_documents', sa.Integer(), nullable=False),
        sa.Column('total_daily_events', sa.Integer(), nullable=False),
        sa.Column('total_weekly_events', sa.Integer(), nullable=False),
        sa.Column('total_monthly_events', sa.Integer(), nullable=False),
        sa.Column('count_by_subcategory', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('count_by_source', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('activity_by_month', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('category_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('material_score_histogram', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('material_score_avg', sa.Float(), nullable=True),
        sa.Column('material_score_median', sa.Float(), nullable=True),
        sa.Column('material_score', sa.Float(), nullable=True),
        sa.Column('material_justification', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('initiating_country', 'recipient_country', 'category', name='uq_bilateral_category'),
        sa.CheckConstraint('first_interaction_date <= last_interaction_date', name='ck_bilateral_category_valid_dates'),
        sa.CheckConstraint('total_documents >= 0', name='ck_bilateral_category_positive_docs')
    )

    # Create indexes for bilateral_category_summaries
    op.create_index('ix_bilateral_category_initiator', 'bilateral_category_summaries', ['initiating_country'])
    op.create_index('ix_bilateral_category_recipient', 'bilateral_category_summaries', ['recipient_country'])
    op.create_index('ix_bilateral_category_category', 'bilateral_category_summaries', ['category'])
    op.create_index('ix_bilateral_category_dates', 'bilateral_category_summaries', ['first_interaction_date', 'last_interaction_date'])
    op.create_index('ix_bilateral_category_updated', 'bilateral_category_summaries', ['updated_at'])
    op.create_index('ix_bilateral_category_subcategory_jsonb', 'bilateral_category_summaries', ['count_by_subcategory'], postgresql_using='gin')


def downgrade():
    # Drop bilateral_category_summaries indexes
    op.drop_index('ix_bilateral_category_subcategory_jsonb', table_name='bilateral_category_summaries')
    op.drop_index('ix_bilateral_category_updated', table_name='bilateral_category_summaries')
    op.drop_index('ix_bilateral_category_dates', table_name='bilateral_category_summaries')
    op.drop_index('ix_bilateral_category_category', table_name='bilateral_category_summaries')
    op.drop_index('ix_bilateral_category_recipient', table_name='bilateral_category_summaries')
    op.drop_index('ix_bilateral_category_initiator', table_name='bilateral_category_summaries')

    # Drop bilateral_category_summaries table
    op.drop_table('bilateral_category_summaries')

    # Drop country_category_summaries indexes
    op.drop_index('ix_country_category_recipient_jsonb', table_name='country_category_summaries')
    op.drop_index('ix_country_category_updated', table_name='country_category_summaries')
    op.drop_index('ix_country_category_dates', table_name='country_category_summaries')
    op.drop_index('ix_country_category_category', table_name='country_category_summaries')
    op.drop_index('ix_country_category_initiator', table_name='country_category_summaries')

    # Drop country_category_summaries table
    op.drop_table('country_category_summaries')
