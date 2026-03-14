"""phase7 regime engine tables

Revision ID: 20260314_0005
Revises: 20260314_0004
Create Date: 2026-03-14 07:55:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260314_0005"
down_revision: str | None = "20260314_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "regime_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("regime_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("regime", sa.String(length=20), nullable=False),
        sa.Column("entry_policy", sa.String(length=20), nullable=False),
        sa.Column("symbol_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bull_score", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("breadth_ratio", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("benchmark_support_ratio", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("participation_ratio", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("volatility_support_ratio", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_class",
            "timeframe",
            "regime_timestamp",
            name="uq_regime_snapshots_asset_timeframe_timestamp",
        ),
    )
    op.create_index(op.f("ix_regime_snapshots_asset_class"), "regime_snapshots", ["asset_class"], unique=False)
    op.create_index(op.f("ix_regime_snapshots_computed_at"), "regime_snapshots", ["computed_at"], unique=False)
    op.create_index(op.f("ix_regime_snapshots_regime"), "regime_snapshots", ["regime"], unique=False)
    op.create_index(op.f("ix_regime_snapshots_regime_timestamp"), "regime_snapshots", ["regime_timestamp"], unique=False)
    op.create_index(op.f("ix_regime_snapshots_timeframe"), "regime_snapshots", ["timeframe"], unique=False)
    op.create_index(op.f("ix_regime_snapshots_venue"), "regime_snapshots", ["venue"], unique=False)

    op.create_table(
        "regime_sync_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("last_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_feature_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("regime", sa.String(length=20), nullable=True),
        sa.Column("entry_policy", sa.String(length=20), nullable=True),
        sa.Column("symbol_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_class",
            "timeframe",
            name="uq_regime_sync_states_asset_timeframe",
        ),
    )
    op.create_index(op.f("ix_regime_sync_states_asset_class"), "regime_sync_states", ["asset_class"], unique=False)
    op.create_index(op.f("ix_regime_sync_states_timeframe"), "regime_sync_states", ["timeframe"], unique=False)
    op.create_index(op.f("ix_regime_sync_states_venue"), "regime_sync_states", ["venue"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_regime_sync_states_venue"), table_name="regime_sync_states")
    op.drop_index(op.f("ix_regime_sync_states_timeframe"), table_name="regime_sync_states")
    op.drop_index(op.f("ix_regime_sync_states_asset_class"), table_name="regime_sync_states")
    op.drop_table("regime_sync_states")

    op.drop_index(op.f("ix_regime_snapshots_venue"), table_name="regime_snapshots")
    op.drop_index(op.f("ix_regime_snapshots_timeframe"), table_name="regime_snapshots")
    op.drop_index(op.f("ix_regime_snapshots_regime_timestamp"), table_name="regime_snapshots")
    op.drop_index(op.f("ix_regime_snapshots_regime"), table_name="regime_snapshots")
    op.drop_index(op.f("ix_regime_snapshots_computed_at"), table_name="regime_snapshots")
    op.drop_index(op.f("ix_regime_snapshots_asset_class"), table_name="regime_snapshots")
    op.drop_table("regime_snapshots")
