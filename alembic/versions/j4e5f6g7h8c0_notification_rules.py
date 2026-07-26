"""Add notification_rules, quiet_hours, digest; migrate marketplace prefs; notification index

Revision ID: j4e5f6g7h8c0
Revises: i3d4e5f6g7b9
Create Date: 2026-07-26 13:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "j4e5f6g7h8c0"
down_revision = "i3d4e5f6g7b9"
branch_labels = None
depends_on = None

DEFAULT_RULES = {
    "billing": {"in_app": True, "email": True, "slack": False, "webhook": False},
    "security": {"in_app": True, "email": True, "slack": True, "webhook": False},
    "workflows": {"in_app": True, "email": False, "slack": True, "webhook": False},
    "agents": {"in_app": True, "email": False, "slack": False, "webhook": False},
    "messaging": {"in_app": True, "email": False, "slack": False, "webhook": False},
    "commerce": {"in_app": True, "email": True, "slack": True, "webhook": False},
    "marketplace": {"in_app": True, "email": True, "slack": False, "webhook": False},
    "system": {"in_app": True, "email": True, "slack": False, "webhook": False},
}


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("notification_rules", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "user_settings",
        sa.Column("quiet_hours", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "user_settings",
        sa.Column("digest_email_daily", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    # Backfill defaults for existing settings rows
    import json
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE user_settings SET notification_rules = CAST(:rules AS json) "
            "WHERE notification_rules IS NULL"
        ),
        {"rules": json.dumps(DEFAULT_RULES)},
    )

    # Migrate marketplace prefs from user_preferences into marketplace category rules
    # when user_preferences rows exist
    rows = conn.execute(
        sa.text(
            """
            SELECT up.user_id,
                   up.email_on_download, up.email_on_sale, up.email_on_review, up.email_on_follower,
                   up.notify_on_download, up.notify_on_sale, up.notify_on_review, up.notify_on_follower
            FROM user_preferences up
            """
        )
    ).fetchall()

    for row in rows:
        user_id = row[0]
        email_any = any(bool(x) for x in row[1:5] if x is not None) if True else True
        # Conservative merge: email if any email_on_* True; in_app if any notify_on_* True
        email_vals = [row[1], row[2], row[3], row[4]]
        notify_vals = [row[5], row[6], row[7], row[8]]
        email_on = any(v is not False for v in email_vals)  # default True if None
        # Prefer explicit False: if all email are False, turn off
        if all(v is False for v in email_vals if v is not None) and any(v is False for v in email_vals):
            email_on = False
        in_app = True
        if all(v is False for v in notify_vals if v is not None) and any(v is False for v in notify_vals):
            in_app = False

        rules = dict(DEFAULT_RULES)
        rules["marketplace"] = {
            "in_app": in_app,
            "email": email_on,
            "slack": False,
            "webhook": False,
        }
        conn.execute(
            sa.text(
                """
                UPDATE user_settings
                SET notification_rules = CAST(:rules AS json)
                WHERE user_id = :uid
                """
            ),
            {"rules": json.dumps(rules), "uid": str(user_id)},
        )

    op.create_index(
        "ix_notifications_user_read_created",
        "notifications",
        ["user_id", "is_read", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_read_created", table_name="notifications")
    op.drop_column("user_settings", "digest_email_daily")
    op.drop_column("user_settings", "quiet_hours")
    op.drop_column("user_settings", "notification_rules")
