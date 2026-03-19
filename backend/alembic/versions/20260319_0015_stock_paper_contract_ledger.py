"""stock paper contract ledger table

Revision ID: 20260319_0015
Revises: 20260318_0014
Create Date: 2026-03-19 18:55:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260319_0015"
down_revision: str | None = "20260318_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_paper_contract_ledger",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.String(length=10), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("strategy_name", sa.String(length=50), nullable=False, server_default="htf_reclaim_long"),
        sa.Column("timeframe", sa.String(length=10), nullable=False, server_default="5m"),
        sa.Column("ai_named", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ai_bucket", sa.String(length=30), nullable=True),
        sa.Column("ai_reason", sa.Text(), nullable=True),
        sa.Column("ai_quality_1h", sa.String(length=20), nullable=True),
        sa.Column("ai_quality_15m", sa.String(length=20), nullable=True),
        sa.Column("ai_reclaim_state", sa.String(length=30), nullable=True),
        sa.Column("ai_risk_note", sa.Text(), nullable=True),
        sa.Column("ai_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("strategy_status", sa.String(length=20), nullable=True),
        sa.Column("candidate_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pair_1h_used", sa.String(length=40), nullable=True),
        sa.Column("pair_15m_used", sa.String(length=40), nullable=True),
        sa.Column("bias_pass_1h", sa.Boolean(), nullable=True),
        sa.Column("setup_pass_15m", sa.Boolean(), nullable=True),
        sa.Column("trigger_pass_5m", sa.Boolean(), nullable=True),
        sa.Column("indicator_approved", sa.Boolean(), nullable=True),
        sa.Column("risk_status", sa.String(length=30), nullable=True),
        sa.Column("risk_decision_reason", sa.Text(), nullable=True),
        sa.Column("entry_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("stop_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("target_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("trade_taken", sa.Boolean(), nullable=True),
        sa.Column("trade_status", sa.String(length=30), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position_status", sa.String(length=30), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("outcome", sa.String(length=30), nullable=True),
        sa.Column("notes_json", sa.JSON(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "symbol", "strategy_name", name="uq_stock_paper_contract_ledger_trade_symbol_strategy"),
    )
    op.create_index("ix_stock_paper_contract_ledger_trade_date", "stock_paper_contract_ledger", ["trade_date"])
    op.create_index("ix_stock_paper_contract_ledger_symbol", "stock_paper_contract_ledger", ["symbol"])
    op.create_index("ix_stock_paper_contract_ledger_strategy_name", "stock_paper_contract_ledger", ["strategy_name"])
    op.create_index("ix_stock_paper_contract_ledger_ai_bucket", "stock_paper_contract_ledger", ["ai_bucket"])
    op.create_index("ix_stock_paper_contract_ledger_ai_scanned_at", "stock_paper_contract_ledger", ["ai_scanned_at"])
    op.create_index("ix_stock_paper_contract_ledger_strategy_status", "stock_paper_contract_ledger", ["strategy_status"])
    op.create_index("ix_stock_paper_contract_ledger_candidate_timestamp", "stock_paper_contract_ledger", ["candidate_timestamp"])
    op.create_index("ix_stock_paper_contract_ledger_risk_status", "stock_paper_contract_ledger", ["risk_status"])
    op.create_index("ix_stock_paper_contract_ledger_trade_status", "stock_paper_contract_ledger", ["trade_status"])
    op.create_index("ix_stock_paper_contract_ledger_filled_at", "stock_paper_contract_ledger", ["filled_at"])
    op.create_index("ix_stock_paper_contract_ledger_position_status", "stock_paper_contract_ledger", ["position_status"])
    op.create_index("ix_stock_paper_contract_ledger_outcome", "stock_paper_contract_ledger", ["outcome"])
    op.create_index("ix_stock_paper_contract_ledger_first_seen_at", "stock_paper_contract_ledger", ["first_seen_at"])
    op.create_index("ix_stock_paper_contract_ledger_last_synced_at", "stock_paper_contract_ledger", ["last_synced_at"])
    op.create_index("ix_stock_paper_contract_ledger_closed_at", "stock_paper_contract_ledger", ["closed_at"])


def downgrade() -> None:
    op.drop_index("ix_stock_paper_contract_ledger_closed_at", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_last_synced_at", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_first_seen_at", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_outcome", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_position_status", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_filled_at", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_trade_status", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_risk_status", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_candidate_timestamp", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_strategy_status", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_ai_scanned_at", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_ai_bucket", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_strategy_name", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_symbol", table_name="stock_paper_contract_ledger")
    op.drop_index("ix_stock_paper_contract_ledger_trade_date", table_name="stock_paper_contract_ledger")
    op.drop_table("stock_paper_contract_ledger")
