"""whatsapp inbox ux: snooze, sla, inbox settings

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-05 20:35:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_contacts",
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "whatsapp_contacts",
        sa.Column("first_inbound_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "whatsapp_business_profiles",
        sa.Column("inbox_settings", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("whatsapp_business_profiles", "inbox_settings")
    op.drop_column("whatsapp_contacts", "first_inbound_at")
    op.drop_column("whatsapp_contacts", "snoozed_until")
