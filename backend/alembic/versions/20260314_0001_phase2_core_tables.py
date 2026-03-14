"""phase2 core tables

Revision ID: 20260314_0001
Revises:
Create Date: 2026-03-14 00:01:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260314_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_scope", sa.String(length=30), nullable=False),
        sa.Column("venue", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("equity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("cash", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("buying_power", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(precision=18, scale=4), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.Numeric(precision=18, scale=4), nullable=False, server_default="0"),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_account_snapshots_account_scope"), "account_snapshots", ["account_scope"], unique=False)
    op.create_index(op.f("ix_account_snapshots_as_of"), "account_snapshots", ["as_of"], unique=False)
    op.create_index(op.f("ix_account_snapshots_mode"), "account_snapshots", ["mode"], unique=False)
    op.create_index(op.f("ix_account_snapshots_venue"), "account_snapshots", ["venue"], unique=False)

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(length=30), nullable=False, server_default="string"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(op.f("ix_settings_key"), "settings", ["key"], unique=True)

    op.create_table(
        "system_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("event_source", sa.String(length=100), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_events_created_at"), "system_events", ["created_at"], unique=False)
    op.create_index(op.f("ix_system_events_event_type"), "system_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_system_events_severity"), "system_events", ["severity"], unique=False)

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="running"),
        sa.Column("trigger_source", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workflow_runs_workflow_name"), "workflow_runs", ["workflow_name"], unique=False)

    op.create_table(
        "workflow_stage_statuses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), nullable=False),
        sa.Column("stage_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workflow_stage_statuses_stage_name"), "workflow_stage_statuses", ["stage_name"], unique=False)
    op.create_index(op.f("ix_workflow_stage_statuses_workflow_run_id"), "workflow_stage_statuses", ["workflow_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_workflow_stage_statuses_workflow_run_id"), table_name="workflow_stage_statuses")
    op.drop_index(op.f("ix_workflow_stage_statuses_stage_name"), table_name="workflow_stage_statuses")
    op.drop_table("workflow_stage_statuses")

    op.drop_index(op.f("ix_workflow_runs_workflow_name"), table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_index(op.f("ix_system_events_severity"), table_name="system_events")
    op.drop_index(op.f("ix_system_events_event_type"), table_name="system_events")
    op.drop_index(op.f("ix_system_events_created_at"), table_name="system_events")
    op.drop_table("system_events")

    op.drop_index(op.f("ix_settings_key"), table_name="settings")
    op.drop_table("settings")

    op.drop_index(op.f("ix_account_snapshots_venue"), table_name="account_snapshots")
    op.drop_index(op.f("ix_account_snapshots_mode"), table_name="account_snapshots")
    op.drop_index(op.f("ix_account_snapshots_as_of"), table_name="account_snapshots")
    op.drop_index(op.f("ix_account_snapshots_account_scope"), table_name="account_snapshots")
    op.drop_table("account_snapshots")
