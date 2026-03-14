"""phase12 position sync reconciliation pnl tables

Revision ID: 20260314_0010
Revises: 20260314_0009
Create Date: 2026-03-14 10:45:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260314_0010"
down_revision: str | None = "20260314_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "position_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("side", sa.String(length=20), nullable=False, server_default="long"),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reconciliation_status", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=28, scale=8), nullable=False, server_default="0"),
        sa.Column("broker_quantity", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("internal_quantity", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("quantity_delta", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("average_entry_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("broker_average_entry_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("internal_average_entry_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("cost_basis", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("market_value", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("current_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(precision=20, scale=8), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.Numeric(precision=20, scale=8), nullable=False, server_default="0"),
        sa.Column("last_fill_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mismatch_reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_class",
            "venue",
            "mode",
            "symbol",
            "timeframe",
            name="uq_position_states_asset_venue_mode_symbol_timeframe",
        ),
    )
    op.create_index(op.f("ix_position_states_asset_class"), "position_states", ["asset_class"], unique=False)
    op.create_index(op.f("ix_position_states_mode"), "position_states", ["mode"], unique=False)
    op.create_index(op.f("ix_position_states_reconciliation_status"), "position_states", ["reconciliation_status"], unique=False)
    op.create_index(op.f("ix_position_states_status"), "position_states", ["status"], unique=False)
    op.create_index(op.f("ix_position_states_symbol"), "position_states", ["symbol"], unique=False)
    op.create_index(op.f("ix_position_states_synced_at"), "position_states", ["synced_at"], unique=False)
    op.create_index(op.f("ix_position_states_timeframe"), "position_states", ["timeframe"], unique=False)
    op.create_index(op.f("ix_position_states_venue"), "position_states", ["venue"], unique=False)

    op.create_table(
        "open_order_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("execution_order_id", sa.Integer(), nullable=True),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("unique_order_key", sa.String(length=160), nullable=False),
        sa.Column("client_order_id", sa.String(length=120), nullable=True),
        sa.Column("broker_order_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("order_type", sa.String(length=20), nullable=False),
        sa.Column("side", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("notional_value", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("limit_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("stop_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reconciliation_status", sa.String(length=30), nullable=False, server_default="matched"),
        sa.Column("mismatch_reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_order_id"], ["execution_orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("unique_order_key", name="uq_open_order_states_unique_order_key"),
    )
    op.create_index(op.f("ix_open_order_states_asset_class"), "open_order_states", ["asset_class"], unique=False)
    op.create_index(op.f("ix_open_order_states_broker_order_id"), "open_order_states", ["broker_order_id"], unique=False)
    op.create_index(op.f("ix_open_order_states_client_order_id"), "open_order_states", ["client_order_id"], unique=False)
    op.create_index(op.f("ix_open_order_states_execution_order_id"), "open_order_states", ["execution_order_id"], unique=False)
    op.create_index(op.f("ix_open_order_states_mode"), "open_order_states", ["mode"], unique=False)
    op.create_index(op.f("ix_open_order_states_reconciliation_status"), "open_order_states", ["reconciliation_status"], unique=False)
    op.create_index(op.f("ix_open_order_states_status"), "open_order_states", ["status"], unique=False)
    op.create_index(op.f("ix_open_order_states_symbol"), "open_order_states", ["symbol"], unique=False)
    op.create_index(op.f("ix_open_order_states_synced_at"), "open_order_states", ["synced_at"], unique=False)
    op.create_index(op.f("ix_open_order_states_timeframe"), "open_order_states", ["timeframe"], unique=False)
    op.create_index(op.f("ix_open_order_states_unique_order_key"), "open_order_states", ["unique_order_key"], unique=False)
    op.create_index(op.f("ix_open_order_states_venue"), "open_order_states", ["venue"], unique=False)

    op.create_table(
        "reconciliation_mismatches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("mismatch_type", sa.String(length=40), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="warning"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("internal_value", sa.String(length=120), nullable=True),
        sa.Column("broker_value", sa.String(length=120), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reconciliation_mismatches_asset_class"), "reconciliation_mismatches", ["asset_class"], unique=False)
    op.create_index(op.f("ix_reconciliation_mismatches_detected_at"), "reconciliation_mismatches", ["detected_at"], unique=False)
    op.create_index(op.f("ix_reconciliation_mismatches_mismatch_type"), "reconciliation_mismatches", ["mismatch_type"], unique=False)
    op.create_index(op.f("ix_reconciliation_mismatches_mode"), "reconciliation_mismatches", ["mode"], unique=False)
    op.create_index(op.f("ix_reconciliation_mismatches_severity"), "reconciliation_mismatches", ["severity"], unique=False)
    op.create_index(op.f("ix_reconciliation_mismatches_status"), "reconciliation_mismatches", ["status"], unique=False)
    op.create_index(op.f("ix_reconciliation_mismatches_symbol"), "reconciliation_mismatches", ["symbol"], unique=False)
    op.create_index(op.f("ix_reconciliation_mismatches_timeframe"), "reconciliation_mismatches", ["timeframe"], unique=False)
    op.create_index(op.f("ix_reconciliation_mismatches_venue"), "reconciliation_mismatches", ["venue"], unique=False)

    op.create_table(
        "position_sync_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fill_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("open_order_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mismatch_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(precision=20, scale=8), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.Numeric(precision=20, scale=8), nullable=False, server_default="0"),
        sa.Column("last_status", sa.String(length=30), nullable=False, server_default="idle"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_class", "timeframe", name="uq_position_sync_states_asset_timeframe"),
    )
    op.create_index(op.f("ix_position_sync_states_asset_class"), "position_sync_states", ["asset_class"], unique=False)
    op.create_index(op.f("ix_position_sync_states_mode"), "position_sync_states", ["mode"], unique=False)
    op.create_index(op.f("ix_position_sync_states_timeframe"), "position_sync_states", ["timeframe"], unique=False)
    op.create_index(op.f("ix_position_sync_states_venue"), "position_sync_states", ["venue"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_position_sync_states_venue"), table_name="position_sync_states")
    op.drop_index(op.f("ix_position_sync_states_timeframe"), table_name="position_sync_states")
    op.drop_index(op.f("ix_position_sync_states_mode"), table_name="position_sync_states")
    op.drop_index(op.f("ix_position_sync_states_asset_class"), table_name="position_sync_states")
    op.drop_table("position_sync_states")

    op.drop_index(op.f("ix_reconciliation_mismatches_venue"), table_name="reconciliation_mismatches")
    op.drop_index(op.f("ix_reconciliation_mismatches_timeframe"), table_name="reconciliation_mismatches")
    op.drop_index(op.f("ix_reconciliation_mismatches_symbol"), table_name="reconciliation_mismatches")
    op.drop_index(op.f("ix_reconciliation_mismatches_status"), table_name="reconciliation_mismatches")
    op.drop_index(op.f("ix_reconciliation_mismatches_severity"), table_name="reconciliation_mismatches")
    op.drop_index(op.f("ix_reconciliation_mismatches_mode"), table_name="reconciliation_mismatches")
    op.drop_index(op.f("ix_reconciliation_mismatches_mismatch_type"), table_name="reconciliation_mismatches")
    op.drop_index(op.f("ix_reconciliation_mismatches_detected_at"), table_name="reconciliation_mismatches")
    op.drop_index(op.f("ix_reconciliation_mismatches_asset_class"), table_name="reconciliation_mismatches")
    op.drop_table("reconciliation_mismatches")

    op.drop_index(op.f("ix_open_order_states_venue"), table_name="open_order_states")
    op.drop_index(op.f("ix_open_order_states_unique_order_key"), table_name="open_order_states")
    op.drop_index(op.f("ix_open_order_states_timeframe"), table_name="open_order_states")
    op.drop_index(op.f("ix_open_order_states_synced_at"), table_name="open_order_states")
    op.drop_index(op.f("ix_open_order_states_symbol"), table_name="open_order_states")
    op.drop_index(op.f("ix_open_order_states_status"), table_name="open_order_states")
    op.drop_index(op.f("ix_open_order_states_reconciliation_status"), table_name="open_order_states")
    op.drop_index(op.f("ix_open_order_states_mode"), table_name="open_order_states")
    op.drop_index(op.f("ix_open_order_states_execution_order_id"), table_name="open_order_states")
    op.drop_index(op.f("ix_open_order_states_client_order_id"), table_name="open_order_states")
    op.drop_index(op.f("ix_open_order_states_broker_order_id"), table_name="open_order_states")
    op.drop_index(op.f("ix_open_order_states_asset_class"), table_name="open_order_states")
    op.drop_table("open_order_states")

    op.drop_index(op.f("ix_position_states_venue"), table_name="position_states")
    op.drop_index(op.f("ix_position_states_timeframe"), table_name="position_states")
    op.drop_index(op.f("ix_position_states_synced_at"), table_name="position_states")
    op.drop_index(op.f("ix_position_states_symbol"), table_name="position_states")
    op.drop_index(op.f("ix_position_states_status"), table_name="position_states")
    op.drop_index(op.f("ix_position_states_reconciliation_status"), table_name="position_states")
    op.drop_index(op.f("ix_position_states_mode"), table_name="position_states")
    op.drop_index(op.f("ix_position_states_asset_class"), table_name="position_states")
    op.drop_table("position_states")
