"""phase6 feature engine tables

Revision ID: 20260314_0004
Revises: 20260314_0003
Create Date: 2026-03-14 02:10:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260314_0004"
down_revision: str | None = "20260314_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("candle_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("volume", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column("price_return_1", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("sma_20", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("ema_20", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("momentum_20", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("volume_sma_20", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("relative_volume_20", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("dollar_volume", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("dollar_volume_sma_20", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("atr_14", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("realized_volatility_20", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("trend_slope_20", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_class",
            "symbol",
            "timeframe",
            "candle_timestamp",
            name="uq_feature_snapshots_asset_symbol_timeframe_timestamp",
        ),
    )
    op.create_index(op.f("ix_feature_snapshots_asset_class"), "feature_snapshots", ["asset_class"], unique=False)
    op.create_index(op.f("ix_feature_snapshots_candle_timestamp"), "feature_snapshots", ["candle_timestamp"], unique=False)
    op.create_index(op.f("ix_feature_snapshots_computed_at"), "feature_snapshots", ["computed_at"], unique=False)
    op.create_index(op.f("ix_feature_snapshots_symbol"), "feature_snapshots", ["symbol"], unique=False)
    op.create_index(op.f("ix_feature_snapshots_timeframe"), "feature_snapshots", ["timeframe"], unique=False)
    op.create_index(op.f("ix_feature_snapshots_venue"), "feature_snapshots", ["venue"], unique=False)

    op.create_table(
        "feature_sync_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("last_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_candle_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feature_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_class",
            "symbol",
            "timeframe",
            name="uq_feature_sync_states_asset_symbol_timeframe",
        ),
    )
    op.create_index(op.f("ix_feature_sync_states_asset_class"), "feature_sync_states", ["asset_class"], unique=False)
    op.create_index(op.f("ix_feature_sync_states_symbol"), "feature_sync_states", ["symbol"], unique=False)
    op.create_index(op.f("ix_feature_sync_states_timeframe"), "feature_sync_states", ["timeframe"], unique=False)
    op.create_index(op.f("ix_feature_sync_states_venue"), "feature_sync_states", ["venue"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_feature_sync_states_venue"), table_name="feature_sync_states")
    op.drop_index(op.f("ix_feature_sync_states_timeframe"), table_name="feature_sync_states")
    op.drop_index(op.f("ix_feature_sync_states_symbol"), table_name="feature_sync_states")
    op.drop_index(op.f("ix_feature_sync_states_asset_class"), table_name="feature_sync_states")
    op.drop_table("feature_sync_states")

    op.drop_index(op.f("ix_feature_snapshots_venue"), table_name="feature_snapshots")
    op.drop_index(op.f("ix_feature_snapshots_timeframe"), table_name="feature_snapshots")
    op.drop_index(op.f("ix_feature_snapshots_symbol"), table_name="feature_snapshots")
    op.drop_index(op.f("ix_feature_snapshots_computed_at"), table_name="feature_snapshots")
    op.drop_index(op.f("ix_feature_snapshots_candle_timestamp"), table_name="feature_snapshots")
    op.drop_index(op.f("ix_feature_snapshots_asset_class"), table_name="feature_snapshots")
    op.drop_table("feature_snapshots")
