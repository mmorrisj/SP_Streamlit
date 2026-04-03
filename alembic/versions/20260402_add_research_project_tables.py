"""Add research_projects and project_documents tables for document collection.

Revision ID: 20260402_research_projects
Revises: 20260402_alert_tables
Create Date: 2026-04-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '20260402_research_projects'
down_revision: Union[str, None] = '20260402_alert_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    projectstatus = sa.Enum('ACTIVE', 'ARCHIVED', name='projectstatus')

    op.create_table(
        'research_projects',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', projectstatus, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_research_project_user', 'research_projects', ['user_id'])
    op.create_index('ix_research_project_status', 'research_projects', ['status', 'is_deleted'])

    op.create_table(
        'project_documents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('doc_id', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('source_name', sa.Text(), nullable=True),
        sa.Column('date', sa.Date(), nullable=True),
        sa.Column('initiating_country', sa.Text(), nullable=True),
        sa.Column('recipient_country', sa.Text(), nullable=True),
        sa.Column('category', sa.Text(), nullable=True),
        sa.Column('excerpt', sa.Text(), nullable=True),
        sa.Column('source_query', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['project_id'], ['research_projects.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'doc_id', name='uq_project_doc'),
    )
    op.create_index('ix_project_doc_project', 'project_documents', ['project_id'])
    op.create_index('ix_project_doc_docid', 'project_documents', ['doc_id'])


def downgrade() -> None:
    op.drop_index('ix_project_doc_docid', table_name='project_documents')
    op.drop_index('ix_project_doc_project', table_name='project_documents')
    op.drop_table('project_documents')

    op.drop_index('ix_research_project_status', table_name='research_projects')
    op.drop_index('ix_research_project_user', table_name='research_projects')
    op.drop_table('research_projects')

    op.execute('DROP TYPE IF EXISTS projectstatus')
