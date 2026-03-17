"""ci crypto regime addon tables

Revision ID: 20260316_0011
Revises: 20260314_0010
Create Date: 2026-03-16 20:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260316_0011"
down_revision: str | None = "20260314_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ci_crypto_regime_model_registry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=120), nullable=False),
        sa.Column("feature_set_version", sa.String(length=120), nullable=False),
        sa.Column("scaler_version", sa.String(length=120), nullable=True),
        sa.Column("model_type", sa.String(length=40), nullable=False),
        sa.Column("label_map_json", sa.JSON(), nullable=True),
        sa.Column("training_window_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("training_window_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("training_notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_version"),
    )
    op.create_index(op.f("ix_ci_crypto_regime_model_registry_is_active"), "ci_crypto_regime_model_registry", ["is_active"], unique=False)
    op.create_index(op.f("ix_ci_crypto_regime_model_registry_model_type"), "ci_crypto_regime_model_registry", ["model_type"], unique=False)
    op.create_index(op.f("ix_ci_crypto_regime_model_registry_model_version"), "ci_crypto_regime_model_registry", ["model_version"], unique=False)

    op.create_table(
        "ci_crypto_regime_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("skip_reason", sa.String(length=60), nullable=True),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("feature_set_version", sa.String(length=120), nullable=True),
        sa.Column("used_orderbook", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("used_defillama", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("used_hurst", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("data_window_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ci_crypto_regime_runs_model_version"), "ci_crypto_regime_runs", ["model_version"], unique=False)
    op.create_index(op.f("ix_ci_crypto_regime_runs_run_started_at"), "ci_crypto_regime_runs", ["run_started_at"], unique=False)
    op.create_index(op.f("ix_ci_crypto_regime_runs_status"), "ci_crypto_regime_runs", ["status"], unique=False)

    op.create_table(
        "ci_crypto_regime_feature_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("symbol_scope", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=True),
        sa.Column("feature_name", sa.String(length=120), nullable=False),
        sa.Column("feature_value", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("feature_status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("as_of_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["ci_crypto_regime_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ci_crypto_regime_feature_snapshots_as_of_at"), "ci_crypto_regime_feature_snapshots", ["as_of_at"], unique=False)
    op.create_index(op.f("ix_ci_crypto_regime_feature_snapshots_feature_name"), "ci_crypto_regime_feature_snapshots", ["feature_name"], unique=False)
    op.create_index(op.f("ix_ci_crypto_regime_feature_snapshots_feature_status"), "ci_crypto_regime_feature_snapshots", ["feature_status"], unique=False)
    op.create_index(op.f("ix_ci_crypto_regime_feature_snapshots_run_id"), "ci_crypto_regime_feature_snapshots", ["run_id"], unique=False)
    op.create_index(op.f("ix_ci_crypto_regime_feature_snapshots_symbol_scope"), "ci_crypto_regime_feature_snapshots", ["symbol_scope"], unique=False)
    op.create_index(op.f("ix_ci_crypto_regime_feature_snapshots_timeframe"), "ci_crypto_regime_feature_snapshots", ["timeframe"], unique=False)

    op.create_table(
        "ci_crypto_regime_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("as_of_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=10, scale=5), nullable=False, server_default="0"),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("cluster_prob_bull", sa.Numeric(precision=10, scale=5), nullable=True),
        sa.Column("cluster_prob_neutral", sa.Numeric(precision=10, scale=5), nullable=True),
        sa.Column("cluster_prob_risk_off", sa.Numeric(precision=10, scale=5), nullable=True),
        sa.Column("agreement_with_core", sa.String(length=20), nullable=False),
        sa.Column("advisory_action", sa.String(length=20), nullable=False),
        sa.Column("core_regime_state", sa.String(length=20), nullable=True),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason_codes_json", sa.JSON(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["ci_crypto_regime_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_ci_crypto_regime_states_run_id"),
    )
    op.create_index(op.f("ix_ci_crypto_regime_states_agreement_with_core"), "ci_crypto_regime_states", ["agreement_with_core"], unique=False)
    op.create_index(op.f("ix_ci_crypto_regime_states_as_of_at"), "ci_crypto_regime_states", ["as_of_at"], unique=False)
    op.create_index(op.f("ix_ci_crypto_regime_states_run_id"), "ci_crypto_regime_states", ["run_id"], unique=False)
    op.create_index(op.f("ix_ci_crypto_regime_states_state"), "ci_crypto_regime_states", ["state"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ci_crypto_regime_states_state"), table_name="ci_crypto_regime_states")
    op.drop_index(op.f("ix_ci_crypto_regime_states_run_id"), table_name="ci_crypto_regime_states")
    op.drop_index(op.f("ix_ci_crypto_regime_states_as_of_at"), table_name="ci_crypto_regime_states")
    op.drop_index(op.f("ix_ci_crypto_regime_states_agreement_with_core"), table_name="ci_crypto_regime_states")
    op.drop_table("ci_crypto_regime_states")

    op.drop_index(op.f("ix_ci_crypto_regime_feature_snapshots_timeframe"), table_name="ci_crypto_regime_feature_snapshots")
    op.drop_index(op.f("ix_ci_crypto_regime_feature_snapshots_symbol_scope"), table_name="ci_crypto_regime_feature_snapshots")
    op.drop_index(op.f("ix_ci_crypto_regime_feature_snapshots_run_id"), table_name="ci_crypto_regime_feature_snapshots")
    op.drop_index(op.f("ix_ci_crypto_regime_feature_snapshots_feature_status"), table_name="ci_crypto_regime_feature_snapshots")
    op.drop_index(op.f("ix_ci_crypto_regime_feature_snapshots_feature_name"), table_name="ci_crypto_regime_feature_snapshots")
    op.drop_index(op.f("ix_ci_crypto_regime_feature_snapshots_as_of_at"), table_name="ci_crypto_regime_feature_snapshots")
    op.drop_table("ci_crypto_regime_feature_snapshots")

    op.drop_index(op.f("ix_ci_crypto_regime_runs_status"), table_name="ci_crypto_regime_runs")
    op.drop_index(op.f("ix_ci_crypto_regime_runs_run_started_at"), table_name="ci_crypto_regime_runs")
    op.drop_index(op.f("ix_ci_crypto_regime_runs_model_version"), table_name="ci_crypto_regime_runs")
    op.drop_table("ci_crypto_regime_runs")

    op.drop_index(op.f("ix_ci_crypto_regime_model_registry_model_version"), table_name="ci_crypto_regime_model_registry")
    op.drop_index(op.f("ix_ci_crypto_regime_model_registry_model_type"), table_name="ci_crypto_regime_model_registry")
    op.drop_index(op.f("ix_ci_crypto_regime_model_registry_is_active"), table_name="ci_crypto_regime_model_registry")
    op.drop_table("ci_crypto_regime_model_registry")
