"""phase8 strategy engine tables

Revision ID: 20260314_0006
Revises: 20260314_0005
Create Date: 2026-03-14 08:25:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260314_0006"
down_revision: str | None = "20260314_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("strategy_name", sa.String(length=100), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False, server_default="long"),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("candidate_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("regime", sa.String(length=20), nullable=True),
        sa.Column("entry_policy", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("readiness_score", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("composite_score", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("threshold_score", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("trend_score", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("participation_score", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("liquidity_score", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("stability_score", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("blocked_reasons", sa.JSON(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_class",
            "symbol",
            "strategy_name",
            "timeframe",
            "candidate_timestamp",
            name="uq_strategy_snapshots_asset_symbol_strategy_timeframe_timestamp",
        ),
    )
    op.create_index(op.f("ix_strategy_snapshots_asset_class"), "strategy_snapshots", ["asset_class"], unique=False)
    op.create_index(op.f("ix_strategy_snapshots_candidate_timestamp"), "strategy_snapshots", ["candidate_timestamp"], unique=False)
    op.create_index(op.f("ix_strategy_snapshots_computed_at"), "strategy_snapshots", ["computed_at"], unique=False)
    op.create_index(op.f("ix_strategy_snapshots_status"), "strategy_snapshots", ["status"], unique=False)
    op.create_index(op.f("ix_strategy_snapshots_strategy_name"), "strategy_snapshots", ["strategy_name"], unique=False)
    op.create_index(op.f("ix_strategy_snapshots_symbol"), "strategy_snapshots", ["symbol"], unique=False)
    op.create_index(op.f("ix_strategy_snapshots_timeframe"), "strategy_snapshots", ["timeframe"], unique=False)
    op.create_index(op.f("ix_strategy_snapshots_venue"), "strategy_snapshots", ["venue"], unique=False)

    op.create_table(
        "strategy_sync_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("last_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_candidate_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ready_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("regime", sa.String(length=20), nullable=True),
        sa.Column("entry_policy", sa.String(length=20), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_class",
            "timeframe",
            name="uq_strategy_sync_states_asset_timeframe",
        ),
    )
    op.create_index(op.f("ix_strategy_sync_states_asset_class"), "strategy_sync_states", ["asset_class"], unique=False)
    op.create_index(op.f("ix_strategy_sync_states_timeframe"), "strategy_sync_states", ["timeframe"], unique=False)
    op.create_index(op.f("ix_strategy_sync_states_venue"), "strategy_sync_states", ["venue"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_strategy_sync_states_venue"), table_name="strategy_sync_states")
    op.drop_index(op.f("ix_strategy_sync_states_timeframe"), table_name="strategy_sync_states")
    op.drop_index(op.f("ix_strategy_sync_states_asset_class"), table_name="strategy_sync_states")
    op.drop_table("strategy_sync_states")

    op.drop_index(op.f("ix_strategy_snapshots_venue"), table_name="strategy_snapshots")
    op.drop_index(op.f("ix_strategy_snapshots_timeframe"), table_name="strategy_snapshots")
    op.drop_index(op.f("ix_strategy_snapshots_symbol"), table_name="strategy_snapshots")
    op.drop_index(op.f("ix_strategy_snapshots_strategy_name"), table_name="strategy_snapshots")
    op.drop_index(op.f("ix_strategy_snapshots_status"), table_name="strategy_snapshots")
    op.drop_index(op.f("ix_strategy_snapshots_computed_at"), table_name="strategy_snapshots")
    op.drop_index(op.f("ix_strategy_snapshots_candidate_timestamp"), table_name="strategy_snapshots")
    op.drop_index(op.f("ix_strategy_snapshots_asset_class"), table_name="strategy_snapshots")
    op.drop_table("strategy_snapshots")
