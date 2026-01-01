"""Add user settings table

Revision ID: 001
Revises: None (initial migration)
Create Date: 2024-01-01 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create user_settings table
    op.create_table('user_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('email_notifications', sa.Boolean(), nullable=False, default=True),
        sa.Column('slack_notifications', sa.Boolean(), nullable=False, default=False),
        sa.Column('webhook_notifications', sa.Boolean(), nullable=False, default=False),
        sa.Column('notification_webhook_url', sa.String(), nullable=True),
        sa.Column('api_rate_limit', sa.Integer(), nullable=False, default=1000),
        sa.Column('api_timeout', sa.Integer(), nullable=False, default=30),
        sa.Column('auto_refresh_tokens', sa.Boolean(), nullable=False, default=True),
        sa.Column('dashboard_theme', sa.String(), nullable=False, default='light'),
        sa.Column('dashboard_layout', sa.String(), nullable=False, default='default'),
        sa.Column('show_analytics', sa.Boolean(), nullable=False, default=True),
        sa.Column('show_usage_stats', sa.Boolean(), nullable=False, default=True),
        sa.Column('auto_sync_connections', sa.Boolean(), nullable=False, default=True),
        sa.Column('sync_frequency', sa.String(), nullable=False, default='hourly'),
        sa.Column('backup_connections', sa.Boolean(), nullable=False, default=True),
        sa.Column('two_factor_enabled', sa.Boolean(), nullable=False, default=False),
        sa.Column('session_timeout', sa.Integer(), nullable=False, default=30),
        sa.Column('ip_whitelist', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('custom_settings', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create index on user_id
    op.create_index(op.f('ix_user_settings_user_id'), 'user_settings', ['user_id'], unique=True)


def downgrade():
    # Drop index
    op.drop_index(op.f('ix_user_settings_user_id'), table_name='user_settings')
    
    # Drop table
    op.drop_table('user_settings') 