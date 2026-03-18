"""consolidated_mpesa_daraja_columns

Revision ID: f7a8b9c0d1e2
Revises: 536e7ddf484a
Create Date: 2026-03-18 04:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f7a8b9c0d1e2'
down_revision = '536e7ddf484a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add all the plain string columns
    op.add_column('mpesa_agent_configs', sa.Column('daraja_consumer_key', sa.String(), nullable=True))
    op.add_column('mpesa_agent_configs', sa.Column('daraja_consumer_secret', sa.String(), nullable=True))
    op.add_column('mpesa_agent_configs', sa.Column('daraja_passkey', sa.String(), nullable=True))
    op.add_column('mpesa_agent_configs', sa.Column('daraja_shortcode', sa.String(), nullable=True))
    op.add_column('mpesa_agent_configs', sa.Column('callback_url_override', sa.String(), nullable=True))
    
    # 2. Add the webhook_secret with a unique index
    op.add_column('mpesa_agent_configs', sa.Column('webhook_secret', sa.String(), nullable=True))
    op.create_index(op.f('ix_mpesa_agent_configs_webhook_secret'), 'mpesa_agent_configs', ['webhook_secret'], unique=True)
    
    # 3. Add the environment column safely
    op.add_column('mpesa_agent_configs', sa.Column('daraja_environment', sa.String(), server_default='sandbox', nullable=True))
    op.execute("UPDATE mpesa_agent_configs SET daraja_environment = 'sandbox'")
    op.alter_column('mpesa_agent_configs', 'daraja_environment', nullable=False)


def downgrade() -> None:
    op.drop_column('mpesa_agent_configs', 'daraja_environment')
    op.drop_index(op.f('ix_mpesa_agent_configs_webhook_secret'), table_name='mpesa_agent_configs')
    op.drop_column('mpesa_agent_configs', 'webhook_secret')
    op.drop_column('mpesa_agent_configs', 'callback_url_override')
    op.drop_column('mpesa_agent_configs', 'daraja_shortcode')
    op.drop_column('mpesa_agent_configs', 'daraja_passkey')
    op.drop_column('mpesa_agent_configs', 'daraja_consumer_secret')
    op.drop_column('mpesa_agent_configs', 'daraja_consumer_key')
