"""Add Power BI support

Revision ID: 006
Revises: 005_add_tool_calling_support
Create Date: 2024-01-01 12:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add Power BI support to the database."""
    
    # Add Power BI to the ConnectionPlatform enum
    # Note: This is handled by the existing enum in models.py
    # The enum already includes POWERBI = "powerbi"
    
    # Add Power BI specific configuration columns to connections table
    # This allows storing Power BI specific settings like tenant_id, etc.
    op.add_column('connections', sa.Column('powerbi_tenant_id', sa.String(), nullable=True))
    op.add_column('connections', sa.Column('powerbi_workspace_id', sa.String(), nullable=True))
    
    # Add Power BI specific settings to user_settings table
    op.add_column('user_settings', sa.Column('powerbi_auto_refresh', sa.Boolean(), nullable=True, default=True))
    op.add_column('user_settings', sa.Column('powerbi_default_workspace', sa.String(), nullable=True))
    op.add_column('user_settings', sa.Column('powerbi_embed_enabled', sa.Boolean(), nullable=True, default=True))
    
    # Create index for Power BI connections
    op.create_index('ix_connections_powerbi_tenant', 'connections', ['powerbi_tenant_id'])


def downgrade() -> None:
    """Remove Power BI support from the database."""
    
    # Remove Power BI specific columns
    op.drop_column('connections', 'powerbi_tenant_id')
    op.drop_column('connections', 'powerbi_workspace_id')
    op.drop_column('user_settings', 'powerbi_auto_refresh')
    op.drop_column('user_settings', 'powerbi_default_workspace')
    op.drop_column('user_settings', 'powerbi_embed_enabled')
    
    # Remove Power BI index
    op.drop_index('ix_connections_powerbi_tenant', 'connections') 