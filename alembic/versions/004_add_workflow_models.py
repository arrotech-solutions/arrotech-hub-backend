"""Add workflow models

Revision ID: 004
Revises: 003_add_chat_models
Create Date: 2024-01-01 00:00:00.000000

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003_add_chat_models'
branch_labels = None
depends_on = None


def upgrade():
    # Create workflows table
    op.create_table('workflows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=True),
        sa.Column('is_template', sa.Boolean(), nullable=True),
        sa.Column('trigger_type', sa.String(), nullable=True),
        sa.Column('trigger_config', sa.JSON(), nullable=True),
        sa.Column('variables', sa.JSON(), nullable=True),
        sa.Column('workflow_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflows_id'), 'workflows', ['id'], unique=False)

    # Create workflow_steps table
    op.create_table('workflow_steps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('step_number', sa.Integer(), nullable=False),
        sa.Column('tool_name', sa.String(), nullable=False),
        sa.Column('tool_parameters', sa.JSON(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('condition', sa.JSON(), nullable=True),
        sa.Column('retry_config', sa.JSON(), nullable=True),
        sa.Column('timeout', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_steps_id'), 'workflow_steps', ['id'], unique=False)

    # Create workflow_executions table
    op.create_table('workflow_executions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('trigger_type', sa.String(), nullable=True),
        sa.Column('trigger_data', sa.JSON(), nullable=True),
        sa.Column('input_data', sa.JSON(), nullable=True),
        sa.Column('output_data', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_executions_id'), 'workflow_executions', ['id'], unique=False)

    # Create workflow_step_executions table
    op.create_table('workflow_step_executions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_execution_id', sa.Integer(), nullable=False),
        sa.Column('step_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('input_data', sa.JSON(), nullable=True),
        sa.Column('output_data', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['step_id'], ['workflow_steps.id'], ),
        sa.ForeignKeyConstraint(['workflow_execution_id'], ['workflow_executions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_step_executions_id'), 'workflow_step_executions', ['id'], unique=False)


def downgrade():
    # Drop workflow_step_executions table
    op.drop_index(op.f('ix_workflow_step_executions_id'), table_name='workflow_step_executions')
    op.drop_table('workflow_step_executions')

    # Drop workflow_executions table
    op.drop_index(op.f('ix_workflow_executions_id'), table_name='workflow_executions')
    op.drop_table('workflow_executions')

    # Drop workflow_steps table
    op.drop_index(op.f('ix_workflow_steps_id'), table_name='workflow_steps')
    op.drop_table('workflow_steps')

    # Drop workflows table
    op.drop_index(op.f('ix_workflows_id'), table_name='workflows')
    op.drop_table('workflows') 