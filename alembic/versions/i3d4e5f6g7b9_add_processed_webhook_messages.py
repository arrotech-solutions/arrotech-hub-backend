"""add processed_webhook_messages idempotency table

Revision ID: i3d4e5f6g7b9
Revises: h2c3d4e5f6a8
Create Date: 2026-07-15 01:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "i3d4e5f6g7b9"
down_revision = "h2c3d4e5f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processed_webhook_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("whatsapp_message_id", sa.String(), nullable=False),
        sa.Column("processing_result", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    # The unique constraint IS the idempotency guarantee.
    # INSERT ... ON CONFLICT DO NOTHING on this constraint atomically
    # prevents duplicate processing even when two Celery workers race.
    op.create_unique_constraint(
        "uq_processed_user_wa_msg",
        "processed_webhook_messages",
        ["user_id", "whatsapp_message_id"],
    )
    op.create_index(
        "ix_processed_webhook_messages_user_id",
        "processed_webhook_messages",
        ["user_id"],
    )
    op.create_index(
        "ix_processed_webhook_created_at",
        "processed_webhook_messages",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_processed_webhook_created_at",
        table_name="processed_webhook_messages",
    )
    op.drop_index(
        "ix_processed_webhook_messages_user_id",
        table_name="processed_webhook_messages",
    )
    op.drop_constraint(
        "uq_processed_user_wa_msg",
        "processed_webhook_messages",
        type_="unique",
    )
    op.drop_table("processed_webhook_messages")
