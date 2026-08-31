"""add idempotency hardening columns to processed_webhook_messages

Revision ID: n8i9j0k1l2m3
Revises: m7h8i9j0k1l3
Create Date: 2026-08-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "n8i9j0k1l2m3"
down_revision = "m7h8i9j0k1l3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Two-phase processing lifecycle: 'started' → 'completed' | 'failed'.
    # Existing rows keep NULL which is treated as 'completed' by the
    # IdempotencyService (backward compatibility — no backfill needed).
    op.add_column(
        "processed_webhook_messages",
        sa.Column("processing_status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "processed_webhook_messages",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Order ID created for this message (prevents duplicate order creation).
    op.add_column(
        "processed_webhook_messages",
        sa.Column("order_id", sa.String(), nullable=True),
    )

    # Per-operation idempotency flags.
    op.add_column(
        "processed_webhook_messages",
        sa.Column(
            "confirmation_sent",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "processed_webhook_messages",
        sa.Column(
            "receipt_sent",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("processed_webhook_messages", "receipt_sent")
    op.drop_column("processed_webhook_messages", "confirmation_sent")
    op.drop_column("processed_webhook_messages", "order_id")
    op.drop_column("processed_webhook_messages", "completed_at")
    op.drop_column("processed_webhook_messages", "processing_status")
