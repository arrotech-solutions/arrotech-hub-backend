"""Add tool_audit_log and tool_proposals for Ask AI HITL

Revision ID: k5f6g7h8i9d1
Revises: j4e5f6g7h8c0
Create Date: 2026-07-26 22:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "k5f6g7h8i9d1"
down_revision = "j4e5f6g7h8c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("args_hash", sa.String(64), nullable=True),
        sa.Column("arguments_preview", sa.JSON(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_tool_audit_user_created", "tool_audit_log", ["user_id", "created_at"])
    op.create_index("ix_tool_audit_tool_name", "tool_audit_log", ["tool_name"])

    op.create_table(
        "tool_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
    )
    op.create_index("ix_tool_proposals_user_status", "tool_proposals", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_tool_proposals_user_status", table_name="tool_proposals")
    op.drop_table("tool_proposals")
    op.drop_index("ix_tool_audit_tool_name", table_name="tool_audit_log")
    op.drop_index("ix_tool_audit_user_created", table_name="tool_audit_log")
    op.drop_table("tool_audit_log")
