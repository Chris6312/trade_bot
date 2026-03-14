"""phase5 universe engine tables

Revision ID: 20260314_0003
Revises: 20260314_0002
Create Date: 2026-03-14 01:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260314_0003"
down_revision: str | None = "20260314_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "universe_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_path", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_class", "trade_date", name="uq_universe_runs_asset_class_trade_date"),
    )
    op.create_index(op.f("ix_universe_runs_asset_class"), "universe_runs", ["asset_class"], unique=False)
    op.create_index(op.f("ix_universe_runs_trade_date"), "universe_runs", ["trade_date"], unique=False)
    op.create_index(op.f("ix_universe_runs_venue"), "universe_runs", ["venue"], unique=False)

    op.create_table(
        "universe_constituents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("universe_run_id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(length=20), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("selection_reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["universe_run_id"], ["universe_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("universe_run_id", "symbol", name="uq_universe_constituents_run_symbol"),
    )
    op.create_index(op.f("ix_universe_constituents_asset_class"), "universe_constituents", ["asset_class"], unique=False)
    op.create_index(op.f("ix_universe_constituents_symbol"), "universe_constituents", ["symbol"], unique=False)
    op.create_index(op.f("ix_universe_constituents_universe_run_id"), "universe_constituents", ["universe_run_id"], unique=False)
    op.create_index(op.f("ix_universe_constituents_venue"), "universe_constituents", ["venue"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_universe_constituents_venue"), table_name="universe_constituents")
    op.drop_index(op.f("ix_universe_constituents_universe_run_id"), table_name="universe_constituents")
    op.drop_index(op.f("ix_universe_constituents_symbol"), table_name="universe_constituents")
    op.drop_index(op.f("ix_universe_constituents_asset_class"), table_name="universe_constituents")
    op.drop_table("universe_constituents")

    op.drop_index(op.f("ix_universe_runs_venue"), table_name="universe_runs")
    op.drop_index(op.f("ix_universe_runs_trade_date"), table_name="universe_runs")
    op.drop_index(op.f("ix_universe_runs_asset_class"), table_name="universe_runs")
    op.drop_table("universe_runs")
