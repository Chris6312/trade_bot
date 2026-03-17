from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CiCryptoRegimeModelRegistryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    model_version: str
    feature_set_version: str
    scaler_version: str | None
    model_type: str
    label_map_json: dict[str, Any] | None
    training_window_start_at: datetime | None
    training_window_end_at: datetime | None
    training_notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: str | None


class CiCryptoRegimeFeatureSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    symbol_scope: str
    timeframe: str | None
    feature_name: str
    feature_value: Decimal | None
    feature_status: str
    source: str
    as_of_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CiCryptoRegimeOrderbookSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    venue: str
    symbol: str
    bid_levels: int
    ask_levels: int
    best_bid: Decimal | None
    best_ask: Decimal | None
    spread_bps: Decimal | None
    top10_imbalance: Decimal | None
    top25_depth_usd: Decimal | None
    sweep_cost_buy_5k_bps: Decimal | None
    sweep_cost_sell_5k_bps: Decimal | None
    as_of_at: datetime | None
    payload_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class CiCryptoRegimeRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_started_at: datetime
    run_completed_at: datetime | None
    status: str
    skip_reason: str | None
    model_version: str
    feature_set_version: str
    used_orderbook: bool
    used_defillama: bool
    used_hurst: bool
    data_window_end_at: datetime | None
    error_message: str | None
    degraded: bool
    created_at: datetime
    updated_at: datetime


class CiCryptoRegimeStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    as_of_at: datetime
    state: str
    confidence: Decimal
    cluster_id: int | None
    cluster_prob_bull: Decimal | None
    cluster_prob_neutral: Decimal | None
    cluster_prob_risk_off: Decimal | None
    agreement_with_core: str
    advisory_action: str
    core_regime_state: str | None
    degraded: bool
    reason_codes_json: list[str] | None
    summary_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class CiCryptoRegimeCurrentRead(BaseModel):
    enabled: bool
    advisory_only: bool
    as_of_at: datetime
    state: str
    confidence: Decimal
    core_regime_state: str | None
    agreement_with_core: str
    advisory_action: str
    model_version: str
    feature_set_version: str
    degraded: bool
    reason_codes: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    core_regime_timeframe: str | None = None
    last_run_status: str | None = None
    last_run_started_at: datetime | None = None
    last_run_completed_at: datetime | None = None
    last_run_used_orderbook: bool = False
    last_run_used_defillama: bool = False
    last_run_used_hurst: bool = False
    orderbook_status: str | None = None
    orderbook_ready: bool = False
    defillama_status: str | None = None
    defillama_ready: bool = False
    hurst_status: str | None = None
    hurst_ready: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)


class CiCryptoRegimeHistoryRead(BaseModel):
    items: list[CiCryptoRegimeStateRead] = Field(default_factory=list)


class CiCryptoRegimeModelListRead(BaseModel):
    active_model_version: str | None = None
    items: list[CiCryptoRegimeModelRegistryRead] = Field(default_factory=list)


class CiCryptoRegimeRunDetailRead(BaseModel):
    run: CiCryptoRegimeRunRead
    state: CiCryptoRegimeStateRead | None
    features: list[CiCryptoRegimeFeatureSnapshotRead] = Field(default_factory=list)
    orderbook_snapshots: list[CiCryptoRegimeOrderbookSnapshotRead] = Field(default_factory=list)


class CiCryptoRegimeRuntimeStatusRead(BaseModel):
    enabled: bool
    advisory_only: bool
    model_version: str
    mode: str
    use_orderbook: bool
    use_defillama: bool
    use_hurst: bool
    promote_to_runtime: bool
    run_interval_minutes: int
    stale_after_seconds: int
    state: str | None = None
    confidence: Decimal | None = None
    agreement_with_core: str | None = None
    advisory_action: str | None = None
    core_regime_state: str | None = None
    core_regime_timeframe: str | None = None
    degraded: bool = False
    last_run_status: str | None = None
    last_run_started_at: datetime | None = None
    last_run_completed_at: datetime | None = None
    last_run_used_orderbook: bool = False
    last_run_used_defillama: bool = False
    last_run_used_hurst: bool = False
    orderbook_status: str | None = None
    orderbook_ready: bool = False
    defillama_status: str | None = None
    defillama_ready: bool = False
    hurst_status: str | None = None
    hurst_ready: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)
