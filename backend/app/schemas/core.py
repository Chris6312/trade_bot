from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SettingUpsert(BaseModel):
    value: str
    value_type: str = "string"
    description: str | None = None
    is_secret: bool = False


class SettingBatchUpsertItem(SettingUpsert):
    key: str


class SettingBatchUpsertRequest(BaseModel):
    items: list[SettingBatchUpsertItem] = Field(default_factory=list)


class SettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str
    value_type: str
    description: str | None
    is_secret: bool
    updated_at: datetime


class RuntimeSettingsSnapshot(BaseModel):
    app_name: str
    app_env: str
    api_v1_prefix: str
    backend_port: int
    frontend_port: int
    postgres_host_port: int
    cors_origins: list[str]
    database_url_masked: str
    setting_sources: dict[str, Literal["environment", "database"]]


class WorkflowRunCreate(BaseModel):
    workflow_name: str
    status: str = "running"
    trigger_source: str | None = None
    notes: str | None = None


class WorkflowStageCreate(BaseModel):
    stage_name: str
    status: str = "pending"
    details: str | None = None
    completed_at: datetime | None = None


class WorkflowStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_run_id: int
    stage_name: str
    status: str
    details: str | None
    started_at: datetime
    completed_at: datetime | None


class WorkflowRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_name: str
    status: str
    trigger_source: str | None
    notes: str | None
    started_at: datetime
    completed_at: datetime | None
    stages: list[WorkflowStageRead] = Field(default_factory=list)


class AccountSnapshotCreate(BaseModel):
    account_scope: str
    venue: str
    mode: str
    equity: Decimal
    cash: Decimal
    buying_power: Decimal | None = None
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    as_of: datetime | None = None


class AccountSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_scope: str
    venue: str
    mode: str
    equity: Decimal
    cash: Decimal
    buying_power: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    as_of: datetime


class SystemEventCreate(BaseModel):
    event_type: str
    severity: str
    message: str
    event_source: str | None = None
    payload: dict[str, Any] | None = None


class SystemEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    severity: str
    message: str
    event_source: str | None
    payload: dict[str, Any] | None
    created_at: datetime


class RegimeSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_class: str
    venue: str
    source: str
    timeframe: str
    regime_timestamp: datetime
    computed_at: datetime
    regime: str
    entry_policy: str
    symbol_count: int
    bull_score: Decimal
    breadth_ratio: Decimal
    benchmark_support_ratio: Decimal
    participation_ratio: Decimal
    volatility_support_ratio: Decimal
    payload: dict[str, Any] | None


class RegimeSyncStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_class: str
    venue: str
    timeframe: str
    last_computed_at: datetime | None
    last_feature_at: datetime | None
    regime: str | None
    entry_policy: str | None
    symbol_count: int
    last_status: str
    last_error: str | None


class StrategySnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_class: str
    venue: str
    source: str
    symbol: str
    strategy_name: str
    direction: str
    timeframe: str
    candidate_timestamp: datetime
    computed_at: datetime
    regime: str | None
    entry_policy: str | None
    status: str
    readiness_score: Decimal
    composite_score: Decimal
    threshold_score: Decimal
    trend_score: Decimal
    participation_score: Decimal
    liquidity_score: Decimal
    stability_score: Decimal
    blocked_reasons: list[str] | None
    decision_reason: str | None
    payload: dict[str, Any] | None


class StrategySyncStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_class: str
    venue: str
    timeframe: str
    last_computed_at: datetime | None
    last_candidate_at: datetime | None
    candidate_count: int
    ready_count: int
    blocked_count: int
    regime: str | None
    entry_policy: str | None
    last_status: str
    last_error: str | None


class RiskSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_class: str
    venue: str
    source: str
    symbol: str
    strategy_name: str
    direction: str
    timeframe: str
    candidate_timestamp: datetime
    computed_at: datetime
    status: str
    risk_profile: str
    decision_reason: str | None
    blocked_reasons: list[str] | None
    account_equity: Decimal | None
    account_cash: Decimal | None
    entry_price: Decimal | None
    stop_price: Decimal | None
    stop_distance: Decimal | None
    stop_distance_pct: Decimal | None
    quantity: Decimal | None
    notional_value: Decimal | None
    deployment_pct: Decimal | None
    cumulative_deployment_pct: Decimal | None
    requested_risk_pct: Decimal | None
    effective_risk_pct: Decimal | None
    max_risk_pct: Decimal | None
    risk_budget_amount: Decimal | None
    projected_loss_amount: Decimal | None
    projected_loss_pct: Decimal | None
    fee_pct: Decimal | None
    slippage_pct: Decimal | None
    estimated_fees: Decimal | None
    estimated_slippage: Decimal | None
    strategy_readiness_score: Decimal | None
    strategy_composite_score: Decimal | None
    strategy_threshold_score: Decimal | None
    payload: dict[str, Any] | None


class RiskSyncStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_class: str
    venue: str
    timeframe: str
    last_computed_at: datetime | None
    last_candidate_at: datetime | None
    candidate_count: int
    accepted_count: int
    blocked_count: int
    deployment_pct: Decimal
    breaker_status: str | None
    last_status: str
    last_error: str | None


class ExecutionOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    risk_snapshot_id: int
    asset_class: str
    venue: str
    mode: str
    source: str
    symbol: str
    strategy_name: str
    direction: str
    timeframe: str
    candidate_timestamp: datetime
    routed_at: datetime
    client_order_id: str
    broker_order_id: str | None
    status: str
    order_type: str
    side: str
    quantity: Decimal | None
    notional_value: Decimal | None
    limit_price: Decimal | None
    stop_price: Decimal | None
    fill_count: int
    decision_reason: str | None
    error_message: str | None
    payload: dict[str, Any] | None


class ExecutionFillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    execution_order_id: int
    asset_class: str
    venue: str
    mode: str
    symbol: str
    timeframe: str
    fill_timestamp: datetime
    status: str
    quantity: Decimal
    fill_price: Decimal
    notional_value: Decimal
    fee_amount: Decimal | None
    venue_fill_id: str | None
    payload: dict[str, Any] | None


class ExecutionSyncStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_class: str
    venue: str
    mode: str
    timeframe: str
    last_routed_at: datetime | None
    last_candidate_at: datetime | None
    candidate_count: int
    routed_count: int
    duplicate_count: int
    blocked_count: int
    failed_count: int
    fill_count: int
    last_status: str
    last_error: str | None


class StopStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    execution_order_id: int
    execution_fill_id: int | None
    risk_snapshot_id: int | None
    asset_class: str
    venue: str
    mode: str
    source: str
    symbol: str
    strategy_name: str
    direction: str
    timeframe: str
    stop_style: str
    status: str
    entry_price: Decimal
    initial_stop_price: Decimal
    current_stop_price: Decimal
    current_price: Decimal | None
    highest_price: Decimal | None
    trailing_activation_price: Decimal | None
    trailing_offset_pct: Decimal | None
    trailing_active: bool
    trailing_activated_at: datetime | None
    step_trigger_pct: Decimal | None
    step_increment_pct: Decimal | None
    step_level: int
    next_step_trigger_price: Decimal | None
    protected_quantity: Decimal | None
    broker_stop_order_id: str | None
    last_fill_at: datetime | None
    last_evaluated_at: datetime | None
    last_updated_at: datetime | None
    update_count: int
    last_error: str | None
    payload: dict[str, Any] | None


class StopUpdateHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stop_state_id: int
    asset_class: str
    venue: str
    mode: str
    symbol: str
    timeframe: str
    event_timestamp: datetime
    event_type: str
    status: str
    previous_stop_price: Decimal | None
    new_stop_price: Decimal | None
    reference_price: Decimal | None
    high_watermark: Decimal | None
    step_level: int | None
    broker_stop_order_id: str | None
    message: str | None
    payload: dict[str, Any] | None


class StopSyncStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_class: str
    venue: str
    mode: str
    timeframe: str
    last_evaluated_at: datetime | None
    last_fill_at: datetime | None
    filled_count: int
    created_count: int
    activated_count: int
    updated_count: int
    unchanged_count: int
    failed_count: int
    last_status: str
    last_error: str | None


class PositionStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_class: str
    venue: str
    mode: str
    source: str
    symbol: str
    timeframe: str
    side: str
    status: str
    reconciliation_status: str
    quantity: Decimal
    broker_quantity: Decimal | None
    internal_quantity: Decimal | None
    quantity_delta: Decimal | None
    average_entry_price: Decimal | None
    broker_average_entry_price: Decimal | None
    internal_average_entry_price: Decimal | None
    cost_basis: Decimal | None
    market_value: Decimal | None
    current_price: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    last_fill_at: datetime | None
    synced_at: datetime
    mismatch_reason: str | None
    payload: dict[str, Any] | None




class PostTradeReviewRead(BaseModel):
    asset_class: str
    symbol: str
    venue: str
    mode: str
    strategy_name: str
    timeframe: str
    order_status: str
    fill_status: str | None = None
    stop_status: str | None = None
    position_status: str | None = None
    reconciliation_status: str | None = None
    candidate_timestamp: datetime | None = None
    routed_at: datetime | None = None
    fill_timestamp: datetime | None = None
    audit_event_count: int = 0
    review_notes: list[str] = Field(default_factory=list)
    order: ExecutionOrderRead
    fill: ExecutionFillRead | None = None
    stop: StopStateRead | None = None
    position: PositionStateRead | None = None
    related_events: list[SystemEventRead] = Field(default_factory=list)

class OpenOrderStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    execution_order_id: int | None
    asset_class: str
    venue: str
    mode: str
    source: str
    symbol: str
    timeframe: str
    unique_order_key: str
    client_order_id: str | None
    broker_order_id: str | None
    status: str
    order_type: str
    side: str
    quantity: Decimal | None
    notional_value: Decimal | None
    limit_price: Decimal | None
    stop_price: Decimal | None
    submitted_at: datetime | None
    synced_at: datetime
    reconciliation_status: str
    mismatch_reason: str | None
    payload: dict[str, Any] | None


class ReconciliationMismatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_class: str
    venue: str
    mode: str
    timeframe: str
    mismatch_type: str
    symbol: str | None
    severity: str
    status: str
    internal_value: str | None
    broker_value: str | None
    message: str
    detected_at: datetime
    resolved_at: datetime | None
    payload: dict[str, Any] | None


class PositionSyncStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_class: str
    venue: str
    mode: str
    timeframe: str
    last_synced_at: datetime | None
    last_fill_at: datetime | None
    position_count: int
    open_order_count: int
    mismatch_count: int
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    last_status: str
    last_error: str | None


class UniverseConstituentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    universe_run_id: int
    asset_class: str
    venue: str
    symbol: str
    rank: int
    source: str
    selection_reason: str | None
    payload: dict[str, Any] | None


class UniverseRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_class: str
    venue: str
    trade_date: date
    source: str
    status: str
    resolved_at: datetime | None
    snapshot_path: str | None
    last_error: str | None
    payload: dict[str, Any] | None
    constituents: list[UniverseConstituentRead] = Field(default_factory=list)


class CandleSyncStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_class: str
    venue: str
    symbol: str
    timeframe: str
    last_synced_at: datetime | None
    last_candle_at: datetime | None
    last_status: str
    last_error: str | None


class CandleFreshnessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_class: str
    venue: str
    symbol: str
    timeframe: str
    last_synced_at: datetime | None
    last_candle_at: datetime | None
    fresh_through: datetime | None


class FeatureSyncStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_class: str
    venue: str
    symbol: str
    timeframe: str
    last_computed_at: datetime | None
    last_candle_at: datetime | None
    feature_count: int
    last_status: str
    last_error: str | None




class ValidationRequest(BaseModel):
    note: str | None = None


class ValidationResultRead(BaseModel):
    validation_type: str
    asset_class: str | None = None
    status: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class LiveRolloutChecklistItemRead(BaseModel):
    key: str
    label: str
    status: str
    detail: str
    action_required: str | None = None


class LiveRolloutChecklistRead(BaseModel):
    generated_at: datetime
    overall_status: str
    default_mode: str
    stock_mode: str
    crypto_mode: str
    live_asset_count: int
    items: list[LiveRolloutChecklistItemRead] = Field(default_factory=list)

class ControlActionRequest(BaseModel):
    asset_class: Literal["stock", "crypto", "all"] = "all"
    timeframe: str | None = None
    force: bool = False
    symbols: list[str] | None = None


class KillSwitchToggleRequest(BaseModel):
    enabled: bool | None = None


class FlattenRequest(BaseModel):
    engage_kill_switch: bool = True
    note: str | None = None


class ControlActionResponse(BaseModel):
    action: str
    status: str
    message: str
    details: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class ControlSnapshotRead(BaseModel):
    kill_switch_enabled: bool
    default_mode: str
    stock_mode: str
    crypto_mode: str
    stock_trading_enabled: bool
    crypto_trading_enabled: bool
    last_updated_at: datetime | None = None
