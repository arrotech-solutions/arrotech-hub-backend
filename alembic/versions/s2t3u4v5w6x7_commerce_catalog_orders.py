"""commerce catalog orders and reservations

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-11-12 19:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "s2t3u4v5w6x7"
down_revision = "r1s2t3u4v5w6"
branch_labels = None
depends_on = None

COMMERCE_TENANT_TABLES = (
    "catalog_products",
    "commerce_orders",
    "commerce_reservations",
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
        "catalog_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("cost_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("brand", sa.String(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=True),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("condition", sa.String(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=False),
        sa.Column("availability", sa.String(), server_default="in_stock", nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_catalog_products_user_id", "catalog_products", ["user_id"])
    op.create_index("ix_catalog_products_user_name", "catalog_products", ["user_id", "name"])

    op.create_table(
        "commerce_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("external_order_id", sa.String(), nullable=False),
        sa.Column("customer_name", sa.String(), nullable=False),
        sa.Column("customer_phone", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payment_status", sa.String(), nullable=False),
        sa.Column("payment_method", sa.String(), nullable=True),
        sa.Column("currency", sa.String(length=8), server_default="KES", nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_items", sa.JSON(), nullable=False),
        sa.Column("delivery_method", sa.String(), nullable=False),
        sa.Column("delivery_address", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("mpesa_receipt", sa.String(), nullable=True),
        sa.Column("raw_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "user_id",
            "external_order_id",
            name="uq_commerce_orders_user_external_order_id",
        ),
    )
    op.create_index("ix_commerce_orders_user_id", "commerce_orders", ["user_id"])

    op.create_table(
        "commerce_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("external_reservation_id", sa.String(), nullable=False),
        sa.Column("customer_name", sa.String(), nullable=False),
        sa.Column("customer_phone", sa.String(), nullable=False),
        sa.Column("reservation_date", sa.String(), nullable=False),
        sa.Column("reservation_time", sa.String(), nullable=False),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), server_default="confirmed", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("raw_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "user_id",
            "external_reservation_id",
            name="uq_commerce_reservations_user_external_reservation_id",
        ),
    )
    op.create_index("ix_commerce_reservations_user_id", "commerce_reservations", ["user_id"])

    for table in COMMERCE_TENANT_TABLES:
        _enable_tenant_rls(table)


def downgrade() -> None:
    for table in reversed(COMMERCE_TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";')
    op.drop_index("ix_commerce_reservations_user_id", table_name="commerce_reservations")
    op.drop_table("commerce_reservations")
    op.drop_index("ix_commerce_orders_user_id", table_name="commerce_orders")
    op.drop_table("commerce_orders")
    op.drop_index("ix_catalog_products_user_name", table_name="catalog_products")
    op.drop_index("ix_catalog_products_user_id", table_name="catalog_products")
    op.drop_table("catalog_products")
