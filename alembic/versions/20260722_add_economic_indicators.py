"""Add economic_indicators table for public international economic data

Stores World Bank WDI country-level indicators and IMF DOTS/IMTS bilateral
trade series in one narrow time-series table keyed on
(source, indicator, reporter, counterpart, frequency, period).

Revision ID: 20260722_econ_indicators
Revises: 20260612_ingestion_jobs
Create Date: 2026-07-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '20260722_econ_indicators'
down_revision: Union[str, None] = '20260612_ingestion_jobs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'economic_indicators',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('source', sa.String(16), nullable=False),
        sa.Column('indicator_code', sa.String(64), nullable=False),
        sa.Column('indicator_name', sa.Text(), nullable=True),
        sa.Column('country_iso3', sa.String(3), nullable=False),
        # '' means "no counterpart" (country-level indicator); NOT NULL so the
        # unique constraint below actually deduplicates those rows.
        sa.Column('counterpart_iso3', sa.String(3), nullable=False, server_default=''),
        sa.Column('frequency', sa.String(1), nullable=False, server_default='A'),
        sa.Column('period', sa.String(10), nullable=False),
        sa.Column('period_date', sa.Date(), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('unit', sa.Text(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            'source', 'indicator_code', 'country_iso3', 'counterpart_iso3',
            'frequency', 'period',
            name='uq_econ_series_period'
        ),
    )

    op.create_index('ix_econ_country_period', 'economic_indicators', ['country_iso3', 'period_date'])
    op.create_index('ix_econ_pair', 'economic_indicators', ['country_iso3', 'counterpart_iso3', 'indicator_code'])
    op.create_index('ix_econ_source_indicator', 'economic_indicators', ['source', 'indicator_code'])


def downgrade() -> None:
    op.drop_table('economic_indicators')
