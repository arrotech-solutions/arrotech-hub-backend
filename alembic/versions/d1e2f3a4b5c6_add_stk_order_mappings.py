"""add stk_order_mappings table

Revision ID: d1e2f3a4b5c6
Revises: c4f187280349
Create Date: 2026-06-30 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d1e2f3a4b5c6"
down_revision = "c4f187280349"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stk_order_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_id", sa.String(), nullable=False),
        sa.Column("checkout_request_id", sa.String(), nullable=True),
        sa.Column("merchant_request_id", sa.String(), nullable=True),
        sa.Column("whatsapp_sender", sa.String(length=20), nullable=True),
        sa.Column("mpesa_phone", sa.String(length=20), nullable=True),
        sa.Column("platform", sa.String(length=32), server_default="whatsapp", nullable=False),
        sa.Column("storage_config", sa.JSON(), nullable=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), server_default="KES", nullable=False),
        sa.Column("payment_notified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_stk_order_mappings_user_id", "stk_order_mappings", ["user_id"])
    op.create_index("ix_stk_order_mappings_order_id", "stk_order_mappings", ["order_id"])
    op.create_index(
        "ix_stk_order_mappings_checkout_request_id",
        "stk_order_mappings",
        ["checkout_request_id"],
        unique=True,
    )
    op.create_index(
        "ix_stk_order_mappings_merchant_request_id",
        "stk_order_mappings",
        ["merchant_request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_stk_order_mappings_merchant_request_id", table_name="stk_order_mappings")
    op.drop_index("ix_stk_order_mappings_checkout_request_id", table_name="stk_order_mappings")
    op.drop_index("ix_stk_order_mappings_order_id", table_name="stk_order_mappings")
    op.drop_index("ix_stk_order_mappings_user_id", table_name="stk_order_mappings")
    op.drop_table("stk_order_mappings")
