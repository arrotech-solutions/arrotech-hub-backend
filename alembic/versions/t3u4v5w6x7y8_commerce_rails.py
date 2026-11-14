"""commerce rails policy returns complaints refunds

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-11-14 14:48:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "t3u4v5w6x7y8"
down_revision = "s2t3u4v5w6x7"
branch_labels = None
depends_on = None

COMMERCE_TENANT_TABLES = (
    "commerce_policies",
    "commerce_returns",
    "commerce_complaints",
)


def _enable_tenant_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;')
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


def upgrade() -> None:
    op.create_table(
        "commerce_policies",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("config", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "commerce_returns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("external_return_id", sa.String(), nullable=False),
        sa.Column("order_external_id", sa.String(), nullable=False),
        sa.Column("customer_phone", sa.String(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="KES", nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("auto_approved", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("raw_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "user_id",
            "external_return_id",
            name="uq_commerce_returns_user_external_return_id",
        ),
    )
    op.create_index("ix_commerce_returns_user_id", "commerce_returns", ["user_id"])
    op.create_index("ix_commerce_returns_user_status", "commerce_returns", ["user_id", "status"])

    op.create_table(
        "commerce_complaints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("external_complaint_id", sa.String(), nullable=False),
        sa.Column("order_external_id", sa.String(), nullable=True),
        sa.Column("customer_phone", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("raw_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "user_id",
            "external_complaint_id",
            name="uq_commerce_complaints_user_external_complaint_id",
        ),
    )
    op.create_index("ix_commerce_complaints_user_id", "commerce_complaints", ["user_id"])
    op.create_index("ix_commerce_complaints_user_status", "commerce_complaints", ["user_id", "status"])

    op.create_table(
        "commerce_refund_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "return_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("commerce_returns.id"),
            nullable=False,
        ),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("mpesa_receipt", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_commerce_refund_attempts_return_id", "commerce_refund_attempts", ["return_id"])

    for table in COMMERCE_TENANT_TABLES:
        _enable_tenant_rls(table)


def downgrade() -> None:
    for table in reversed(COMMERCE_TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";')
    op.drop_index("ix_commerce_refund_attempts_return_id", table_name="commerce_refund_attempts")
    op.drop_table("commerce_refund_attempts")
    op.drop_index("ix_commerce_complaints_user_status", table_name="commerce_complaints")
    op.drop_index("ix_commerce_complaints_user_id", table_name="commerce_complaints")
    op.drop_table("commerce_complaints")
    op.drop_index("ix_commerce_returns_user_status", table_name="commerce_returns")
    op.drop_index("ix_commerce_returns_user_id", table_name="commerce_returns")
    op.drop_table("commerce_returns")
    op.drop_table("commerce_policies")