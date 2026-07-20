"""add stk_payment_attempts table

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-30 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stk_payment_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_id", sa.String(), nullable=False),
        sa.Column("checkout_request_id", sa.String(), nullable=True),
        sa.Column("merchant_request_id", sa.String(), nullable=True),
        sa.Column("mpesa_phone", sa.String(length=20), nullable=True),
        sa.Column("whatsapp_phone", sa.String(length=20), nullable=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), server_default="KES", nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result_code", sa.String(length=16), nullable=True),
        sa.Column("result_desc", sa.Text(), nullable=True),
        sa.Column("customer_message", sa.Text(), nullable=True),
        sa.Column("failure_notified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_stk_payment_attempts_user_id", "stk_payment_attempts", ["user_id"])
    op.create_index("ix_stk_payment_attempts_order_id", "stk_payment_attempts", ["order_id"])
    op.create_index("ix_stk_payment_attempts_checkout_request_id", "stk_payment_attempts", ["checkout_request_id"])
    op.create_index("ix_stk_payment_attempts_status", "stk_payment_attempts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_stk_payment_attempts_status", table_name="stk_payment_attempts")
    op.drop_index("ix_stk_payment_attempts_checkout_request_id", table_name="stk_payment_attempts")
    op.drop_index("ix_stk_payment_attempts_order_id", table_name="stk_payment_attempts")
    op.drop_index("ix_stk_payment_attempts_user_id", table_name="stk_payment_attempts")
    op.drop_table("stk_payment_attempts")
