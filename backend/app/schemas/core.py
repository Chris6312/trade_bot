from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SettingUpsert(BaseModel):
    value: str
    value_type: str = "string"
    description: str | None = None
    is_secret: bool = False


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
