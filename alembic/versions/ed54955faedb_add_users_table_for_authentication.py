"""add users table for authentication

Revision ID: ed54955faedb
Revises: 20250202_batch_jobs
Create Date: 2026-02-08 04:37:20.186429

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ed54955faedb'
down_revision: Union[str, None] = '20250202_batch_jobs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table for authentication
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('ADMIN', 'ANALYST', 'VIEWER', name='userrole'), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('force_password_change', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('last_login', sa.DateTime(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_index('ix_user_active', 'users', ['is_active', 'is_deleted'], unique=False)
    op.create_index('ix_user_role', 'users', ['role'], unique=False)
    op.create_index('ix_user_username', 'users', ['username'], unique=False)


def downgrade() -> None:
    # Drop users table
    op.drop_index('ix_user_username', table_name='users')
    op.drop_index('ix_user_role', table_name='users')
    op.drop_index('ix_user_active', table_name='users')
    op.drop_table('users')
    op.execute('DROP TYPE IF EXISTS userrole')
