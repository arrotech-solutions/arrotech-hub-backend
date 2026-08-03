"""Add user onboarding wizard profile fields

Revision ID: l6g7h8i9j0k2
Revises: k5f6g7h8i9d1
Create Date: 2026-08-03 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "l6g7h8i9j0k2"
down_revision = "k5f6g7h8i9d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("onboarding_version", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("primary_goal", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column("secondary_goals", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("users", sa.Column("workspace_type", sa.String(), nullable=True))
    op.add_column("users", sa.Column("onboarding_role", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column("preferred_apps", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("users", sa.Column("activation_event", sa.String(), nullable=True))
    op.add_column("users", sa.Column("onboarding_step", sa.Integer(), nullable=True))

    # Grandfather existing accounts so they are not forced through the new wizard
    op.execute(
        sa.text(
            "UPDATE users SET onboarding_completed_at = COALESCE(created_at, NOW()), "
            "onboarding_version = 1 "
            "WHERE onboarding_completed_at IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("users", "onboarding_step")
    op.drop_column("users", "activation_event")
    op.drop_column("users", "preferred_apps")
    op.drop_column("users", "onboarding_role")
    op.drop_column("users", "workspace_type")
    op.drop_column("users", "secondary_goals")
    op.drop_column("users", "primary_goal")
    op.drop_column("users", "onboarding_version")
    op.drop_column("users", "onboarding_completed_at")
