"""Add alert_rules and alert_history tables for configurable analyst notifications.

Revision ID: 20260402_alert_tables
Revises: 821886869aed
Create Date: 2026-04-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '20260402_alert_tables'
down_revision: Union[str, None] = '821886869aed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from alembic import context
    bind = context.get_bind()

    # Check if tables already exist (e.g. from create_all or partial migration)
    tables_exist = bind.execute(
        sa.text("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'alert_rules')")
    ).scalar()

    if tables_exist:
        # Tables already created outside alembic — just stamp and move on
        return

    # Create enum types conditionally
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE alertconditiontype AS ENUM ('MATERIALITY_SPIKE', 'VOLUME_SURGE', 'NEW_ENTITY', 'NEW_EVENT');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE alertseverity AS ENUM ('INFO', 'WARNING', 'CRITICAL');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    alertconditiontype = sa.Enum(
        'MATERIALITY_SPIKE', 'VOLUME_SURGE', 'NEW_ENTITY', 'NEW_EVENT',
        name='alertconditiontype', create_type=False
    )
    alertseverity = sa.Enum('INFO', 'WARNING', 'CRITICAL', name='alertseverity', create_type=False)

    # Create alert_rules table
    op.create_table(
        'alert_rules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('condition_type', alertconditiontype, nullable=False),
        sa.Column('condition_params', postgresql.JSONB(), nullable=False),
        sa.Column('channels', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('channel_config', postgresql.JSONB(), nullable=True),
        sa.Column('severity', alertseverity, nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('cooldown_minutes', sa.Integer(), nullable=True),
        sa.Column('last_evaluated_at', sa.DateTime(), nullable=True),
        sa.Column('last_triggered_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_alert_rule_user', 'alert_rules', ['user_id'])
    op.create_index('ix_alert_rule_condition', 'alert_rules', ['condition_type'])
    op.create_index('ix_alert_rule_enabled', 'alert_rules', ['is_enabled', 'is_deleted'])

    # Create alert_history table
    op.create_table(
        'alert_history',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('alert_rule_id', sa.UUID(), nullable=False),
        sa.Column('triggered_at', sa.DateTime(), nullable=False),
        sa.Column('severity', alertseverity, nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('context_data', postgresql.JSONB(), nullable=True),
        sa.Column('channels_notified', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('acknowledged', sa.Boolean(), nullable=True),
        sa.Column('acknowledged_by', sa.UUID(), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ['alert_rule_id'], ['alert_rules.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_alert_history_rule', 'alert_history', ['alert_rule_id'])
    op.create_index('ix_alert_history_triggered', 'alert_history', ['triggered_at'])
    op.create_index(
        'ix_alert_history_unacked', 'alert_history',
        ['acknowledged', 'triggered_at']
    )


def downgrade() -> None:
    op.drop_index('ix_alert_history_unacked', table_name='alert_history')
    op.drop_index('ix_alert_history_triggered', table_name='alert_history')
    op.drop_index('ix_alert_history_rule', table_name='alert_history')
    op.drop_table('alert_history')

    op.drop_index('ix_alert_rule_enabled', table_name='alert_rules')
    op.drop_index('ix_alert_rule_condition', table_name='alert_rules')
    op.drop_index('ix_alert_rule_user', table_name='alert_rules')
    op.drop_table('alert_rules')

    op.execute('DROP TYPE IF EXISTS alertconditiontype')
    op.execute('DROP TYPE IF EXISTS alertseverity')
