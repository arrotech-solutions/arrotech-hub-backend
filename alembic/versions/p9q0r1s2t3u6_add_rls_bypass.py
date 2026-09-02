"""add rls bypass for system tasks

Revision ID: p9q0r1s2t3u6
Revises: p9q0r1s2t3u5
Create Date: 2026-09-02 13:16:00.000000

Update RLS policies to allow an explicit bypass flag `app.bypass_rls` = 'true'.
This is required for Celery background tasks like webhooks which process
data across tenants without a specific user context.
"""

from alembic import op

revision = "p9q0r1s2t3u6"
down_revision = "p9q0r1s2t3u5"
branch_labels = None
depends_on = None

TENANT_TABLES_USER_ID = [
    "whatsapp_contacts",
    "whatsapp_messages",
    "whatsapp_auto_replies",
    "whatsapp_business_profiles",
    "whatsapp_templates",
    "whatsapp_broadcasts",
    "whatsapp_quick_replies",
    "connections",
    "workflows",
    "workflow_executions",
    "mpesa_payments",
    "stk_payment_attempts",
    "stk_order_mappings",
    "mpesa_agent_configs",
    "invoices",
    "knowledge_bases",
    "conversations",
    "notifications",
    "processed_webhook_messages",
    "tool_audit_log",
    "tool_proposals",
    "user_settings",
    "user_preferences",
    "webauthn_credentials",
    "subscriptions",
    "usage_logs",
    "usage_records",
    "payments",
    "workflow_downloads",
    "workflow_reviews",
    "workflow_favorites",
    "activity_feed",
    "fraud_signals",
    "developer_apps",
    "authorization_codes",
    "organization_members",
]

SPECIAL_TENANT_TABLES = {
    "messaging_conversations": "owner_user_id",
}

def upgrade() -> None:
    # Set default bypass to false
    op.execute("ALTER DATABASE arrotech_hub SET app.bypass_rls = 'false';")

    # Update user_id tables
    for table in TENANT_TABLES_USER_ID:
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";')
        op.execute(f"""
            CREATE POLICY tenant_isolation ON "{table}"
                USING (
                    current_setting('app.bypass_rls', true) = 'true'
                    OR user_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
                )
                WITH CHECK (
                    current_setting('app.bypass_rls', true) = 'true'
                    OR user_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
                );
        """)

    # Update special tables
    for table, col in SPECIAL_TENANT_TABLES.items():
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";')
        op.execute(f"""
            CREATE POLICY tenant_isolation ON "{table}"
                USING (
                    current_setting('app.bypass_rls', true) = 'true'
                    OR {col} = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
                )
                WITH CHECK (
                    current_setting('app.bypass_rls', true) = 'true'
                    OR {col} = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
                );
        """)

def downgrade() -> None:
    # Downgrade drops the bypass and restores standard isolation
    for table in TENANT_TABLES_USER_ID:
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";')
        op.execute(f"""
            CREATE POLICY tenant_isolation ON "{table}"
                USING (user_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
                WITH CHECK (user_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
        """)

    for table, col in SPECIAL_TENANT_TABLES.items():
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";')
        op.execute(f"""
            CREATE POLICY tenant_isolation ON "{table}"
                USING ({col} = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
                WITH CHECK ({col} = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
        """)
