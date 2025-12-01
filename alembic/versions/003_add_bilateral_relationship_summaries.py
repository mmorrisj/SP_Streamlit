"""add bilateral relationship summaries table

Revision ID: 003_bilateral_rel
Revises: 002_material_score
Create Date: 2025-11-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003_bilateral_rel'
down_revision = '002_material_score'
branch_labels = None
depends_on = None


def upgrade():
    # Create bilateral_relationship_summaries table
    op.create_table(
        'bilateral_relationship_summaries',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('initiating_country', sa.Text(), nullable=False),
        sa.Column('recipient_country', sa.Text(), nullable=False),
        sa.Column('first_interaction_date', sa.Date(), nullable=False),
        sa.Column('last_interaction_date', sa.Date(), nullable=False),
        sa.Column('analysis_generated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('total_documents', sa.Integer(), nullable=False),
        sa.Column('total_daily_events', sa.Integer(), nullable=False),
        sa.Column('total_weekly_events', sa.Integer(), nullable=False),
        sa.Column('total_monthly_events', sa.Integer(), nullable=False),
        sa.Column('count_by_category', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('count_by_subcategory', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('count_by_source', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('activity_by_month', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('relationship_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('material_score', sa.Float(), nullable=True),
        sa.Column('material_justification', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('initiating_country', 'recipient_country', name='uq_bilateral_pair'),
        sa.CheckConstraint('first_interaction_date <= last_interaction_date', name='ck_bilateral_valid_dates'),
        sa.CheckConstraint('total_documents >= 0', name='ck_bilateral_positive_docs')
    )

    # Create indexes
    op.create_index('ix_bilateral_initiator', 'bilateral_relationship_summaries', ['initiating_country'])
    op.create_index('ix_bilateral_recipient', 'bilateral_relationship_summaries', ['recipient_country'])
    op.create_index('ix_bilateral_dates', 'bilateral_relationship_summaries', ['first_interaction_date', 'last_interaction_date'])
    op.create_index('ix_bilateral_updated', 'bilateral_relationship_summaries', ['updated_at'])
    op.create_index('ix_bilateral_category_jsonb', 'bilateral_relationship_summaries', ['count_by_category'], postgresql_using='gin')


def downgrade():
    # Drop indexes
    op.drop_index('ix_bilateral_category_jsonb', table_name='bilateral_relationship_summaries')
    op.drop_index('ix_bilateral_updated', table_name='bilateral_relationship_summaries')
    op.drop_index('ix_bilateral_dates', table_name='bilateral_relationship_summaries')
    op.drop_index('ix_bilateral_recipient', table_name='bilateral_relationship_summaries')
    op.drop_index('ix_bilateral_initiator', table_name='bilateral_relationship_summaries')

    # Drop table
    op.drop_table('bilateral_relationship_summaries')
