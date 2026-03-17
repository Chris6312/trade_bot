"""ci crypto regime orderbook snapshots

Revision ID: 20260316_0012
Revises: 20260316_0011
Create Date: 2026-03-16 22:10:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260316_0012"
down_revision: str | None = "20260316_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ci_crypto_regime_orderbook_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("venue", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("bid_levels", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ask_levels", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("best_bid", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("best_ask", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("spread_bps", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("top10_imbalance", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("top25_depth_usd", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("sweep_cost_buy_5k_bps", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("sweep_cost_sell_5k_bps", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("as_of_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["ci_crypto_regime_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ci_crypto_regime_orderbook_snapshots_as_of_at"),
        "ci_crypto_regime_orderbook_snapshots",
        ["as_of_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ci_crypto_regime_orderbook_snapshots_run_id"),
        "ci_crypto_regime_orderbook_snapshots",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ci_crypto_regime_orderbook_snapshots_symbol"),
        "ci_crypto_regime_orderbook_snapshots",
        ["symbol"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ci_crypto_regime_orderbook_snapshots_symbol"), table_name="ci_crypto_regime_orderbook_snapshots")
    op.drop_index(op.f("ix_ci_crypto_regime_orderbook_snapshots_run_id"), table_name="ci_crypto_regime_orderbook_snapshots")
    op.drop_index(op.f("ix_ci_crypto_regime_orderbook_snapshots_as_of_at"), table_name="ci_crypto_regime_orderbook_snapshots")
    op.drop_table("ci_crypto_regime_orderbook_snapshots")
