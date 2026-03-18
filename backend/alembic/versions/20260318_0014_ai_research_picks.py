"""ai research picks table and take_profit_price on risk_snapshots

Revision ID: 20260318_0014
Revises: 20260318_0013
Create Date: 2026-03-18 00:14:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260318_0014"
down_revision: str | None = "20260318_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- New table: ai_research_picks ---
    op.create_table(
        "ai_research_picks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.String(length=10), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("catalyst", sa.Text(), nullable=True),
        sa.Column("approximate_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("entry_zone_low", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("entry_zone_high", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("stop_loss", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("take_profit_primary", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("take_profit_stretch", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("use_trail_stop", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("position_size_dollars", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("risk_reward_note", sa.Text(), nullable=True),
        sa.Column("is_bonus_pick", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("account_cash_at_scan", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("venue", sa.String(length=50), nullable=False, server_default="alpaca"),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "symbol", name="uq_ai_research_picks_date_symbol"),
    )
    op.create_index("ix_ai_research_picks_trade_date", "ai_research_picks", ["trade_date"])
    op.create_index("ix_ai_research_picks_symbol", "ai_research_picks", ["symbol"])
    op.create_index("ix_ai_research_picks_scanned_at", "ai_research_picks", ["scanned_at"])

    # --- New column: risk_snapshots.take_profit_price ---
    op.add_column(
        "risk_snapshots",
        sa.Column("take_profit_price", sa.Numeric(precision=20, scale=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("risk_snapshots", "take_profit_price")
    op.drop_index("ix_ai_research_picks_scanned_at", table_name="ai_research_picks")
    op.drop_index("ix_ai_research_picks_symbol", table_name="ai_research_picks")
    op.drop_index("ix_ai_research_picks_trade_date", table_name="ai_research_picks")
    op.drop_table("ai_research_picks")
