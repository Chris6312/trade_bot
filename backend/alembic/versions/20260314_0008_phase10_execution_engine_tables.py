
"""phase10 execution engine tables

Revision ID: 20260314_0008
Revises: 20260314_0007
Create Date: 2026-03-14 09:25:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260314_0008"
down_revision: str | None = "20260314_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("risk_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("strategy_name", sa.String(length=100), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False, server_default="long"),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("candidate_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("routed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_order_id", sa.String(length=120), nullable=False),
        sa.Column("broker_order_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("order_type", sa.String(length=20), nullable=False, server_default="market"),
        sa.Column("side", sa.String(length=20), nullable=False, server_default="buy"),
        sa.Column("quantity", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("notional_value", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("limit_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("stop_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("fill_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["risk_snapshot_id"], ["risk_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_order_id", name="uq_execution_orders_client_order_id"),
        sa.UniqueConstraint("risk_snapshot_id", name="uq_execution_orders_risk_snapshot_id"),
    )
    op.create_index(op.f("ix_execution_orders_asset_class"), "execution_orders", ["asset_class"], unique=False)
    op.create_index(op.f("ix_execution_orders_broker_order_id"), "execution_orders", ["broker_order_id"], unique=False)
    op.create_index(op.f("ix_execution_orders_candidate_timestamp"), "execution_orders", ["candidate_timestamp"], unique=False)
    op.create_index(op.f("ix_execution_orders_client_order_id"), "execution_orders", ["client_order_id"], unique=False)
    op.create_index(op.f("ix_execution_orders_mode"), "execution_orders", ["mode"], unique=False)
    op.create_index(op.f("ix_execution_orders_risk_snapshot_id"), "execution_orders", ["risk_snapshot_id"], unique=False)
    op.create_index(op.f("ix_execution_orders_routed_at"), "execution_orders", ["routed_at"], unique=False)
    op.create_index(op.f("ix_execution_orders_status"), "execution_orders", ["status"], unique=False)
    op.create_index(op.f("ix_execution_orders_strategy_name"), "execution_orders", ["strategy_name"], unique=False)
    op.create_index(op.f("ix_execution_orders_symbol"), "execution_orders", ["symbol"], unique=False)
    op.create_index(op.f("ix_execution_orders_timeframe"), "execution_orders", ["timeframe"], unique=False)
    op.create_index(op.f("ix_execution_orders_venue"), "execution_orders", ["venue"], unique=False)

    op.create_table(
        "execution_fills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("execution_order_id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("fill_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column("fill_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("notional_value", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column("fee_amount", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("venue_fill_id", sa.String(length=120), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_order_id"], ["execution_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "execution_order_id",
            "fill_timestamp",
            "quantity",
            name="uq_execution_fills_order_timestamp_quantity",
        ),
    )
    op.create_index(op.f("ix_execution_fills_asset_class"), "execution_fills", ["asset_class"], unique=False)
    op.create_index(op.f("ix_execution_fills_execution_order_id"), "execution_fills", ["execution_order_id"], unique=False)
    op.create_index(op.f("ix_execution_fills_fill_timestamp"), "execution_fills", ["fill_timestamp"], unique=False)
    op.create_index(op.f("ix_execution_fills_mode"), "execution_fills", ["mode"], unique=False)
    op.create_index(op.f("ix_execution_fills_status"), "execution_fills", ["status"], unique=False)
    op.create_index(op.f("ix_execution_fills_symbol"), "execution_fills", ["symbol"], unique=False)
    op.create_index(op.f("ix_execution_fills_timeframe"), "execution_fills", ["timeframe"], unique=False)
    op.create_index(op.f("ix_execution_fills_venue"), "execution_fills", ["venue"], unique=False)
    op.create_index(op.f("ix_execution_fills_venue_fill_id"), "execution_fills", ["venue_fill_id"], unique=False)

    op.create_table(
        "execution_sync_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("last_routed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_candidate_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("routed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fill_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_status", sa.String(length=30), nullable=False, server_default="idle"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_class", "timeframe", name="uq_execution_sync_states_asset_timeframe"),
    )
    op.create_index(op.f("ix_execution_sync_states_asset_class"), "execution_sync_states", ["asset_class"], unique=False)
    op.create_index(op.f("ix_execution_sync_states_mode"), "execution_sync_states", ["mode"], unique=False)
    op.create_index(op.f("ix_execution_sync_states_timeframe"), "execution_sync_states", ["timeframe"], unique=False)
    op.create_index(op.f("ix_execution_sync_states_venue"), "execution_sync_states", ["venue"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_execution_sync_states_venue"), table_name="execution_sync_states")
    op.drop_index(op.f("ix_execution_sync_states_timeframe"), table_name="execution_sync_states")
    op.drop_index(op.f("ix_execution_sync_states_mode"), table_name="execution_sync_states")
    op.drop_index(op.f("ix_execution_sync_states_asset_class"), table_name="execution_sync_states")
    op.drop_table("execution_sync_states")

    op.drop_index(op.f("ix_execution_fills_venue_fill_id"), table_name="execution_fills")
    op.drop_index(op.f("ix_execution_fills_venue"), table_name="execution_fills")
    op.drop_index(op.f("ix_execution_fills_timeframe"), table_name="execution_fills")
    op.drop_index(op.f("ix_execution_fills_symbol"), table_name="execution_fills")
    op.drop_index(op.f("ix_execution_fills_status"), table_name="execution_fills")
    op.drop_index(op.f("ix_execution_fills_mode"), table_name="execution_fills")
    op.drop_index(op.f("ix_execution_fills_fill_timestamp"), table_name="execution_fills")
    op.drop_index(op.f("ix_execution_fills_execution_order_id"), table_name="execution_fills")
    op.drop_index(op.f("ix_execution_fills_asset_class"), table_name="execution_fills")
    op.drop_table("execution_fills")

    op.drop_index(op.f("ix_execution_orders_venue"), table_name="execution_orders")
    op.drop_index(op.f("ix_execution_orders_timeframe"), table_name="execution_orders")
    op.drop_index(op.f("ix_execution_orders_symbol"), table_name="execution_orders")
    op.drop_index(op.f("ix_execution_orders_strategy_name"), table_name="execution_orders")
    op.drop_index(op.f("ix_execution_orders_status"), table_name="execution_orders")
    op.drop_index(op.f("ix_execution_orders_routed_at"), table_name="execution_orders")
    op.drop_index(op.f("ix_execution_orders_risk_snapshot_id"), table_name="execution_orders")
    op.drop_index(op.f("ix_execution_orders_mode"), table_name="execution_orders")
    op.drop_index(op.f("ix_execution_orders_client_order_id"), table_name="execution_orders")
    op.drop_index(op.f("ix_execution_orders_candidate_timestamp"), table_name="execution_orders")
    op.drop_index(op.f("ix_execution_orders_broker_order_id"), table_name="execution_orders")
    op.drop_index(op.f("ix_execution_orders_asset_class"), table_name="execution_orders")
    op.drop_table("execution_orders")
