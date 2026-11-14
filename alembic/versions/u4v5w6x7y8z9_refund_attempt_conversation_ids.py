"""b2c refund attempt conversation ids

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-11-14 18:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "u4v5w6x7y8z9"
down_revision = "t3u4v5w6x7y8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "commerce_refund_attempts",
        sa.Column("conversation_id", sa.String(), nullable=True),
    )
    op.add_column(
        "commerce_refund_attempts",
        sa.Column("originator_conversation_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_commerce_refund_attempts_conversation_id",
        "commerce_refund_attempts",
        ["conversation_id"],
    )
    op.create_index(
        "ix_commerce_refund_attempts_originator_conversation_id",
        "commerce_refund_attempts",
        ["originator_conversation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_commerce_refund_attempts_originator_conversation_id",
        table_name="commerce_refund_attempts",
    )
    op.drop_index(
        "ix_commerce_refund_attempts_conversation_id",
        table_name="commerce_refund_attempts",
    )
    op.drop_column("commerce_refund_attempts", "originator_conversation_id")
    op.drop_column("commerce_refund_attempts", "conversation_id")
