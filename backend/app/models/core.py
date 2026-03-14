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
