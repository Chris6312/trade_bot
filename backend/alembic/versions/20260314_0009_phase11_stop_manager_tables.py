"""phase11 stop manager tables

Revision ID: 20260314_0009
Revises: 20260314_0008
Create Date: 2026-03-14 10:15:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260314_0009"
down_revision: str | None = "20260314_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stop_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("execution_order_id", sa.Integer(), nullable=False),
        sa.Column("execution_fill_id", sa.Integer(), nullable=True),
        sa.Column("risk_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("strategy_name", sa.String(length=100), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False, server_default="long"),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("stop_style", sa.String(length=20), nullable=False, server_default="fixed"),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("initial_stop_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("current_stop_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("current_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("highest_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("trailing_activation_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("trailing_offset_pct", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("trailing_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("trailing_activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("step_trigger_pct", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("step_increment_pct", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("step_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_step_trigger_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("protected_quantity", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("broker_stop_order_id", sa.String(length=120), nullable=True),
        sa.Column("last_fill_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("update_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_fill_id"], ["execution_fills.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["execution_order_id"], ["execution_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["risk_snapshot_id"], ["risk_snapshots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_order_id", name="uq_stop_states_execution_order_id"),
    )
    op.create_index(op.f("ix_stop_states_asset_class"), "stop_states", ["asset_class"], unique=False)
    op.create_index(op.f("ix_stop_states_broker_stop_order_id"), "stop_states", ["broker_stop_order_id"], unique=False)
    op.create_index(op.f("ix_stop_states_execution_fill_id"), "stop_states", ["execution_fill_id"], unique=False)
    op.create_index(op.f("ix_stop_states_execution_order_id"), "stop_states", ["execution_order_id"], unique=False)
    op.create_index(op.f("ix_stop_states_mode"), "stop_states", ["mode"], unique=False)
    op.create_index(op.f("ix_stop_states_risk_snapshot_id"), "stop_states", ["risk_snapshot_id"], unique=False)
    op.create_index(op.f("ix_stop_states_status"), "stop_states", ["status"], unique=False)
    op.create_index(op.f("ix_stop_states_strategy_name"), "stop_states", ["strategy_name"], unique=False)
    op.create_index(op.f("ix_stop_states_symbol"), "stop_states", ["symbol"], unique=False)
    op.create_index(op.f("ix_stop_states_timeframe"), "stop_states", ["timeframe"], unique=False)
    op.create_index(op.f("ix_stop_states_venue"), "stop_states", ["venue"], unique=False)

    op.create_table(
        "stop_update_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stop_state_id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("previous_stop_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("new_stop_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("reference_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("high_watermark", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("step_level", sa.Integer(), nullable=True),
        sa.Column("broker_stop_order_id", sa.String(length=120), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["stop_state_id"], ["stop_states.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_stop_update_history_asset_class"), "stop_update_history", ["asset_class"], unique=False)
    op.create_index(op.f("ix_stop_update_history_broker_stop_order_id"), "stop_update_history", ["broker_stop_order_id"], unique=False)
    op.create_index(op.f("ix_stop_update_history_event_timestamp"), "stop_update_history", ["event_timestamp"], unique=False)
    op.create_index(op.f("ix_stop_update_history_event_type"), "stop_update_history", ["event_type"], unique=False)
    op.create_index(op.f("ix_stop_update_history_mode"), "stop_update_history", ["mode"], unique=False)
    op.create_index(op.f("ix_stop_update_history_status"), "stop_update_history", ["status"], unique=False)
    op.create_index(op.f("ix_stop_update_history_stop_state_id"), "stop_update_history", ["stop_state_id"], unique=False)
    op.create_index(op.f("ix_stop_update_history_symbol"), "stop_update_history", ["symbol"], unique=False)
    op.create_index(op.f("ix_stop_update_history_timeframe"), "stop_update_history", ["timeframe"], unique=False)
    op.create_index(op.f("ix_stop_update_history_venue"), "stop_update_history", ["venue"], unique=False)

    op.create_table(
        "stop_sync_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fill_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_status", sa.String(length=30), nullable=False, server_default="idle"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_class", "timeframe", name="uq_stop_sync_states_asset_timeframe"),
    )
    op.create_index(op.f("ix_stop_sync_states_asset_class"), "stop_sync_states", ["asset_class"], unique=False)
    op.create_index(op.f("ix_stop_sync_states_mode"), "stop_sync_states", ["mode"], unique=False)
    op.create_index(op.f("ix_stop_sync_states_timeframe"), "stop_sync_states", ["timeframe"], unique=False)
    op.create_index(op.f("ix_stop_sync_states_venue"), "stop_sync_states", ["venue"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_stop_sync_states_venue"), table_name="stop_sync_states")
    op.drop_index(op.f("ix_stop_sync_states_timeframe"), table_name="stop_sync_states")
    op.drop_index(op.f("ix_stop_sync_states_mode"), table_name="stop_sync_states")
    op.drop_index(op.f("ix_stop_sync_states_asset_class"), table_name="stop_sync_states")
    op.drop_table("stop_sync_states")

    op.drop_index(op.f("ix_stop_update_history_venue"), table_name="stop_update_history")
    op.drop_index(op.f("ix_stop_update_history_timeframe"), table_name="stop_update_history")
    op.drop_index(op.f("ix_stop_update_history_symbol"), table_name="stop_update_history")
    op.drop_index(op.f("ix_stop_update_history_stop_state_id"), table_name="stop_update_history")
    op.drop_index(op.f("ix_stop_update_history_status"), table_name="stop_update_history")
    op.drop_index(op.f("ix_stop_update_history_mode"), table_name="stop_update_history")
    op.drop_index(op.f("ix_stop_update_history_event_type"), table_name="stop_update_history")
    op.drop_index(op.f("ix_stop_update_history_event_timestamp"), table_name="stop_update_history")
    op.drop_index(op.f("ix_stop_update_history_broker_stop_order_id"), table_name="stop_update_history")
    op.drop_index(op.f("ix_stop_update_history_asset_class"), table_name="stop_update_history")
    op.drop_table("stop_update_history")

    op.drop_index(op.f("ix_stop_states_venue"), table_name="stop_states")
    op.drop_index(op.f("ix_stop_states_timeframe"), table_name="stop_states")
    op.drop_index(op.f("ix_stop_states_symbol"), table_name="stop_states")
    op.drop_index(op.f("ix_stop_states_strategy_name"), table_name="stop_states")
    op.drop_index(op.f("ix_stop_states_status"), table_name="stop_states")
    op.drop_index(op.f("ix_stop_states_risk_snapshot_id"), table_name="stop_states")
    op.drop_index(op.f("ix_stop_states_mode"), table_name="stop_states")
    op.drop_index(op.f("ix_stop_states_execution_order_id"), table_name="stop_states")
    op.drop_index(op.f("ix_stop_states_execution_fill_id"), table_name="stop_states")
    op.drop_index(op.f("ix_stop_states_broker_stop_order_id"), table_name="stop_states")
    op.drop_index(op.f("ix_stop_states_asset_class"), table_name="stop_states")
    op.drop_table("stop_states")
