"""auto_generated_20260611_120800

Revision ID: 9a8b7c6d5e4f
Revises: a1b2c3d4e5f6
Create Date: 2026-06-11 12:08:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '9a8b7c6d5e4f'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # WhatsAppQuickReply table
    op.create_table('whatsapp_quick_replies',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('shortcut', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'shortcut', name='uq_user_quick_reply_shortcut')
    )
    op.create_index(op.f('ix_whatsapp_quick_replies_id'), 'whatsapp_quick_replies', ['id'], unique=False)
    op.create_index(op.f('ix_whatsapp_quick_replies_user_id'), 'whatsapp_quick_replies', ['user_id'], unique=False)

    # WhatsAppContact columns
    op.add_column('whatsapp_contacts', sa.Column('assigned_to_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('whatsapp_contacts', sa.Column('status', sa.String(), nullable=True, server_default='open'))
    op.add_column('whatsapp_contacts', sa.Column('is_starred', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('whatsapp_contacts', sa.Column('unread_count', sa.Integer(), nullable=True, server_default='0'))
    
    op.create_index(op.f('ix_whatsapp_contacts_assigned_to_id'), 'whatsapp_contacts', ['assigned_to_id'], unique=False)
    op.create_foreign_key('fk_whatsapp_contacts_assigned_to_id_users', 'whatsapp_contacts', 'users', ['assigned_to_id'], ['id'])

    # WhatsAppMessage column
    op.add_column('whatsapp_messages', sa.Column('is_internal_note', sa.Boolean(), nullable=True, server_default='false'))


def downgrade() -> None:
    # WhatsAppMessage
    op.drop_column('whatsapp_messages', 'is_internal_note')

    # WhatsAppContact
    op.drop_constraint('fk_whatsapp_contacts_assigned_to_id_users', 'whatsapp_contacts', type_='foreignkey')
    op.drop_index(op.f('ix_whatsapp_contacts_assigned_to_id'), table_name='whatsapp_contacts')
    op.drop_column('whatsapp_contacts', 'unread_count')
    op.drop_column('whatsapp_contacts', 'is_starred')
    op.drop_column('whatsapp_contacts', 'status')
    op.drop_column('whatsapp_contacts', 'assigned_to_id')

    # WhatsAppQuickReply
    op.drop_index(op.f('ix_whatsapp_quick_replies_user_id'), table_name='whatsapp_quick_replies')
    op.drop_index(op.f('ix_whatsapp_quick_replies_id'), table_name='whatsapp_quick_replies')
    op.drop_table('whatsapp_quick_replies')
