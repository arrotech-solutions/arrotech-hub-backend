"""add phone_number_hash to observability_logs

Revision ID: q0r1s2t3u4v5
Revises: p9q0r1s2t3u6
Create Date: 2026-09-03 13:16:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'q0r1s2t3u4v5'
down_revision = 'p9q0r1s2t3u6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('observability_logs', sa.Column('phone_number_hash', sa.String(), nullable=True))
    op.create_index(op.f('ix_observability_logs_phone_number_hash'), 'observability_logs', ['phone_number_hash'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_observability_logs_phone_number_hash'), table_name='observability_logs')
    op.drop_column('observability_logs', 'phone_number_hash')
