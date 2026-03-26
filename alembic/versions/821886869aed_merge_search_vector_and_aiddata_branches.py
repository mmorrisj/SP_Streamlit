"""merge search_vector and aiddata branches

Revision ID: 821886869aed
Revises: 006_search_vector, 20260224_aiddata_tables
Create Date: 2026-03-26 13:33:52.540352

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '821886869aed'
down_revision: Union[str, None] = ('006_search_vector', '20260224_aiddata_tables')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
