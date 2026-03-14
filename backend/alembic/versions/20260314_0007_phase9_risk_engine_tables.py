"""phase9 risk engine tables

Revision ID: 20260314_0007
Revises: 20260314_0006
Create Date: 2026-03-14 08:55:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260314_0007"
down_revision: str | None = "20260314_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_snapshots",
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
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("risk_profile", sa.String(length=30), nullable=False, server_default="moderate"),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("blocked_reasons", sa.JSON(), nullable=True),
        sa.Column("account_equity", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("account_cash", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("entry_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("stop_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("stop_distance", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("stop_distance_pct", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("notional_value", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("deployment_pct", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("cumulative_deployment_pct", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("requested_risk_pct", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("effective_risk_pct", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("max_risk_pct", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("risk_budget_amount", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("projected_loss_amount", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("projected_loss_pct", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("fee_pct", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("slippage_pct", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("estimated_fees", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("estimated_slippage", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("strategy_readiness_score", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("strategy_composite_score", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("strategy_threshold_score", sa.Numeric(precision=20, scale=8), nullable=True),
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
            name="uq_risk_snapshots_asset_symbol_strategy_timeframe_timestamp",
        ),
    )
    op.create_index(op.f("ix_risk_snapshots_asset_class"), "risk_snapshots", ["asset_class"], unique=False)
    op.create_index(op.f("ix_risk_snapshots_candidate_timestamp"), "risk_snapshots", ["candidate_timestamp"], unique=False)
    op.create_index(op.f("ix_risk_snapshots_computed_at"), "risk_snapshots", ["computed_at"], unique=False)
    op.create_index(op.f("ix_risk_snapshots_status"), "risk_snapshots", ["status"], unique=False)
    op.create_index(op.f("ix_risk_snapshots_strategy_name"), "risk_snapshots", ["strategy_name"], unique=False)
    op.create_index(op.f("ix_risk_snapshots_symbol"), "risk_snapshots", ["symbol"], unique=False)
    op.create_index(op.f("ix_risk_snapshots_timeframe"), "risk_snapshots", ["timeframe"], unique=False)
    op.create_index(op.f("ix_risk_snapshots_venue"), "risk_snapshots", ["venue"], unique=False)

    op.create_table(
        "risk_sync_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("last_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_candidate_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deployment_pct", sa.Numeric(precision=20, scale=8), nullable=False, server_default="0"),
        sa.Column("breaker_status", sa.String(length=30), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_class", "timeframe", name="uq_risk_sync_states_asset_timeframe"),
    )
    op.create_index(op.f("ix_risk_sync_states_asset_class"), "risk_sync_states", ["asset_class"], unique=False)
    op.create_index(op.f("ix_risk_sync_states_timeframe"), "risk_sync_states", ["timeframe"], unique=False)
    op.create_index(op.f("ix_risk_sync_states_venue"), "risk_sync_states", ["venue"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_risk_sync_states_venue"), table_name="risk_sync_states")
    op.drop_index(op.f("ix_risk_sync_states_timeframe"), table_name="risk_sync_states")
    op.drop_index(op.f("ix_risk_sync_states_asset_class"), table_name="risk_sync_states")
    op.drop_table("risk_sync_states")

    op.drop_index(op.f("ix_risk_snapshots_venue"), table_name="risk_snapshots")
    op.drop_index(op.f("ix_risk_snapshots_timeframe"), table_name="risk_snapshots")
    op.drop_index(op.f("ix_risk_snapshots_symbol"), table_name="risk_snapshots")
    op.drop_index(op.f("ix_risk_snapshots_strategy_name"), table_name="risk_snapshots")
    op.drop_index(op.f("ix_risk_snapshots_status"), table_name="risk_snapshots")
    op.drop_index(op.f("ix_risk_snapshots_computed_at"), table_name="risk_snapshots")
    op.drop_index(op.f("ix_risk_snapshots_candidate_timestamp"), table_name="risk_snapshots")
    op.drop_index(op.f("ix_risk_snapshots_asset_class"), table_name="risk_snapshots")
    op.drop_table("risk_snapshots")
