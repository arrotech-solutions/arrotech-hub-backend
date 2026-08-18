"""Add checklist persistence columns to users

Revision ID: m7h8i9j0k1l3
Revises: l6g7h8i9j0k2
Create Date: 2026-08-18 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "m7h8i9j0k1l3"
down_revision = "l6g7h8i9j0k2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("checklist_dismissed", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )
    op.add_column(
        "users",
        sa.Column("checklist_done_ids", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )

    # Grandfather: users already marked with onboarding_version=0 should never see the checklist
    op.execute(
        sa.text(
            "UPDATE users SET checklist_dismissed = true "
            "WHERE onboarding_version = 0 AND checklist_dismissed IS NOT TRUE"
        )
    )


def downgrade() -> None:
    op.drop_column("users", "checklist_done_ids")
    op.drop_column("users", "checklist_dismissed")
