"""add avatar_url to whatsapp_contacts

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-07-05 20:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_contacts",
        sa.Column("avatar_url", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("whatsapp_contacts", "avatar_url")
