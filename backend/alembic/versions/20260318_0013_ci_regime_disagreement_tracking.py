"""add ci regime disagreement tracking

Revision ID: 20260318_0013
Revises: 20260316_0012
Create Date: 2026-03-18 03:15:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260318_0013"
down_revision = "20260316_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ci_regime_disagreements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ci_run_id", sa.Integer(), nullable=False),
        sa.Column("as_of_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ci_state", sa.String(length=20), nullable=False),
        sa.Column("core_state", sa.String(length=20), nullable=False),
        sa.Column("ci_advisory_action", sa.String(length=20), nullable=False),
        sa.Column("btc_price_at_disagreement", sa.Numeric(20, 8), nullable=True),
        sa.Column("resolution_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_timeframe", sa.String(length=10), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column("outcome_basis", sa.String(length=40), nullable=True),
        sa.Column("btc_price_at_resolution", sa.Numeric(20, 8), nullable=True),
        sa.Column("btc_return_pct", sa.Numeric(10, 5), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["ci_run_id"], ["ci_crypto_regime_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ci_run_id"),
    )
    op.create_index(op.f("ix_ci_regime_disagreements_as_of_at"), "ci_regime_disagreements", ["as_of_at"], unique=False)
    op.create_index(op.f("ix_ci_regime_disagreements_ci_run_id"), "ci_regime_disagreements", ["ci_run_id"], unique=False)
    op.create_index(op.f("ix_ci_regime_disagreements_ci_state"), "ci_regime_disagreements", ["ci_state"], unique=False)
    op.create_index(op.f("ix_ci_regime_disagreements_core_state"), "ci_regime_disagreements", ["core_state"], unique=False)
    op.create_index(op.f("ix_ci_regime_disagreements_outcome"), "ci_regime_disagreements", ["outcome"], unique=False)
    op.create_index(op.f("ix_ci_regime_disagreements_resolution_at"), "ci_regime_disagreements", ["resolution_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ci_regime_disagreements_resolution_at"), table_name="ci_regime_disagreements")
    op.drop_index(op.f("ix_ci_regime_disagreements_outcome"), table_name="ci_regime_disagreements")
    op.drop_index(op.f("ix_ci_regime_disagreements_core_state"), table_name="ci_regime_disagreements")
    op.drop_index(op.f("ix_ci_regime_disagreements_ci_state"), table_name="ci_regime_disagreements")
    op.drop_index(op.f("ix_ci_regime_disagreements_ci_run_id"), table_name="ci_regime_disagreements")
    op.drop_index(op.f("ix_ci_regime_disagreements_as_of_at"), table_name="ci_regime_disagreements")
    op.drop_table("ci_regime_disagreements")
