"""Add batch_jobs table for OpenAI batch processing tracking

Revision ID: 20250202_batch_jobs
Revises: fec28b5b115d
Create Date: 2025-02-02

This migration creates the batch_jobs table to track OpenAI Batch API jobs
for pipeline processing. Supports cluster_deconflict and canonical_deconflict
job types with comprehensive status tracking, file management, and cost tracking.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250202_batch_jobs'
down_revision = 'fec28b5b115d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Inspect existing database state for idempotent operation
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'batch_jobs' not in existing_tables:
        # Create batch_jobs table
        op.create_table(
            'batch_jobs',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),

            # Job identification
            sa.Column('job_type', sa.String(length=50), nullable=False, comment='Job type: cluster_deconflict, canonical_deconflict'),
            sa.Column('openai_batch_id', sa.String(length=255), nullable=True, comment="OpenAI's batch ID"),

            # Processing scope
            sa.Column('initiating_country', sa.String(length=100), nullable=True),
            sa.Column('date_range_start', sa.Date(), nullable=True),
            sa.Column('date_range_end', sa.Date(), nullable=True),
            sa.Column('batch_size', sa.Integer(), nullable=False, comment='Number of requests in batch'),

            # Status tracking
            sa.Column('status', sa.String(length=50), nullable=False, server_default='preparing'),
            sa.Column('progress_metadata', postgresql.JSONB(), nullable=True, comment='Progress: requests_total, requests_completed, requests_failed'),

            # File tracking
            sa.Column('input_file_path', sa.Text(), nullable=True, comment='Local or S3 path to input JSONL'),
            sa.Column('input_file_id', sa.String(length=255), nullable=True, comment='OpenAI file ID for input'),
            sa.Column('output_file_path', sa.Text(), nullable=True, comment='Local or S3 path to output JSONL'),
            sa.Column('output_file_id', sa.String(length=255), nullable=True, comment='OpenAI file ID for output'),
            sa.Column('error_file_path', sa.Text(), nullable=True, comment='Local or S3 path to errors JSONL'),
            sa.Column('error_file_id', sa.String(length=255), nullable=True, comment='OpenAI file ID for errors'),

            # Cost tracking
            sa.Column('estimated_cost', sa.Numeric(10, 4), nullable=True, comment='Estimated cost in USD'),
            sa.Column('actual_cost', sa.Numeric(10, 4), nullable=True, comment='Actual cost in USD from OpenAI'),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
            sa.Column('submitted_at', sa.DateTime(), nullable=True, comment='When batch was submitted to OpenAI'),
            sa.Column('completed_at', sa.DateTime(), nullable=True, comment='When OpenAI completed the batch'),
            sa.Column('processed_at', sa.DateTime(), nullable=True, comment='When results were processed into database'),

            # Error tracking
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),

            # Audit trail
            sa.Column('created_by', sa.String(length=255), nullable=True, comment='Username or system that created the job'),

            # Constraints
            sa.CheckConstraint(
                "status IN ('preparing', 'submitted', 'in_progress', 'completed', 'failed', 'cancelled', 'processing_results')",
                name='ck_batch_job_status'
            ),

            comment='Tracks OpenAI Batch API jobs for pipeline processing'
        )

        # Create indexes for efficient queries
        op.create_index('idx_batch_jobs_type_status', 'batch_jobs', ['job_type', 'status'])
        op.create_index('idx_batch_jobs_openai_id', 'batch_jobs', ['openai_batch_id'])
        op.create_index('idx_batch_jobs_country_dates', 'batch_jobs', ['initiating_country', 'date_range_start', 'date_range_end'])
        op.create_index('idx_batch_jobs_created', 'batch_jobs', ['created_at'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_batch_jobs_created', table_name='batch_jobs')
    op.drop_index('idx_batch_jobs_country_dates', table_name='batch_jobs')
    op.drop_index('idx_batch_jobs_openai_id', table_name='batch_jobs')
    op.drop_index('idx_batch_jobs_type_status', table_name='batch_jobs')

    # Drop table
    op.drop_table('batch_jobs')

    # Drop enum type using raw SQL
    op.execute("DROP TYPE IF EXISTS batchjobstatus CASCADE;")
