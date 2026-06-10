"""add_assigned_to_id_to_whatsapp_contacts

Revision ID: a1b2c3d4e5f6
Revises: e24ae191ac35
Create Date: 2026-06-10 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'e24ae191ac35'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'whatsapp_contacts',
        sa.Column(
            'assigned_to_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=True,
        )
    )
    op.create_index(
        'ix_whatsapp_contacts_assigned_to_id',
        'whatsapp_contacts',
        ['assigned_to_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_whatsapp_contacts_assigned_to_id', table_name='whatsapp_contacts')
    op.drop_column('whatsapp_contacts', 'assigned_to_id')