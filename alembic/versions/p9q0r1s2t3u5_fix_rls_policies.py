"""fix rls policies safe current setting

Revision ID: p9q0r1s2t3u5
Revises: p9q0r1s2t3u4
Create Date: 2026-09-02 12:00:00.000000

"""

from alembic import op

revision = "p9q0r1s2t3u5"
down_revision = "p9q0r1s2t3u4"
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
    # Set default database setting so it never crashes
    op.execute("ALTER DATABASE arrotech_hub SET app.current_tenant_id = '00000000-0000-0000-0000-000000000000';")
    
    # Fix user_id tables
    for table in TENANT_TABLES_USER_ID:
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY;')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";')
        op.execute(f"""
            CREATE POLICY tenant_isolation ON "{table}"
                USING (user_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
                WITH CHECK (user_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
        """)

    # Fix messaging_conversations
    for table, col in SPECIAL_TENANT_TABLES.items():
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY;')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";')
        op.execute(f"""
            CREATE POLICY tenant_isolation ON "{table}"
                USING ({col} = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
                WITH CHECK ({col} = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
        """)

def downgrade() -> None:
    pass
