"""Add marketplace and sharing fields to workflows

Revision ID: 007_add_marketplace_fields
Revises: 006_add_powerbi_support
Create Date: 2025-12-31
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    # Add visibility enum type
    visibility_enum = sa.Enum('private', 'unlisted', 'public', 'marketplace', name='workflowvisibility')
    visibility_enum.create(op.get_bind(), checkfirst=True)
    
    # Add license enum type
    license_enum = sa.Enum('free', 'personal', 'commercial', 'enterprise', name='workflowlicense')
    license_enum.create(op.get_bind(), checkfirst=True)
    
    # Add new columns to workflows table
    op.add_column('workflows', sa.Column('visibility', sa.Enum('private', 'unlisted', 'public', 'marketplace', name='workflowvisibility'), nullable=False, server_default='private'))
    op.add_column('workflows', sa.Column('share_code', sa.String(), nullable=True))
    op.add_column('workflows', sa.Column('license_type', sa.Enum('free', 'personal', 'commercial', 'enterprise', name='workflowlicense'), nullable=False, server_default='free'))
    op.add_column('workflows', sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('workflows', sa.Column('currency', sa.String(), nullable=True))
    op.add_column('workflows', sa.Column('category', sa.String(), nullable=True))
    op.add_column('workflows', sa.Column('tags', sa.JSON(), nullable=True))
    op.add_column('workflows', sa.Column('required_connections', sa.JSON(), nullable=True))
    op.add_column('workflows', sa.Column('downloads_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('workflows', sa.Column('rating_sum', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('workflows', sa.Column('rating_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('workflows', sa.Column('author_name', sa.String(), nullable=True))
    op.add_column('workflows', sa.Column('preview_image', sa.String(), nullable=True))
    
    # Create unique index on share_code
    op.create_index('ix_workflows_share_code', 'workflows', ['share_code'], unique=True)
    
    # Create workflow_downloads table
    op.create_table(
        'workflow_downloads',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('workflow_id', sa.Integer(), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('downloaded_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('source_version', sa.Integer(), nullable=True),
        sa.Column('imported_workflow_id', sa.Integer(), nullable=True),
    )
    op.create_index('ix_workflow_downloads_workflow_id', 'workflow_downloads', ['workflow_id'])
    op.create_index('ix_workflow_downloads_user_id', 'workflow_downloads', ['user_id'])
    
    # Create workflow_reviews table
    op.create_table(
        'workflow_reviews',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('workflow_id', sa.Integer(), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index('ix_workflow_reviews_workflow_id', 'workflow_reviews', ['workflow_id'])
    op.create_index('ix_workflow_reviews_user_id', 'workflow_reviews', ['user_id'])
    # Unique constraint: one review per user per workflow
    op.create_unique_constraint('uq_workflow_reviews_user_workflow', 'workflow_reviews', ['workflow_id', 'user_id'])


def downgrade():
    # Drop workflow_reviews table
    op.drop_constraint('uq_workflow_reviews_user_workflow', 'workflow_reviews', type_='unique')
    op.drop_index('ix_workflow_reviews_user_id', 'workflow_reviews')
    op.drop_index('ix_workflow_reviews_workflow_id', 'workflow_reviews')
    op.drop_table('workflow_reviews')
    
    # Drop workflow_downloads table
    op.drop_index('ix_workflow_downloads_user_id', 'workflow_downloads')
    op.drop_index('ix_workflow_downloads_workflow_id', 'workflow_downloads')
    op.drop_table('workflow_downloads')
    
    # Drop columns from workflows
    op.drop_index('ix_workflows_share_code', 'workflows')
    op.drop_column('workflows', 'preview_image')
    op.drop_column('workflows', 'author_name')
    op.drop_column('workflows', 'rating_count')
    op.drop_column('workflows', 'rating_sum')
    op.drop_column('workflows', 'downloads_count')
    op.drop_column('workflows', 'required_connections')
    op.drop_column('workflows', 'tags')
    op.drop_column('workflows', 'category')
    op.drop_column('workflows', 'currency')
    op.drop_column('workflows', 'price')
    op.drop_column('workflows', 'license_type')
    op.drop_column('workflows', 'share_code')
    op.drop_column('workflows', 'visibility')
    
    # Drop enum types
    sa.Enum(name='workflowlicense').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='workflowvisibility').drop(op.get_bind(), checkfirst=True)

