"""Add password reset and remember me fields to User model

Revision ID: 003
Revises: 002
Create Date: 2024-01-01 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    # Add password reset fields
    op.add_column('users', sa.Column('password_reset_token', sa.String(), nullable=True))
    op.add_column('users', sa.Column('password_reset_expires', sa.DateTime(timezone=True), nullable=True))
    
    # Add remember me fields
    op.add_column('users', sa.Column('remember_me_token', sa.String(), nullable=True))
    op.add_column('users', sa.Column('remember_me_expires', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    # Remove password reset fields
    op.drop_column('users', 'password_reset_token')
    op.drop_column('users', 'password_reset_expires')
    
    # Remove remember me fields
    op.drop_column('users', 'remember_me_token')
    op.drop_column('users', 'remember_me_expires') 