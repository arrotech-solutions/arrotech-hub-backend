"""Add WhatsApp Broadcast features

Revision ID: c4f187280349
Revises: f7e8d9c0b1a2
Create Date: 2026-06-28 15:36:42.755346

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4f187280349'
down_revision = 'f7e8d9c0b1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WhatsAppContact additions
    op.add_column('whatsapp_contacts', sa.Column('opted_out', sa.Boolean(), server_default='false', nullable=True))
    op.add_column('whatsapp_contacts', sa.Column('opted_out_at', sa.DateTime(timezone=True), nullable=True))

    # WhatsAppBroadcast additions
    op.add_column('whatsapp_broadcasts', sa.Column('media_url', sa.String(), nullable=True))
    op.add_column('whatsapp_broadcasts', sa.Column('media_type', sa.String(), nullable=True))
    op.add_column('whatsapp_broadcasts', sa.Column('send_rate', sa.Integer(), server_default='10', nullable=True))
    op.add_column('whatsapp_broadcasts', sa.Column('error_summary', sa.JSON(), nullable=True))


def downgrade() -> None:
    # WhatsAppBroadcast removals
    op.drop_column('whatsapp_broadcasts', 'error_summary')
    op.drop_column('whatsapp_broadcasts', 'send_rate')
    op.drop_column('whatsapp_broadcasts', 'media_type')
    op.drop_column('whatsapp_broadcasts', 'media_url')

    # WhatsAppContact removals
    op.drop_column('whatsapp_contacts', 'opted_out_at')
    op.drop_column('whatsapp_contacts', 'opted_out') 