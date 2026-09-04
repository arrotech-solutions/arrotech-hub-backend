"""add parent_span_id to observability_logs

Revision ID: r1s2t3u4v5w6
Revises: q0r1s2t3u4v5
Create Date: 2026-09-04 14:42:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'r1s2t3u4v5w6'
down_revision = 'q0r1s2t3u4v5'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('observability_logs', sa.Column('parent_span_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_observability_logs_parent_span_id'), 'observability_logs', ['parent_span_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_observability_logs_parent_span_id'), table_name='observability_logs')
    op.drop_column('observability_logs', 'parent_span_id')
