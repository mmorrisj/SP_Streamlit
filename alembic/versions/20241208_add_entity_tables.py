"""Add entity extraction tables for network mapping

Revision ID: 20241208_entity
Revises:
Create Date: 2024-12-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20241208_entity'
down_revision = None  # Update this to chain with your existing migrations
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create entities table
    op.create_table(
        'entities',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('canonical_name', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('country', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('parent_organization_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('aliases', postgresql.ARRAY(sa.Text()), server_default='{}'),
        sa.Column('embedding_vector', postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column('first_seen_date', sa.Date(), nullable=True),
        sa.Column('last_seen_date', sa.Date(), nullable=True),
        sa.Column('mention_count', sa.Integer(), server_default='0'),
        sa.Column('primary_topics', postgresql.JSONB(), server_default='{}'),
        sa.Column('primary_roles', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('is_verified', sa.Boolean(), server_default='false'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['parent_organization_id'], ['entities.id'], ondelete='SET NULL')
    )

    # Create indexes for entities
    op.create_index('ix_entity_canonical_name', 'entities', ['canonical_name'])
    op.create_index('ix_entity_type', 'entities', ['entity_type'])
    op.create_index('ix_entity_country', 'entities', ['country'])
    op.create_index('ix_entity_mention_count', 'entities', ['mention_count'])
    op.create_index('ix_entity_aliases', 'entities', ['aliases'], postgresql_using='gin')

    # Create document_entities table
    op.create_table(
        'document_entities',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('doc_id', sa.Text(), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('side', sa.String(20), nullable=False),
        sa.Column('role_label', sa.String(50), nullable=False),
        sa.Column('topic_label', sa.String(50), nullable=False),
        sa.Column('role_description', sa.Text(), nullable=True),
        sa.Column('title_in_context', sa.Text(), nullable=True),
        sa.Column('organization_in_context', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), server_default='1.0'),
        sa.Column('extraction_method', sa.String(50), server_default="'llm'"),
        sa.Column('extracted_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('model_used', sa.String(100), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['doc_id'], ['documents.doc_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id'], ondelete='CASCADE')
    )

    # Create indexes for document_entities
    op.create_index('ix_doc_entity_doc_id', 'document_entities', ['doc_id'])
    op.create_index('ix_doc_entity_entity_id', 'document_entities', ['entity_id'])
    op.create_index('ix_doc_entity_side', 'document_entities', ['side'])
    op.create_index('ix_doc_entity_role', 'document_entities', ['role_label'])
    op.create_index('ix_doc_entity_topic', 'document_entities', ['topic_label'])

    # Create entity_relationships table
    op.create_table(
        'entity_relationships',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('target_entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('relationship_type', sa.String(50), nullable=False),
        sa.Column('first_observed', sa.Date(), nullable=False),
        sa.Column('last_observed', sa.Date(), nullable=False),
        sa.Column('observation_count', sa.Integer(), server_default='1'),
        sa.Column('document_count', sa.Integer(), server_default='1'),
        sa.Column('total_value_usd', sa.Float(), nullable=True),
        sa.Column('sample_doc_ids', postgresql.ARRAY(sa.Text()), server_default='{}'),
        sa.Column('sample_descriptions', postgresql.ARRAY(sa.Text()), server_default='{}'),
        sa.Column('avg_confidence', sa.Float(), server_default='1.0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['source_entity_id'], ['entities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_entity_id'], ['entities.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('source_entity_id', 'target_entity_id', 'relationship_type', name='uq_entity_relationship')
    )

    # Create indexes for entity_relationships
    op.create_index('ix_relationship_source', 'entity_relationships', ['source_entity_id'])
    op.create_index('ix_relationship_target', 'entity_relationships', ['target_entity_id'])
    op.create_index('ix_relationship_type', 'entity_relationships', ['relationship_type'])
    op.create_index('ix_relationship_dates', 'entity_relationships', ['first_observed', 'last_observed'])

    # Create entity_extraction_runs table (for auditing)
    op.create_table(
        'entity_extraction_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('initiating_country', sa.Text(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('model_used', sa.String(100), nullable=False),
        sa.Column('documents_processed', sa.Integer(), server_default='0'),
        sa.Column('entities_extracted', sa.Integer(), server_default='0'),
        sa.Column('relationships_extracted', sa.Integer(), server_default='0'),
        sa.Column('errors', sa.Integer(), server_default='0'),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(20), server_default="'running'"),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('entity_extraction_runs')
    op.drop_table('entity_relationships')
    op.drop_table('document_entities')
    op.drop_table('entities')
