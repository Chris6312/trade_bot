"""phase4 candle worker tables

Revision ID: 20260314_0002
Revises: 20260314_0001
Create Date: 2026-03-14 00:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260314_0002"
down_revision: str | None = "20260314_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("high", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("low", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("close", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("volume", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column("vwap", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_class",
            "symbol",
            "timeframe",
            "timestamp",
            name="uq_candles_asset_symbol_timeframe_timestamp",
        ),
    )
    op.create_index(op.f("ix_candles_asset_class"), "candles", ["asset_class"], unique=False)
    op.create_index(op.f("ix_candles_symbol"), "candles", ["symbol"], unique=False)
    op.create_index(op.f("ix_candles_timeframe"), "candles", ["timeframe"], unique=False)
    op.create_index(op.f("ix_candles_timestamp"), "candles", ["timestamp"], unique=False)
    op.create_index(op.f("ix_candles_venue"), "candles", ["venue"], unique=False)

    op.create_table(
        "candle_sync_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_candle_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_class",
            "symbol",
            "timeframe",
            name="uq_candle_sync_states_asset_symbol_timeframe",
        ),
    )
    op.create_index(op.f("ix_candle_sync_states_asset_class"), "candle_sync_states", ["asset_class"], unique=False)
    op.create_index(op.f("ix_candle_sync_states_symbol"), "candle_sync_states", ["symbol"], unique=False)
    op.create_index(op.f("ix_candle_sync_states_timeframe"), "candle_sync_states", ["timeframe"], unique=False)
    op.create_index(op.f("ix_candle_sync_states_venue"), "candle_sync_states", ["venue"], unique=False)

    op.create_table(
        "candle_freshness",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_candle_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fresh_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_class",
            "symbol",
            "timeframe",
            name="uq_candle_freshness_asset_symbol_timeframe",
        ),
    )
    op.create_index(op.f("ix_candle_freshness_asset_class"), "candle_freshness", ["asset_class"], unique=False)
    op.create_index(op.f("ix_candle_freshness_symbol"), "candle_freshness", ["symbol"], unique=False)
    op.create_index(op.f("ix_candle_freshness_timeframe"), "candle_freshness", ["timeframe"], unique=False)
    op.create_index(op.f("ix_candle_freshness_venue"), "candle_freshness", ["venue"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_candle_freshness_venue"), table_name="candle_freshness")
    op.drop_index(op.f("ix_candle_freshness_timeframe"), table_name="candle_freshness")
    op.drop_index(op.f("ix_candle_freshness_symbol"), table_name="candle_freshness")
    op.drop_index(op.f("ix_candle_freshness_asset_class"), table_name="candle_freshness")
    op.drop_table("candle_freshness")

    op.drop_index(op.f("ix_candle_sync_states_venue"), table_name="candle_sync_states")
    op.drop_index(op.f("ix_candle_sync_states_timeframe"), table_name="candle_sync_states")
    op.drop_index(op.f("ix_candle_sync_states_symbol"), table_name="candle_sync_states")
    op.drop_index(op.f("ix_candle_sync_states_asset_class"), table_name="candle_sync_states")
    op.drop_table("candle_sync_states")

    op.drop_index(op.f("ix_candles_venue"), table_name="candles")
    op.drop_index(op.f("ix_candles_timestamp"), table_name="candles")
    op.drop_index(op.f("ix_candles_timeframe"), table_name="candles")
    op.drop_index(op.f("ix_candles_symbol"), table_name="candles")
    op.drop_index(op.f("ix_candles_asset_class"), table_name="candles")
    op.drop_table("candles")
