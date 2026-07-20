"""add manual m-pesa payment fallback fields to mpesa_agent_configs

Revision ID: h2c3d4e5f6a8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-09 14:50:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "h2c3d4e5f6a8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mpesa_agent_configs",
        sa.Column("manual_payment_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("mpesa_agent_configs", sa.Column("manual_paybill_number", sa.String(), nullable=True))
    op.add_column("mpesa_agent_configs", sa.Column("manual_paybill_account", sa.String(), nullable=True))
    op.add_column("mpesa_agent_configs", sa.Column("manual_till_number", sa.String(), nullable=True))
    op.add_column("mpesa_agent_configs", sa.Column("manual_pochi_number", sa.String(), nullable=True))
    op.add_column("mpesa_agent_configs", sa.Column("manual_send_money_number", sa.String(), nullable=True))
    op.add_column("mpesa_agent_configs", sa.Column("manual_recipient_name", sa.String(), nullable=True))
    op.add_column("mpesa_agent_configs", sa.Column("manual_payment_note", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("mpesa_agent_configs", "manual_payment_note")
    op.drop_column("mpesa_agent_configs", "manual_recipient_name")
    op.drop_column("mpesa_agent_configs", "manual_send_money_number")
    op.drop_column("mpesa_agent_configs", "manual_pochi_number")
    op.drop_column("mpesa_agent_configs", "manual_till_number")
    op.drop_column("mpesa_agent_configs", "manual_paybill_account")
    op.drop_column("mpesa_agent_configs", "manual_paybill_number")
    op.drop_column("mpesa_agent_configs", "manual_payment_enabled")
