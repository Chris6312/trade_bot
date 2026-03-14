from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from backend.app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Setting(TimestampMixin, Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text())
    value_type: Mapped[str] = mapped_column(String(30), default="string")
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class WorkflowRun(TimestampMixin, Base):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_name: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    trigger_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    stages: Mapped[list["WorkflowStageStatus"]] = relationship(
        back_populates="workflow_run",
        cascade="all, delete-orphan",
        order_by="WorkflowStageStatus.id",
    )


class WorkflowStageStatus(TimestampMixin, Base):
    __tablename__ = "workflow_stage_statuses"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    stage_name: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    details: Mapped[str | None] = mapped_column(Text(), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow_run: Mapped[WorkflowRun] = relationship(back_populates="stages")


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_scope: Mapped[str] = mapped_column(String(30), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    equity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    buying_power: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )


class SystemEvent(Base):
    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    message: Mapped[str] = mapped_column(Text())
    event_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )


class UniverseRun(TimestampMixin, Base):
    __tablename__ = "universe_runs"
    __table_args__ = (
        UniqueConstraint("asset_class", "trade_date", name="uq_universe_runs_asset_class_trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    trade_date: Mapped[date] = mapped_column(Date(), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(Text(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    constituents: Mapped[list["UniverseConstituent"]] = relationship(
        back_populates="universe_run",
        cascade="all, delete-orphan",
        order_by="UniverseConstituent.rank.asc()",
    )


class UniverseConstituent(TimestampMixin, Base):
    __tablename__ = "universe_constituents"
    __table_args__ = (
        UniqueConstraint("universe_run_id", "symbol", name="uq_universe_constituents_run_symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    universe_run_id: Mapped[int] = mapped_column(ForeignKey("universe_runs.id", ondelete="CASCADE"), index=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    selection_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    universe_run: Mapped[UniverseRun] = relationship(back_populates="constituents")


class FeatureSnapshot(TimestampMixin, Base):
    __tablename__ = "feature_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "asset_class",
            "symbol",
            "timeframe",
            "candle_timestamp",
            name="uq_feature_snapshots_asset_symbol_timeframe_timestamp",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    candle_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    price_return_1: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    sma_20: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    ema_20: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    momentum_20: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    volume_sma_20: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    relative_volume_20: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    dollar_volume: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    dollar_volume_sma_20: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    atr_14: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    realized_volatility_20: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    trend_slope_20: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class FeatureSyncState(TimestampMixin, Base):
    __tablename__ = "feature_sync_states"
    __table_args__ = (
        UniqueConstraint(
            "asset_class",
            "symbol",
            "timeframe",
            name="uq_feature_sync_states_asset_symbol_timeframe",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    last_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_candle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)


class RegimeSnapshot(TimestampMixin, Base):
    __tablename__ = "regime_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "asset_class",
            "timeframe",
            "regime_timestamp",
            name="uq_regime_snapshots_asset_timeframe_timestamp",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    regime_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    regime: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    entry_policy: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bull_score: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    breadth_ratio: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    benchmark_support_ratio: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    participation_ratio: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volatility_support_ratio: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class RegimeSyncState(TimestampMixin, Base):
    __tablename__ = "regime_sync_states"
    __table_args__ = (
        UniqueConstraint(
            "asset_class",
            "timeframe",
            name="uq_regime_sync_states_asset_timeframe",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    last_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_feature_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    regime: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entry_policy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    symbol_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)


class StrategySnapshot(TimestampMixin, Base):
    __tablename__ = "strategy_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "asset_class",
            "symbol",
            "strategy_name",
            "timeframe",
            "candidate_timestamp",
            name="uq_strategy_snapshots_asset_symbol_strategy_timeframe_timestamp",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    strategy_name: Mapped[str] = mapped_column(String(100), index=True)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="long")
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    candidate_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    regime: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entry_policy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    readiness_score: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    composite_score: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    threshold_score: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    trend_score: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    participation_score: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    liquidity_score: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    stability_score: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    blocked_reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class StrategySyncState(TimestampMixin, Base):
    __tablename__ = "strategy_sync_states"
    __table_args__ = (
        UniqueConstraint(
            "asset_class",
            "timeframe",
            name="uq_strategy_sync_states_asset_timeframe",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    last_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_candidate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ready_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    regime: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entry_policy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)


class RiskSnapshot(TimestampMixin, Base):
    __tablename__ = "risk_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "asset_class",
            "symbol",
            "strategy_name",
            "timeframe",
            "candidate_timestamp",
            name="uq_risk_snapshots_asset_symbol_strategy_timeframe_timestamp",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    strategy_name: Mapped[str] = mapped_column(String(100), index=True)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="long")
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    candidate_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    risk_profile: Mapped[str] = mapped_column(String(30), nullable=False, default="moderate")
    decision_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    blocked_reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    account_equity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    account_cash: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_distance: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_distance_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    notional_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    deployment_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    cumulative_deployment_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    requested_risk_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    effective_risk_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    max_risk_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    risk_budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    projected_loss_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    projected_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    fee_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    slippage_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    estimated_fees: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    estimated_slippage: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    strategy_readiness_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    strategy_composite_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    strategy_threshold_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class RiskSyncState(TimestampMixin, Base):
    __tablename__ = "risk_sync_states"
    __table_args__ = (
        UniqueConstraint(
            "asset_class",
            "timeframe",
            name="uq_risk_sync_states_asset_timeframe",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    last_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_candidate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deployment_pct: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    breaker_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)




class ExecutionOrder(TimestampMixin, Base):
    __tablename__ = "execution_orders"
    __table_args__ = (
        UniqueConstraint("risk_snapshot_id", name="uq_execution_orders_risk_snapshot_id"),
        UniqueConstraint("client_order_id", name="uq_execution_orders_client_order_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    risk_snapshot_id: Mapped[int] = mapped_column(ForeignKey("risk_snapshots.id", ondelete="CASCADE"), index=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    strategy_name: Mapped[str] = mapped_column(String(100), index=True)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="long")
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    candidate_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    routed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    client_order_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False, default="market")
    side: Mapped[str] = mapped_column(String(20), nullable=False, default="buy")
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    notional_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    fill_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ExecutionFill(TimestampMixin, Base):
    __tablename__ = "execution_fills"
    __table_args__ = (
        UniqueConstraint(
            "execution_order_id",
            "fill_timestamp",
            "quantity",
            name="uq_execution_fills_order_timestamp_quantity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    execution_order_id: Mapped[int] = mapped_column(ForeignKey("execution_orders.id", ondelete="CASCADE"), index=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    fill_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    fill_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    notional_value: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    venue_fill_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ExecutionSyncState(TimestampMixin, Base):
    __tablename__ = "execution_sync_states"
    __table_args__ = (
        UniqueConstraint(
            "asset_class",
            "timeframe",
            name="uq_execution_sync_states_asset_timeframe",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    last_routed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_candidate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    routed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fill_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_status: Mapped[str] = mapped_column(String(30), default="idle", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)

class Candle(TimestampMixin, Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "asset_class",
            "symbol",
            "timeframe",
            "timestamp",
            name="uq_candles_asset_symbol_timeframe_timestamp",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CandleSyncState(TimestampMixin, Base):
    __tablename__ = "candle_sync_states"
    __table_args__ = (
        UniqueConstraint(
            "asset_class",
            "symbol",
            "timeframe",
            name="uq_candle_sync_states_asset_symbol_timeframe",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_candle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)


class CandleFreshness(TimestampMixin, Base):
    __tablename__ = "candle_freshness"
    __table_args__ = (
        UniqueConstraint(
            "asset_class",
            "symbol",
            "timeframe",
            name="uq_candle_freshness_asset_symbol_timeframe",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)
    venue: Mapped[str] = mapped_column(String(50), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_candle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fresh_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
