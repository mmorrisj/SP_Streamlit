"""Add aiddata_projects and aiddata_locations tables

Imports AidData's Global Chinese Development Finance Dataset v3.0 schema.
Stores 20,985 project records and sub-national ADM1/ADM2 location data.

Revision ID: 20260224_aiddata_tables
Revises: 20260218_event_summary_cols
Create Date: 2026-02-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '20260224_aiddata_tables'
down_revision: Union[str, None] = '20260218_event_summary_cols'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'aiddata_projects',
        sa.Column('aiddata_record_id', sa.Integer(), primary_key=True),
        sa.Column('aiddata_parent_id', sa.Integer(), nullable=True),
        sa.Column('recommended_for_aggregates', sa.Boolean(), nullable=True),
        sa.Column('umbrella', sa.Boolean(), nullable=True),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('intent', sa.Text(), nullable=True),
        # Geography
        sa.Column('financier_country', sa.Text(), nullable=True),
        sa.Column('recipient', sa.Text(), nullable=True),
        sa.Column('recipient_iso3', sa.String(3), nullable=True),
        sa.Column('recipient_region', sa.Text(), nullable=True),
        sa.Column('oda_eligible_recipient', sa.Text(), nullable=True),
        sa.Column('oecd_oda_income_group', sa.Text(), nullable=True),
        # Timeline
        sa.Column('commitment_year', sa.Integer(), nullable=True),
        sa.Column('implementation_start_year', sa.Integer(), nullable=True),
        sa.Column('completion_year', sa.Integer(), nullable=True),
        sa.Column('commitment_date', sa.Date(), nullable=True),
        # Financial classification
        sa.Column('flow_type', sa.Text(), nullable=True),
        sa.Column('flow_type_simplified', sa.Text(), nullable=True),
        sa.Column('flow_class', sa.Text(), nullable=True),
        # Amounts
        sa.Column('amount_original_currency', sa.Float(), nullable=True),
        sa.Column('original_currency', sa.Text(), nullable=True),
        sa.Column('amount_usd_2021', sa.Float(), nullable=True),
        sa.Column('amount_nominal_usd', sa.Float(), nullable=True),
        sa.Column('adjusted_amount_usd_2021', sa.Float(), nullable=True),
        sa.Column('adjusted_amount_nominal_usd', sa.Float(), nullable=True),
        # Sector
        sa.Column('sector_code', sa.Integer(), nullable=True),
        sa.Column('sector_name', sa.Text(), nullable=True),
        sa.Column('infrastructure', sa.Boolean(), nullable=True),
        sa.Column('covid', sa.Boolean(), nullable=True),
        # Agencies
        sa.Column('funding_agencies', sa.Text(), nullable=True),
        sa.Column('funding_agencies_type', sa.Text(), nullable=True),
        sa.Column('cofinanced', sa.Boolean(), nullable=True),
        sa.Column('cofinancing_agencies', sa.Text(), nullable=True),
        sa.Column('direct_receiving_agencies', sa.Text(), nullable=True),
        sa.Column('direct_receiving_agencies_type', sa.Text(), nullable=True),
        sa.Column('implementing_agencies', sa.Text(), nullable=True),
        sa.Column('on_lending', sa.Boolean(), nullable=True),
        # Description
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('location_narrative', sa.Text(), nullable=True),
        # Loan terms
        sa.Column('maturity', sa.Float(), nullable=True),
        sa.Column('interest_rate', sa.Float(), nullable=True),
        sa.Column('grace_period', sa.Float(), nullable=True),
        sa.Column('management_fee', sa.Float(), nullable=True),
        sa.Column('commitment_fee', sa.Float(), nullable=True),
        sa.Column('grant_element_imf', sa.Float(), nullable=True),
        sa.Column('grant_element_oecd_cashflow', sa.Float(), nullable=True),
        # Loan flags
        sa.Column('financial_distress', sa.Boolean(), nullable=True),
        sa.Column('guarantee_provided', sa.Boolean(), nullable=True),
        sa.Column('collateralized', sa.Boolean(), nullable=True),
        sa.Column('rescue', sa.Boolean(), nullable=True),
        sa.Column('level_of_public_liability', sa.Text(), nullable=True),
        # Geographic precision
        sa.Column('geographic_precision', sa.Text(), nullable=True),
        sa.Column('adm1_available', sa.Boolean(), nullable=True),
        sa.Column('adm2_available', sa.Boolean(), nullable=True),
        # Quality scores
        sa.Column('source_quality_score', sa.Integer(), nullable=True),
        sa.Column('data_completeness_score', sa.Integer(), nullable=True),
        sa.Column('implementation_detail_score', sa.Integer(), nullable=True),
        sa.Column('loan_detail_score', sa.Integer(), nullable=True),
        sa.Column('total_source_count', sa.Integer(), nullable=True),
        sa.Column('official_source_count', sa.Integer(), nullable=True),
    )

    op.create_index('ix_aiddata_recipient_iso3', 'aiddata_projects', ['recipient_iso3'])
    op.create_index('ix_aiddata_commitment_year', 'aiddata_projects', ['commitment_year'])
    op.create_index('ix_aiddata_recipient_year', 'aiddata_projects', ['recipient_iso3', 'commitment_year'])
    op.create_index('ix_aiddata_flow_class', 'aiddata_projects', ['flow_class'])
    op.create_index('ix_aiddata_sector', 'aiddata_projects', ['sector_code'])
    op.create_index('ix_aiddata_status', 'aiddata_projects', ['status'])

    op.create_table(
        'aiddata_locations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'aiddata_record_id', sa.Integer(),
            sa.ForeignKey('aiddata_projects.aiddata_record_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('adm_level', sa.String(4), nullable=False),
        sa.Column('shape_id', sa.Text(), nullable=True),
        sa.Column('shape_group', sa.String(3), nullable=True),
        sa.Column('shape_name', sa.Text(), nullable=True),
        sa.Column('intersection_ratio', sa.Float(), nullable=True),
        sa.Column('even_split_ratio', sa.Float(), nullable=True),
        sa.Column('intersection_ratio_commitment_value', sa.Float(), nullable=True),
        sa.Column('even_split_ratio_commitment_value', sa.Float(), nullable=True),
        sa.Column('centroid_longitude', sa.Float(), nullable=True),
        sa.Column('centroid_latitude', sa.Float(), nullable=True),
    )

    op.create_index('ix_aiddata_loc_record_id', 'aiddata_locations', ['aiddata_record_id'])
    op.create_index('ix_aiddata_loc_adm_level', 'aiddata_locations', ['adm_level'])


def downgrade() -> None:
    op.drop_table('aiddata_locations')
    op.drop_table('aiddata_projects')
