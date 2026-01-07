"""Add M-Pesa agent tables

Revision ID: 008
Revises: 007_add_marketplace_fields
Create Date: 2025-01-20 10:00:00.000000
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    # Create mpesa_payments table
    op.create_table(
        'mpesa_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.String(), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('phone_number', sa.String(20), nullable=False),
        sa.Column('reference', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('transaction_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('matched_invoice_id', sa.Integer(), nullable=True),
        sa.Column('match_confidence', sa.Float(), nullable=True),
        sa.Column('channel', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_mpesa_payments_user_id', 'mpesa_payments', ['user_id'])
    op.create_index('ix_mpesa_payments_transaction_id', 'mpesa_payments', ['transaction_id'], unique=True)
    op.create_index('ix_mpesa_payments_status', 'mpesa_payments', ['status'])
    op.create_index('ix_mpesa_payments_transaction_time', 'mpesa_payments', ['transaction_time'])

    # Create mpesa_agent_configs table
    op.create_table(
        'mpesa_agent_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('alert_channel_id', sa.String(), nullable=True),
        sa.Column('alert_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('auto_match_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('match_threshold', sa.Float(), nullable=False, server_default='0.8'),
        sa.Column('notification_preferences', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index('ix_mpesa_agent_configs_user_id', 'mpesa_agent_configs', ['user_id'], unique=True)


def downgrade():
    op.drop_index('ix_mpesa_agent_configs_user_id', 'mpesa_agent_configs')
    op.drop_table('mpesa_agent_configs')
    op.drop_index('ix_mpesa_payments_transaction_time', 'mpesa_payments')
    op.drop_index('ix_mpesa_payments_status', 'mpesa_payments')
    op.drop_index('ix_mpesa_payments_transaction_id', 'mpesa_payments')
    op.drop_index('ix_mpesa_payments_user_id', 'mpesa_payments')
    op.drop_table('mpesa_payments')

