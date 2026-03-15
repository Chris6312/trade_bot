from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.core.config import get_settings
from backend.app.schemas.core import (
    ControlActionRequest,
    ControlActionResponse,
    ControlSnapshotRead,
    FlattenRequest,
    KillSwitchToggleRequest,
)
from backend.app.services.operator_service import create_audit_event, create_system_event
from backend.app.services.settings_service import get_setting, upsert_setting
from backend.app.services.universe_service import list_universe_symbols, trading_date_for_now
from backend.app.workers.candle_worker import SingleCandleWorker
from backend.app.workers.feature_worker import FeatureWorker
from backend.app.workers.regime_worker import RegimeWorker
from backend.app.workers.strategy_worker import StrategyWorker
from backend.app.workers.universe_worker import UniverseWorker

router = APIRouter(prefix="/controls", tags=["controls"])


@router.get("/snapshot", response_model=ControlSnapshotRead)
def get_control_snapshot(db: Session = Depends(get_db)) -> ControlSnapshotRead:
    settings = get_settings()
    kill_switch_record = get_setting(db, key="controls.kill_switch_enabled")
    default_mode_record = get_setting(db, key="execution.default_mode")
    stock_mode_record = get_setting(db, key="execution.stock.mode")
    crypto_mode_record = get_setting(db, key="execution.crypto.mode")
    stock_enabled_record = get_setting(db, key="controls.stock.trading_enabled")
    crypto_enabled_record = get_setting(db, key="controls.crypto.trading_enabled")

    return ControlSnapshotRead(
        kill_switch_enabled=_setting_to_bool(kill_switch_record.value if kill_switch_record else settings.execution_kill_switch_enabled),
        default_mode=str(default_mode_record.value if default_mode_record else settings.default_mode),
        stock_mode=str(stock_mode_record.value if stock_mode_record else settings.stock_execution_mode),
        crypto_mode=str(crypto_mode_record.value if crypto_mode_record else settings.crypto_execution_mode),
        stock_trading_enabled=_setting_to_bool(stock_enabled_record.value if stock_enabled_record else True),
        crypto_trading_enabled=_setting_to_bool(crypto_enabled_record.value if crypto_enabled_record else True),
        last_updated_at=max((record.updated_at for record in [kill_switch_record, default_mode_record, stock_mode_record, crypto_mode_record, stock_enabled_record, crypto_enabled_record] if record is not None), default=None),
    )


@router.post("/kill-switch/toggle", response_model=ControlActionResponse)
def toggle_kill_switch(
    payload: KillSwitchToggleRequest,
    db: Session = Depends(get_db),
) -> ControlActionResponse:
    current = get_control_snapshot(db)
    target_enabled = (not current.kill_switch_enabled) if payload.enabled is None else payload.enabled
    record = upsert_setting(
        db,
        key="controls.kill_switch_enabled",
        value="true" if target_enabled else "false",
        value_type="bool",
        description="Master kill switch blocking new entries.",
    )
    _create_event(
        db,
        event_type="control.kill_switch_toggled",
        severity="warning" if target_enabled else "info",
        message=f"Kill switch {'enabled' if target_enabled else 'disabled'}.",
        payload={"enabled": target_enabled},
    )
    create_audit_event(
        db,
        event_type="audit.kill_switch_toggled",
        severity="warning" if target_enabled else "info",
        message=f"Operator {'enabled' if target_enabled else 'disabled'} the master kill switch.",
        payload={"enabled": target_enabled},
    )
    db.commit()
    return ControlActionResponse(
        action="toggle_kill_switch",
        status="completed",
        message=f"Kill switch {'enabled' if target_enabled else 'disabled'}.",
        details=[{"key": record.key, "value": record.value}],
        created_at=datetime.now(UTC),
    )


@router.post("/universe/run-once", response_model=ControlActionResponse)
def run_universe(payload: ControlActionRequest, db: Session = Depends(get_db)) -> ControlActionResponse:
    worker = UniverseWorker(db)
    details: list[dict[str, object]] = []
    if payload.asset_class in {"all", "stock"}:
        summary = worker.resolve_stock_universe(force=payload.force)
        details.append({"asset_class": summary.asset_class, "source": summary.source, "symbol_count": len(summary.symbols)})
    if payload.asset_class in {"all", "crypto"}:
        summary = worker.resolve_crypto_universe(force=payload.force)
        details.append({"asset_class": summary.asset_class, "source": summary.source, "symbol_count": len(summary.symbols)})
    _create_event(db, event_type="control.universe_run", severity="info", message="Universe refresh executed.", payload={"asset_class": payload.asset_class, "force": payload.force})
    return ControlActionResponse(action="refresh_universe", status="completed", message="Universe refresh completed.", details=details, created_at=datetime.now(UTC))


@router.post("/candles/backfill", response_model=ControlActionResponse)
def backfill_candles(payload: ControlActionRequest, db: Session = Depends(get_db)) -> ControlActionResponse:
    worker = SingleCandleWorker(db)
    settings = get_settings()
    details = _run_candle_action(worker=worker, db=db, payload=payload, mode="backfill", settings=settings)
    _create_event(db, event_type="control.candle_backfill", severity="info", message="Candle backfill executed.", payload={"asset_class": payload.asset_class, "timeframe": payload.timeframe})
    return ControlActionResponse(action="backfill_candles", status="completed", message="Candle backfill completed.", details=details, created_at=datetime.now(UTC))


@router.post("/candles/incremental", response_model=ControlActionResponse)
def sync_incremental_candles(payload: ControlActionRequest, db: Session = Depends(get_db)) -> ControlActionResponse:
    worker = SingleCandleWorker(db)
    settings = get_settings()
    details = _run_candle_action(worker=worker, db=db, payload=payload, mode="incremental", settings=settings)
    _create_event(db, event_type="control.candle_incremental", severity="info", message="Incremental candle sync executed.", payload={"asset_class": payload.asset_class, "timeframe": payload.timeframe})
    return ControlActionResponse(action="sync_incremental_candles", status="completed", message="Incremental candle sync completed.", details=details, created_at=datetime.now(UTC))


@router.post("/regime/run-once", response_model=ControlActionResponse)
def recompute_regime(payload: ControlActionRequest, db: Session = Depends(get_db)) -> ControlActionResponse:
    settings = get_settings()
    feature_worker = FeatureWorker(db, settings=settings)
    worker = RegimeWorker(db, settings=settings)
    details: list[dict[str, object]] = []
    if payload.asset_class in {"all", "stock"}:
        for timeframe in _resolve_requested_timeframes(settings, asset_class="stock", requested_timeframe=payload.timeframe):
            feature_summary = feature_worker.build_stock_features(timeframe=timeframe)
            summary = worker.build_stock_regime(timeframe=timeframe)
            details.append({"asset_class": "stock", "timeframe": timeframe, "computed_features": feature_summary.computed_snapshots, "regime": summary.regime, "entry_policy": summary.entry_policy, "symbol_count": summary.symbol_count})
    if payload.asset_class in {"all", "crypto"}:
        for timeframe in _resolve_requested_timeframes(settings, asset_class="crypto", requested_timeframe=payload.timeframe):
            feature_summary = feature_worker.build_crypto_features(timeframe=timeframe)
            summary = worker.build_crypto_regime(timeframe=timeframe)
            details.append({"asset_class": "crypto", "timeframe": timeframe, "computed_features": feature_summary.computed_snapshots, "regime": summary.regime, "entry_policy": summary.entry_policy, "symbol_count": summary.symbol_count})
    _create_event(db, event_type="control.regime_run", severity="info", message="Regime recompute executed.", payload={"asset_class": payload.asset_class, "timeframe": payload.timeframe})
    return ControlActionResponse(action="recompute_regime", status="completed", message="Regime recompute completed.", details=details, created_at=datetime.now(UTC))


@router.post("/strategy/run-once", response_model=ControlActionResponse)
def refresh_strategies(payload: ControlActionRequest, db: Session = Depends(get_db)) -> ControlActionResponse:
    settings = get_settings()
    feature_worker = FeatureWorker(db, settings=settings)
    regime_worker = RegimeWorker(db, settings=settings)
    strategy_worker = StrategyWorker(db, settings=settings)
    details: list[dict[str, object]] = []
    if payload.asset_class in {"all", "stock"}:
        for timeframe in _resolve_requested_timeframes(settings, asset_class="stock", requested_timeframe=payload.timeframe):
            feature_summary = feature_worker.build_stock_features(timeframe=timeframe)
            regime_summary = regime_worker.build_stock_regime(timeframe=timeframe)
            strategy_summary = strategy_worker.build_stock_candidates(timeframe=timeframe)
            details.append({"asset_class": "stock", "timeframe": timeframe, "computed_features": feature_summary.computed_snapshots, "regime": regime_summary.regime, "entry_policy": regime_summary.entry_policy, "evaluated_rows": strategy_summary.evaluated_rows, "ready_rows": strategy_summary.ready_rows, "blocked_rows": strategy_summary.blocked_rows})
    if payload.asset_class in {"all", "crypto"}:
        for timeframe in _resolve_requested_timeframes(settings, asset_class="crypto", requested_timeframe=payload.timeframe):
            feature_summary = feature_worker.build_crypto_features(timeframe=timeframe)
            regime_summary = regime_worker.build_crypto_regime(timeframe=timeframe)
            strategy_summary = strategy_worker.build_crypto_candidates(timeframe=timeframe)
            details.append({"asset_class": "crypto", "timeframe": timeframe, "computed_features": feature_summary.computed_snapshots, "regime": regime_summary.regime, "entry_policy": regime_summary.entry_policy, "evaluated_rows": strategy_summary.evaluated_rows, "ready_rows": strategy_summary.ready_rows, "blocked_rows": strategy_summary.blocked_rows})
    _create_event(db, event_type="control.strategy_run", severity="info", message="Strategy refresh executed.", payload={"asset_class": payload.asset_class, "timeframe": payload.timeframe})
    return ControlActionResponse(action="refresh_strategies", status="completed", message="Strategy refresh completed.", details=details, created_at=datetime.now(UTC))


@router.post("/flatten/{scope}", response_model=ControlActionResponse)
def request_flatten(scope: str, payload: FlattenRequest, db: Session = Depends(get_db)) -> ControlActionResponse:
    if scope not in {"stocks", "crypto", "all", "stock"}:
        raise HTTPException(status_code=404, detail="Flatten scope not supported")
    details: list[dict[str, object]] = []
    if payload.engage_kill_switch:
        upsert_setting(db, key="controls.kill_switch_enabled", value="true", value_type="bool", description="Master kill switch blocking new entries.")
        details.append({"kill_switch_enabled": True})
    _create_event(db, event_type="control.flatten_requested", severity="warning", message=f"Manual flatten requested for {scope}.", payload={"scope": scope, "engage_kill_switch": payload.engage_kill_switch, "note": payload.note, "status": "manual_follow_up_required"})
    create_audit_event(db, event_type="audit.flatten_requested", severity="warning", message=f"Operator requested manual flatten for {scope}.", payload={"scope": scope, "engage_kill_switch": payload.engage_kill_switch, "note": payload.note, "status": "manual_follow_up_required"})
    db.commit()
    return ControlActionResponse(action=f"flatten_{scope}", status="queued_manual_action", message="Flatten request recorded. Kill switch engaged when requested. Automated broker liquidation is not implemented in this phase.", details=details, created_at=datetime.now(UTC))


def _run_candle_action(*, worker: SingleCandleWorker, db: Session, payload: ControlActionRequest, mode: str, settings) -> list[dict[str, object]]:
    trade_date = trading_date_for_now(None)
    details: list[dict[str, object]] = []
    requests: list[tuple[str, str, list[str]]] = []
    if payload.asset_class in {"all", "stock"}:
        stock_symbols = payload.symbols or [row.symbol for row in list_universe_symbols(db, asset_class="stock", trade_date=trade_date)]
        for timeframe in _resolve_requested_timeframes(settings, asset_class="stock", requested_timeframe=payload.timeframe):
            requests.append(("stock", timeframe, stock_symbols))
    if payload.asset_class in {"all", "crypto"}:
        crypto_symbols = payload.symbols or [row.symbol for row in list_universe_symbols(db, asset_class="crypto", trade_date=trade_date)]
        for timeframe in _resolve_requested_timeframes(settings, asset_class="crypto", requested_timeframe=payload.timeframe):
            requests.append(("crypto", timeframe, crypto_symbols))

    for asset_class, timeframe, symbols in requests:
        if asset_class == "stock":
            summary = worker.sync_stock_backfill(symbols=symbols, timeframe=timeframe) if mode == "backfill" else worker.sync_stock_incremental(symbols=symbols, timeframe=timeframe)
        else:
            summary = worker.sync_crypto_backfill(symbols=symbols, timeframe=timeframe) if mode == "backfill" else worker.sync_crypto_incremental(symbols=symbols, timeframe=timeframe)
        details.append({"asset_class": asset_class, "timeframe": timeframe, "requested_symbols": len(summary.requested_symbols), "upserted_bars": summary.upserted_bars, "skipped_reason": summary.skipped_reason})
    return details


def _resolve_requested_timeframes(settings, *, asset_class: str, requested_timeframe: str | None) -> list[str]:
    if requested_timeframe:
        return [requested_timeframe]
    configured = settings.stock_feature_timeframe_list if asset_class == "stock" else settings.crypto_feature_timeframe_list
    return list(configured or ["1h"])


def _setting_to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _create_event(db: Session, *, event_type: str, severity: str, message: str, payload: dict[str, object] | None = None) -> None:
    create_system_event(db, event_type=event_type, severity=severity, message=message, event_source="frontend_controls", payload=payload, commit=True)
