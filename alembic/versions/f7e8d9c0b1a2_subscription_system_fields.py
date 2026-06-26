"""subscription_system_fields

Revision ID: f7e8d9c0b1a2
Revises: 9a8b7c6d5e4f
Create Date: 2026-06-26 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f7e8d9c0b1a2'
down_revision = '9a8b7c6d5e4f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users — subscription lifecycle fields
    op.add_column('users', sa.Column('billing_cycle', sa.String(), server_default='monthly', nullable=True))
    op.add_column('users', sa.Column('trial_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('cancel_at_period_end', sa.Boolean(), server_default='false', nullable=True))
    op.add_column('users', sa.Column('last_payment_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('auto_renew_enabled', sa.Boolean(), server_default='true', nullable=True))

    # subscriptions — audit trail fields
    op.add_column('subscriptions', sa.Column('billing_cycle', sa.String(), server_default='monthly', nullable=True))
    op.add_column('subscriptions', sa.Column('payment_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('subscriptions', sa.Column('paystack_reference', sa.String(), nullable=True))
    op.create_foreign_key(
        'fk_subscriptions_payment_id',
        'subscriptions',
        'payments',
        ['payment_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # Backfill invalid tier slugs
    op.execute("""
        UPDATE users SET subscription_tier = 'starter'
        WHERE LOWER(subscription_tier) IN ('lite', 'starter')
           OR subscription_tier IN ('Starter', 'Lite');
    """)
    op.execute("""
        UPDATE users SET subscription_tier = 'business'
        WHERE subscription_tier = 'Business';
    """)
    op.execute("""
        UPDATE users SET subscription_tier = 'pro'
        WHERE subscription_tier IN ('Pro', 'Pro / Agency', 'Agency');
    """)
    op.execute("""
        UPDATE users
        SET subscription_status = 'expired', subscription_tier = 'free'
        WHERE subscription_tier NOT IN ('free', 'enterprise')
          AND subscription_end_date IS NOT NULL
          AND subscription_end_date < NOW()
          AND subscription_status NOT IN ('trial');
    """)


def downgrade() -> None:
    op.drop_constraint('fk_subscriptions_payment_id', 'subscriptions', type_='foreignkey')
    op.drop_column('subscriptions', 'paystack_reference')
    op.drop_column('subscriptions', 'payment_id')
    op.drop_column('subscriptions', 'billing_cycle')
    op.drop_column('users', 'auto_renew_enabled')
    op.drop_column('users', 'last_payment_at')
    op.drop_column('users', 'cancel_at_period_end')
    op.drop_column('users', 'trial_started_at')
    op.drop_column('users', 'billing_cycle')
