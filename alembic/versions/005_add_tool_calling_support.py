"""add tool calling support

Revision ID: 005
Revises: 004
Create Date: 2024-01-01 00:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add tool_call_id column to messages table
    op.add_column('messages', sa.Column('tool_call_id', sa.String(), nullable=True))


def downgrade() -> None:
    # Remove tool_call_id column from messages table
    op.drop_column('messages', 'tool_call_id') 