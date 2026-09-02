"""enable row-level security on tenant-scoped tables

Revision ID: p9q0r1s2t3u4
Revises: n8i9j0k1l2m3
Create Date: 2026-08-31 16:48:00.000000

Enables PostgreSQL Row-Level Security (RLS) on all tenant-scoped tables.
Each policy filters rows using:
    user_id = current_setting('app.current_tenant_id')::uuid

The application must SET LOCAL app.current_tenant_id = '<user-uuid>' on every
database session before issuing queries.  RLS is only enforced when the
connection uses a non-owner role (e.g. 'app_user'); the table owner (used by
Alembic) silently bypasses policies unless FORCE ROW LEVEL SECURITY is set.
"""

from alembic import op

revision = "p9q0r1s2t3u4"
down_revision = "n8i9j0k1l2m3"
branch_labels = None
depends_on = None

# ── Tables that use `user_id` as the tenant discriminator ──────────────────
# Tier 1: Core business-critical tables
# Tier 2: User-scoped settings/preferences
TENANT_TABLES_USER_ID = [
    # Tier 1 — high-value, privacy-sensitive
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
    # Tier 2 — user-scoped, lower urgency
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

# ── Tables that use a different tenant column ──────────────────────────────
SPECIAL_TENANT_TABLES = {
    "messaging_conversations": "owner_user_id",
}

# ── Tables that need a user_id index added (currently missing) ─────────────
TABLES_NEEDING_INDEX = [
    "whatsapp_templates",
    "whatsapp_broadcasts",
    "connections",
    "workflows",
    "workflow_executions",
    "conversations",
]


def upgrade() -> None:
    # ── Step 1: Add missing indexes for RLS performance ───────────────────
    for table in TABLES_NEEDING_INDEX:
        op.create_index(
            f"ix_{table}_user_id",
            table,
            ["user_id"],
            if_not_exists=True,
        )

    # ── Step 2: Enable RLS + create policies on user_id tables ────────────
    for table in TENANT_TABLES_USER_ID:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY;')
        op.execute(f"""
            CREATE POLICY tenant_isolation ON "{table}"
                USING (user_id = current_setting('app.current_tenant_id')::uuid)
                WITH CHECK (user_id = current_setting('app.current_tenant_id')::uuid);
        """)

    # ── Step 3: Enable RLS on tables with different tenant columns ────────
    for table, col in SPECIAL_TENANT_TABLES.items():
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY;')
        op.execute(f"""
            CREATE POLICY tenant_isolation ON "{table}"
                USING ({col} = current_setting('app.current_tenant_id')::uuid)
                WITH CHECK ({col} = current_setting('app.current_tenant_id')::uuid);
        """)


def downgrade() -> None:
    # ── Remove policies and disable RLS ───────────────────────────────────
    all_tables = TENANT_TABLES_USER_ID + list(SPECIAL_TENANT_TABLES.keys())
    for table in all_tables:
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY;')

    # ── Remove added indexes ──────────────────────────────────────────────
    for table in TABLES_NEEDING_INDEX:
        op.drop_index(f"ix_{table}_user_id", table_name=table)
