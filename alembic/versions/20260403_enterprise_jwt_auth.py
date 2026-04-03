"""migrate users table to enterprise JWT auth

Remove password-based auth fields (password_hash, force_password_change, created_by)
and add enterprise_id for enterprise gateway JWT integration.

Revision ID: 20260403_enterprise_jwt
Revises: 821886869aed
Create Date: 2026-04-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260403_enterprise_jwt'
down_revision: Union[str, None] = '821886869aed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add enterprise_id column
    op.add_column('users', sa.Column('enterprise_id', sa.String(length=255), nullable=True))
    op.create_index('ix_user_enterprise_id', 'users', ['enterprise_id'], unique=True)

    # Remove password-based auth columns
    op.drop_column('users', 'password_hash')
    op.drop_column('users', 'force_password_change')
    op.drop_column('users', 'created_by')


def downgrade() -> None:
    # Re-add password-based auth columns
    op.add_column('users', sa.Column('created_by', sa.UUID(), nullable=True))
    op.add_column('users', sa.Column('force_password_change', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('users', sa.Column('password_hash', sa.String(length=255), nullable=False, server_default=''))

    # Remove enterprise_id
    op.drop_index('ix_user_enterprise_id', table_name='users')
    op.drop_column('users', 'enterprise_id')
