from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import log, sqrt
from statistics import fmean
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.common.adapters.models import OrderBookLevel, OrderBookSnapshot
from backend.app.core.config import get_settings
from backend.app.crypto.data.defillama_enrichment import DefiLlamaMarketSnapshot, DefiLlamaMetricsAdapter
from backend.app.crypto.data.kraken_orderbook import KrakenOrderBookAdapter
from backend.app.models.core import (
    CiCryptoRegimeFeatureSnapshot,
    CiCryptoRegimeModelRegistry,
    CiCryptoRegimeOrderbookSnapshot,
    CiCryptoRegimeRun,
    CiCryptoRegimeState,
    Candle,
    FeatureSnapshot,
    RegimeSnapshot,
)
from backend.app.services.candle_service import ensure_utc
from backend.app.services.operator_service import create_system_event
from backend.app.services.regime_service import get_latest_regime_snapshot
from backend.app.services.settings_service import resolve_bool_setting, resolve_int_setting, resolve_str_setting
from backend.app.services.universe_service import list_universe_symbols, trading_date_for_now

CI_FEATURE_SET_VERSION = "ci_crypto_regime_feature_set_v1"
CI_DEFAULT_MODEL_VERSION = "ci_rules_v1"
CI_EVENT_SOURCE = "ci_crypto_regime_worker"
CI_ALLOWED_STATES = {"bull", "neutral", "risk_off", "unavailable"}
CI_ALLOWED_ACTIONS = {"allow", "tighten", "block", "ignore"}
CI_ORDERBOOK_SYMBOLS = ("XBTUSD", "ETHUSD")
CI_BASE_FEATURE_CONTRACT = (
    "btc_trend_4h",
    "btc_trend_1h",
    "eth_trend_4h",
    "eth_trend_1h",
    "crypto_breadth_pct_above_ma",
    "crypto_realized_vol_1h",
    "crypto_realized_vol_4h",
    "btc_return_z_1h",
    "eth_return_z_1h",
)
CI_ORDERBOOK_FEATURE_CONTRACT = (
    "btc_spread_bps",
    "btc_top10_imbalance",
    "btc_top25_depth_usd",
    "btc_sweep_cost_buy_5k_bps",
    "btc_sweep_cost_sell_5k_bps",
    "eth_spread_bps",
    "eth_top10_imbalance",
    "eth_top25_depth_usd",
    "eth_sweep_cost_buy_5k_bps",
    "eth_sweep_cost_sell_5k_bps",
    "microstructure_support_score",
)
CI_DEFILLAMA_FEATURE_CONTRACT = (
    "market_funding_bias",
    "market_open_interest_z",
    "market_oi_change_24h",
    "market_defi_tvl_change_24h",
)
CI_DEFILLAMA_AUDIT_FEATURES = (
    "market_open_interest_total",
    "market_total_defi_tvl",
)
CI_HURST_FEATURE_CONTRACT = (
    "btc_hurst_4h",
    "btc_hurst_1h",
    "eth_hurst_4h",
    "eth_hurst_1h",
)


@dataclass(slots=True, frozen=True)
class CiCryptoRegimeSettings:
    enabled: bool
    advisory_only: bool
    model_version: str
    mode: str
    use_orderbook: bool
    use_defillama: bool
    use_hurst: bool
    run_interval_minutes: int
    stale_after_seconds: int
    min_bars_4h: int
    min_bars_1h: int
    min_book_snapshots: int
    promote_to_runtime: bool


@dataclass(slots=True, frozen=True)
class CiCryptoRegimeRunSummary:
    run_id: int | None
    status: str
    state: str | None
    confidence: float | None
    degraded: bool
    skipped_reason: str | None = None
    agreement_with_core: str | None = None
    advisory_action: str | None = None
    model_version: str | None = None


@dataclass(slots=True, frozen=True)
class _FeatureValue:
    feature_name: str
    feature_value: float | None
    feature_status: str
    source: str
    symbol_scope: str
    timeframe: str | None
    as_of_at: datetime | None


@dataclass(slots=True, frozen=True)
class _OrderbookSnapshotInput:
    venue: str
    symbol: str
    bid_levels: int
    ask_levels: int
    best_bid: float | None
    best_ask: float | None
    spread_bps: float | None
    top10_imbalance: float | None
    top25_depth_usd: float | None
    sweep_cost_buy_5k_bps: float | None
    sweep_cost_sell_5k_bps: float | None
    as_of_at: datetime | None
    payload_json: dict[str, Any] | None


@dataclass(slots=True, frozen=True)
class _OrderbookCollection:
    feature_values: list[_FeatureValue]
    snapshots: list[_OrderbookSnapshotInput]
    status: str
    ready: bool
    used: bool
    degraded_reasons: list[str]


@dataclass(slots=True, frozen=True)
class _FeatureCollection:
    feature_values: list[_FeatureValue]
    status: str
    ready: bool
    used: bool
    degraded_reasons: list[str]
    summary: dict[str, Any]


@dataclass(slots=True, frozen=True)
class _InferenceInputs:
    universe_symbols: tuple[str, ...]
    latest_core_regime: RegimeSnapshot | None
    feature_rows_1h: list[FeatureSnapshot]
    feature_rows_4h: list[FeatureSnapshot]
    feature_values: list[_FeatureValue]
    orderbook_snapshots: list[_OrderbookSnapshotInput]
    orderbook_status: str
    orderbook_ready: bool
    orderbook_used: bool
    defillama_status: str
    defillama_ready: bool
    defillama_used: bool
    hurst_status: str
    hurst_ready: bool
    hurst_used: bool
    degraded_reasons: list[str]
    stale: bool
    newest_feature_at: datetime | None
    oldest_required_feature_at: datetime | None


@dataclass(slots=True, frozen=True)
class _ComputedInference:
    state: str
    confidence: float
    degraded: bool
    agreement_with_core: str
    advisory_action: str
    cluster_id: int | None
    cluster_prob_bull: float | None
    cluster_prob_neutral: float | None
    cluster_prob_risk_off: float | None
    reason_codes: list[str]
    summary: dict[str, Any]


def resolve_ci_crypto_regime_settings(db: Session) -> CiCryptoRegimeSettings:
    return CiCryptoRegimeSettings(
        enabled=resolve_bool_setting(db, "CI_CRYPTO_REGIME_ENABLED", default=False),
        advisory_only=resolve_bool_setting(db, "CI_CRYPTO_REGIME_ADVISORY_ONLY", default=True),
        model_version=resolve_str_setting(db, "CI_CRYPTO_REGIME_MODEL_VERSION", default=CI_DEFAULT_MODEL_VERSION),
        mode=resolve_str_setting(db, "CI_CRYPTO_REGIME_MODE", default="rules_only"),
        use_orderbook=resolve_bool_setting(db, "CI_CRYPTO_REGIME_USE_ORDERBOOK", default=True),
        use_defillama=resolve_bool_setting(db, "CI_CRYPTO_REGIME_USE_DEFILLAMA", default=False),
        use_hurst=resolve_bool_setting(db, "CI_CRYPTO_REGIME_USE_HURST", default=True),
        run_interval_minutes=resolve_int_setting(db, "CI_CRYPTO_REGIME_RUN_INTERVAL_MINUTES", default=15),
        stale_after_seconds=resolve_int_setting(db, "CI_CRYPTO_REGIME_STALE_AFTER_SECONDS", default=1200),
        min_bars_4h=resolve_int_setting(db, "CI_CRYPTO_REGIME_MIN_BARS_4H", default=120),
        min_bars_1h=resolve_int_setting(db, "CI_CRYPTO_REGIME_MIN_BARS_1H", default=240),
        min_book_snapshots=resolve_int_setting(db, "CI_CRYPTO_REGIME_MIN_BOOK_SNAPSHOTS", default=20),
        promote_to_runtime=resolve_bool_setting(db, "CI_CRYPTO_REGIME_PROMOTE_TO_RUNTIME", default=False),
    )


def ensure_default_ci_model_registry(
    db: Session,
    *,
    settings: CiCryptoRegimeSettings | None = None,
    commit: bool = False,
) -> CiCryptoRegimeModelRegistry:
    runtime = settings or resolve_ci_crypto_regime_settings(db)
    record = (
        db.query(CiCryptoRegimeModelRegistry)
        .filter(CiCryptoRegimeModelRegistry.model_version == runtime.model_version)
        .one_or_none()
    )
    if record is None:
        record = CiCryptoRegimeModelRegistry(
            model_version=runtime.model_version,
            feature_set_version=CI_FEATURE_SET_VERSION,
            scaler_version=None,
            model_type=runtime.mode,
            label_map_json={
                "rules_only": {
                    "bull": "bull",
                    "neutral": "neutral",
                    "risk_off": "risk_off",
                }
            },
            training_notes="Auto-registered default advisory rules model for CI crypto regime v1.",
            is_active=True,
            created_by="system",
        )
        db.add(record)
    else:
        record.feature_set_version = CI_FEATURE_SET_VERSION
        record.model_type = runtime.mode
        record.is_active = True
        if record.label_map_json is None:
            record.label_map_json = {
                "rules_only": {
                    "bull": "bull",
                    "neutral": "neutral",
                    "risk_off": "risk_off",
                }
            }
    db.flush()
    if commit:
        db.commit()
        db.refresh(record)
    return record


def list_ci_crypto_regime_models(db: Session) -> list[CiCryptoRegimeModelRegistry]:
    return (
        db.query(CiCryptoRegimeModelRegistry)
        .order_by(CiCryptoRegimeModelRegistry.is_active.desc(), CiCryptoRegimeModelRegistry.created_at.desc())
        .all()
    )


def get_ci_crypto_regime_run(db: Session, *, run_id: int) -> CiCryptoRegimeRun | None:
    return db.query(CiCryptoRegimeRun).filter(CiCryptoRegimeRun.id == run_id).one_or_none()


def get_latest_ci_crypto_regime_run(db: Session) -> CiCryptoRegimeRun | None:
    return db.query(CiCryptoRegimeRun).order_by(CiCryptoRegimeRun.run_started_at.desc(), CiCryptoRegimeRun.id.desc()).first()


def get_latest_ci_crypto_regime_state(db: Session) -> CiCryptoRegimeState | None:
    return (
        db.query(CiCryptoRegimeState)
        .order_by(CiCryptoRegimeState.as_of_at.desc(), CiCryptoRegimeState.id.desc())
        .first()
    )


def list_ci_crypto_regime_history(
    db: Session,
    *,
    limit: int = 100,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    state: str | None = None,
    agreement_with_core: str | None = None,
) -> list[CiCryptoRegimeState]:
    query = db.query(CiCryptoRegimeState)
    if from_at is not None:
        query = query.filter(CiCryptoRegimeState.as_of_at >= ensure_utc(from_at))
    if to_at is not None:
        query = query.filter(CiCryptoRegimeState.as_of_at <= ensure_utc(to_at))
    if state:
        query = query.filter(CiCryptoRegimeState.state == state)
    if agreement_with_core:
        query = query.filter(CiCryptoRegimeState.agreement_with_core == agreement_with_core)
    return query.order_by(CiCryptoRegimeState.as_of_at.desc(), CiCryptoRegimeState.id.desc()).limit(limit).all()


def build_ci_crypto_regime_current_snapshot(db: Session) -> dict[str, Any] | None:
    state = get_latest_ci_crypto_regime_state(db)
    if state is None:
        return None
    settings = resolve_ci_crypto_regime_settings(db)
    ensure_default_ci_model_registry(db, settings=settings)
    db.flush()
    latest_core = _latest_core_regime_for_display(db)
    summary = state.summary_json or {}
    run = state.run or get_latest_ci_crypto_regime_run(db)
    return {
        "enabled": settings.enabled,
        "advisory_only": settings.advisory_only,
        "as_of_at": state.as_of_at,
        "state": state.state,
        "confidence": state.confidence,
        "core_regime_state": state.core_regime_state,
        "agreement_with_core": state.agreement_with_core,
        "advisory_action": state.advisory_action,
        "model_version": run.model_version if run else settings.model_version,
        "feature_set_version": run.feature_set_version if run else CI_FEATURE_SET_VERSION,
        "degraded": state.degraded,
        "reason_codes": list(state.reason_codes_json or []),
        "summary": summary,
        "core_regime_timeframe": latest_core.timeframe if latest_core else None,
        "last_run_status": run.status if run else None,
        "last_run_started_at": run.run_started_at if run else None,
        "last_run_completed_at": run.run_completed_at if run else None,
        "last_run_used_orderbook": bool(run.used_orderbook) if run else False,
        "last_run_used_defillama": bool(run.used_defillama) if run else False,
        "last_run_used_hurst": bool(run.used_hurst) if run else False,
        "orderbook_status": summary.get("orderbook_status"),
        "orderbook_ready": bool(summary.get("orderbook_ready", False)),
        "defillama_status": summary.get("defillama_status"),
        "defillama_ready": bool(summary.get("defillama_ready", False)),
        "hurst_status": summary.get("hurst_status"),
        "hurst_ready": bool(summary.get("hurst_ready", False)),
        "degraded_reasons": list(summary.get("degraded_reasons", [])),
    }


def build_ci_crypto_regime_runtime_status(db: Session) -> dict[str, Any]:
    settings = resolve_ci_crypto_regime_settings(db)
    current = build_ci_crypto_regime_current_snapshot(db)
    return {
        "enabled": settings.enabled,
        "advisory_only": settings.advisory_only,
        "model_version": settings.model_version,
        "mode": settings.mode,
        "use_orderbook": settings.use_orderbook,
        "use_defillama": settings.use_defillama,
        "use_hurst": settings.use_hurst,
        "promote_to_runtime": settings.promote_to_runtime,
        "run_interval_minutes": settings.run_interval_minutes,
        "stale_after_seconds": settings.stale_after_seconds,
        "state": current.get("state") if current else None,
        "confidence": current.get("confidence") if current else None,
        "agreement_with_core": current.get("agreement_with_core") if current else None,
        "advisory_action": current.get("advisory_action") if current else None,
        "core_regime_state": current.get("core_regime_state") if current else None,
        "core_regime_timeframe": current.get("core_regime_timeframe") if current else None,
        "degraded": bool(current.get("degraded", False)) if current else False,
        "last_run_status": current.get("last_run_status") if current else None,
        "last_run_started_at": current.get("last_run_started_at") if current else None,
        "last_run_completed_at": current.get("last_run_completed_at") if current else None,
        "last_run_used_orderbook": bool(current.get("last_run_used_orderbook", False)) if current else False,
        "last_run_used_defillama": bool(current.get("last_run_used_defillama", False)) if current else False,
        "last_run_used_hurst": bool(current.get("last_run_used_hurst", False)) if current else False,
        "orderbook_status": current.get("orderbook_status") if current else None,
        "orderbook_ready": bool(current.get("orderbook_ready", False)) if current else False,
        "defillama_status": current.get("defillama_status") if current else None,
        "defillama_ready": bool(current.get("defillama_ready", False)) if current else False,
        "hurst_status": current.get("hurst_status") if current else None,
        "hurst_ready": bool(current.get("hurst_ready", False)) if current else False,
        "degraded_reasons": list(current.get("degraded_reasons", [])) if current else [],
    }


def build_ci_crypto_regime_run_detail(db: Session, *, run_id: int) -> dict[str, Any] | None:
    run = get_ci_crypto_regime_run(db, run_id=run_id)
    if run is None:
        return None
    state = run.state
    feature_rows = (
        db.query(CiCryptoRegimeFeatureSnapshot)
        .filter(CiCryptoRegimeFeatureSnapshot.run_id == run.id)
        .order_by(CiCryptoRegimeFeatureSnapshot.timeframe.asc(), CiCryptoRegimeFeatureSnapshot.feature_name.asc())
        .all()
    )
    orderbook_rows = (
        db.query(CiCryptoRegimeOrderbookSnapshot)
        .filter(CiCryptoRegimeOrderbookSnapshot.run_id == run.id)
        .order_by(CiCryptoRegimeOrderbookSnapshot.symbol.asc(), CiCryptoRegimeOrderbookSnapshot.id.asc())
        .all()
    )
    return {
        "run": run,
        "state": state,
        "features": feature_rows,
        "orderbook_snapshots": orderbook_rows,
    }


def run_ci_crypto_regime_advisory(
    db: Session,
    *,
    now: datetime | None = None,
    orderbook_fetcher: Callable[[str, int], OrderBookSnapshot] | None = None,
    defillama_snapshot_fetcher: Callable[[], DefiLlamaMarketSnapshot] | None = None,
) -> CiCryptoRegimeRunSummary:
    runtime = resolve_ci_crypto_regime_settings(db)
    run_time = ensure_utc(now) or datetime.now(UTC)

    if not runtime.enabled:
        run = _create_run(
            db,
            run_time=run_time,
            status="skipped",
            skip_reason="disabled",
            settings=runtime,
            degraded=False,
            used_orderbook=False,
            used_defillama=False,
            used_hurst=False,
            data_window_end_at=run_time,
        )
        _emit_worker_event(
            db,
            event_type="ci_crypto_regime.run_skipped",
            severity="info",
            message="CI crypto regime advisory run skipped because the add-on is disabled.",
            payload={"run_id": run.id, "skip_reason": "disabled"},
        )
        db.commit()
        return CiCryptoRegimeRunSummary(
            run_id=run.id,
            status="skipped",
            state=None,
            confidence=None,
            degraded=False,
            skipped_reason="disabled",
            model_version=runtime.model_version,
        )

    model = ensure_default_ci_model_registry(db, settings=runtime)
    if runtime.mode != "rules_only" and model.model_version != runtime.model_version:
        run = _create_run(
            db,
            run_time=run_time,
            status="skipped",
            skip_reason="model_not_registered",
            settings=runtime,
            degraded=False,
            used_orderbook=False,
            used_defillama=False,
            used_hurst=False,
            data_window_end_at=run_time,
        )
        _emit_worker_event(
            db,
            event_type="ci_crypto_regime.model_mismatch",
            severity="warning",
            message="CI crypto regime advisory run skipped because the configured model is not registered.",
            payload={"run_id": run.id, "model_version": runtime.model_version},
        )
        db.commit()
        return CiCryptoRegimeRunSummary(
            run_id=run.id,
            status="skipped",
            state=None,
            confidence=None,
            degraded=False,
            skipped_reason="model_not_registered",
            model_version=runtime.model_version,
        )

    _emit_worker_event(
        db,
        event_type="ci_crypto_regime.run_started",
        severity="info",
        message="CI crypto regime advisory run started.",
        payload={"model_version": model.model_version, "mode": runtime.mode, "advisory_only": runtime.advisory_only},
    )

    inputs = _collect_inference_inputs(
        db,
        runtime=runtime,
        run_time=run_time,
        orderbook_fetcher=orderbook_fetcher,
        defillama_snapshot_fetcher=defillama_snapshot_fetcher,
    )
    if inputs is not None:
        _emit_worker_event(
            db,
            event_type="ci_crypto_regime.features_built",
            severity="info",
            message="CI crypto regime advisory feature inputs were collected.",
            payload={
                "orderbook_status": inputs.orderbook_status,
                "defillama_status": inputs.defillama_status,
                "hurst_status": inputs.hurst_status,
                "degraded_reasons": inputs.degraded_reasons,
            },
        )
    if inputs is None:
        run = _create_run(
            db,
            run_time=run_time,
            status="skipped",
            skip_reason="core_regime_not_ready",
            settings=runtime,
            degraded=False,
            used_orderbook=False,
            used_defillama=False,
            used_hurst=False,
            data_window_end_at=run_time,
        )
        _emit_worker_event(
            db,
            event_type="ci_crypto_regime.run_skipped",
            severity="warning",
            message="CI crypto regime advisory run skipped because the core crypto regime is not ready.",
            payload={"run_id": run.id, "skip_reason": "core_regime_not_ready"},
        )
        db.commit()
        return CiCryptoRegimeRunSummary(
            run_id=run.id,
            status="skipped",
            state=None,
            confidence=None,
            degraded=False,
            skipped_reason="core_regime_not_ready",
            model_version=model.model_version,
        )

    if len(inputs.feature_rows_1h) < max(2, len(inputs.universe_symbols)) or len(inputs.feature_rows_4h) < 2:
        run = _create_run(
            db,
            run_time=run_time,
            status="skipped",
            skip_reason="missing_history",
            settings=runtime,
            degraded=False,
            used_orderbook=False,
            used_defillama=False,
            used_hurst=False,
            data_window_end_at=inputs.newest_feature_at or run_time,
        )
        _write_feature_rows(db, run_id=run.id, feature_values=inputs.feature_values)
        _write_orderbook_rows(db, run_id=run.id, snapshots=inputs.orderbook_snapshots)
        _emit_worker_event(
            db,
            event_type="ci_crypto_regime.run_skipped",
            severity="warning",
            message="CI crypto regime advisory run skipped because required crypto history is missing.",
            payload={"run_id": run.id, "skip_reason": "missing_history"},
        )
        db.commit()
        return CiCryptoRegimeRunSummary(
            run_id=run.id,
            status="skipped",
            state=None,
            confidence=None,
            degraded=False,
            skipped_reason="missing_history",
            model_version=model.model_version,
        )

    computed = _compute_rules_inference(inputs=inputs, runtime=runtime)
    status = "partial" if computed.degraded else "success"
    run = _create_run(
        db,
        run_time=run_time,
        status=status,
        skip_reason=None,
        settings=runtime,
        degraded=computed.degraded,
        used_orderbook=inputs.orderbook_used,
        used_defillama=inputs.defillama_used,
        used_hurst=inputs.hurst_used,
        data_window_end_at=inputs.newest_feature_at or run_time,
    )
    _write_feature_rows(db, run_id=run.id, feature_values=inputs.feature_values)
    _write_orderbook_rows(db, run_id=run.id, snapshots=inputs.orderbook_snapshots)
    state = _upsert_ci_state(
        db,
        run_id=run.id,
        as_of_at=inputs.newest_feature_at or run_time,
        computed=computed,
        core_regime_state=inputs.latest_core_regime.regime if inputs.latest_core_regime else None,
    )

    event_type = "ci_crypto_regime.inference_complete" if status == "success" else "ci_crypto_regime.run_degraded"
    severity = "info" if status == "success" else "warning"
    message = (
        "CI crypto regime advisory inference completed."
        if status == "success"
        else "CI crypto regime advisory inference completed in degraded mode."
    )
    _emit_worker_event(
        db,
        event_type=event_type,
        severity=severity,
        message=message,
        payload={
            "run_id": run.id,
            "status": status,
            "state": state.state,
            "confidence": float(state.confidence),
            "agreement_with_core": state.agreement_with_core,
            "advisory_action": state.advisory_action,
            "degraded": state.degraded,
            "used_orderbook": run.used_orderbook,
            "used_defillama": run.used_defillama,
            "used_hurst": run.used_hurst,
            "orderbook_status": computed.summary.get("orderbook_status"),
            "defillama_status": computed.summary.get("defillama_status"),
            "hurst_status": computed.summary.get("hurst_status"),
        },
    )
    db.commit()
    return CiCryptoRegimeRunSummary(
        run_id=run.id,
        status=status,
        state=state.state,
        confidence=float(state.confidence),
        degraded=state.degraded,
        skipped_reason=None,
        agreement_with_core=state.agreement_with_core,
        advisory_action=state.advisory_action,
        model_version=model.model_version,
    )


def _collect_inference_inputs(
    db: Session,
    *,
    runtime: CiCryptoRegimeSettings,
    run_time: datetime,
    orderbook_fetcher: Callable[[str, int], OrderBookSnapshot] | None,
    defillama_snapshot_fetcher: Callable[[], DefiLlamaMarketSnapshot] | None,
) -> _InferenceInputs | None:
    core_regime = get_latest_regime_snapshot(db, asset_class="crypto", timeframe="1h")
    if core_regime is None:
        core_regime = get_latest_regime_snapshot(db, asset_class="crypto", timeframe="4h")
    if core_regime is None:
        return None

    trade_date = trading_date_for_now(run_time)
    universe_symbols = tuple(item.symbol for item in list_universe_symbols(db, asset_class="crypto", trade_date=trade_date))
    feature_rows_1h = [
        row
        for row in (_latest_feature_snapshot(db, symbol=symbol, timeframe="1h") for symbol in universe_symbols)
        if row is not None
    ]
    feature_rows_4h = [
        row
        for row in (_latest_feature_snapshot(db, symbol=symbol, timeframe="4h") for symbol in universe_symbols)
        if row is not None
    ]

    newest_times = [ensure_utc(row.candle_timestamp) for row in [*feature_rows_1h, *feature_rows_4h] if ensure_utc(row.candle_timestamp) is not None]
    newest_feature_at = max(newest_times) if newest_times else None
    oldest_required_feature_at = min(newest_times) if newest_times else None
    stale_cutoff = run_time - timedelta(seconds=max(60, runtime.stale_after_seconds))
    stale = bool(newest_feature_at is None or newest_feature_at < stale_cutoff)

    feature_values = _build_feature_values(feature_rows_1h=feature_rows_1h, feature_rows_4h=feature_rows_4h, run_time=run_time)
    orderbook = _collect_orderbook_inputs(db, runtime=runtime, run_time=run_time, orderbook_fetcher=orderbook_fetcher)
    defillama = _collect_defillama_inputs(
        db,
        runtime=runtime,
        run_time=run_time,
        snapshot_fetcher=defillama_snapshot_fetcher,
    )
    hurst = _collect_hurst_inputs(db, runtime=runtime, run_time=run_time)
    feature_values.extend(orderbook.feature_values)
    feature_values.extend(defillama.feature_values)
    feature_values.extend(hurst.feature_values)
    degraded_reasons = sorted(set([*orderbook.degraded_reasons, *defillama.degraded_reasons, *hurst.degraded_reasons]))

    return _InferenceInputs(
        universe_symbols=universe_symbols,
        latest_core_regime=core_regime,
        feature_rows_1h=feature_rows_1h,
        feature_rows_4h=feature_rows_4h,
        feature_values=feature_values,
        orderbook_snapshots=orderbook.snapshots,
        orderbook_status=orderbook.status,
        orderbook_ready=orderbook.ready,
        orderbook_used=orderbook.used,
        defillama_status=defillama.status,
        defillama_ready=defillama.ready,
        defillama_used=defillama.used,
        hurst_status=hurst.status,
        hurst_ready=hurst.ready,
        hurst_used=hurst.used,
        degraded_reasons=degraded_reasons,
        stale=stale,
        newest_feature_at=newest_feature_at,
        oldest_required_feature_at=oldest_required_feature_at,
    )


def _build_feature_values(
    *,
    feature_rows_1h: list[FeatureSnapshot],
    feature_rows_4h: list[FeatureSnapshot],
    run_time: datetime,
) -> list[_FeatureValue]:
    row_1h_by_symbol = {row.symbol: row for row in feature_rows_1h}
    row_4h_by_symbol = {row.symbol: row for row in feature_rows_4h}
    btc_1h = row_1h_by_symbol.get("XBTUSD")
    btc_4h = row_4h_by_symbol.get("XBTUSD")
    eth_1h = row_1h_by_symbol.get("ETHUSD")
    eth_4h = row_4h_by_symbol.get("ETHUSD")

    breadth = _share([row for row in feature_rows_1h if row.sma_20 is not None], lambda row: float(row.close) >= float(row.sma_20))
    vol_1h = _mean_optional([_safe_float(row.realized_volatility_20) for row in feature_rows_1h])
    vol_4h = _mean_optional([_safe_float(row.realized_volatility_20) for row in feature_rows_4h])
    z_scores = _return_z_scores(feature_rows_1h)

    return [
        _feature_value("btc_trend_4h", _trend_flag(btc_4h), "derived", "XBTUSD", "4h", btc_4h.candle_timestamp if btc_4h else None),
        _feature_value("btc_trend_1h", _trend_flag(btc_1h), "derived", "XBTUSD", "1h", btc_1h.candle_timestamp if btc_1h else None),
        _feature_value("eth_trend_4h", _trend_flag(eth_4h), "derived", "ETHUSD", "4h", eth_4h.candle_timestamp if eth_4h else None),
        _feature_value("eth_trend_1h", _trend_flag(eth_1h), "derived", "ETHUSD", "1h", eth_1h.candle_timestamp if eth_1h else None),
        _feature_value(
            "crypto_breadth_pct_above_ma",
            breadth,
            "internal",
            "market",
            "1h",
            run_time if breadth is None else max((ensure_utc(row.candle_timestamp) or run_time) for row in feature_rows_1h) if feature_rows_1h else run_time,
        ),
        _feature_value(
            "crypto_realized_vol_1h",
            vol_1h,
            "internal",
            "market",
            "1h",
            run_time if vol_1h is None else max((ensure_utc(row.candle_timestamp) or run_time) for row in feature_rows_1h) if feature_rows_1h else run_time,
        ),
        _feature_value(
            "crypto_realized_vol_4h",
            vol_4h,
            "internal",
            "market",
            "4h",
            run_time if vol_4h is None else max((ensure_utc(row.candle_timestamp) or run_time) for row in feature_rows_4h) if feature_rows_4h else run_time,
        ),
        _feature_value("btc_return_z_1h", z_scores.get("XBTUSD"), "derived", "XBTUSD", "1h", btc_1h.candle_timestamp if btc_1h else None),
        _feature_value("eth_return_z_1h", z_scores.get("ETHUSD"), "derived", "ETHUSD", "1h", eth_1h.candle_timestamp if eth_1h else None),
    ]


def _collect_defillama_inputs(
    db: Session,
    *,
    runtime: CiCryptoRegimeSettings,
    run_time: datetime,
    snapshot_fetcher: Callable[[], DefiLlamaMarketSnapshot] | None,
) -> _FeatureCollection:
    if not runtime.use_defillama:
        return _FeatureCollection(feature_values=[], status="disabled", ready=False, used=False, degraded_reasons=[], summary={})

    adapter: DefiLlamaMetricsAdapter | None = None
    fetcher = snapshot_fetcher
    if fetcher is None:
        adapter = DefiLlamaMetricsAdapter()
        fetcher = adapter.fetch_market_snapshot

    try:
        assert fetcher is not None
        snapshot = fetcher()
    except Exception as exc:  # pragma: no cover - exercised through runtime fallback/tests via injected failure
        _emit_worker_event(
            db,
            event_type="ci_crypto_regime.defillama_unavailable",
            severity="warning",
            message="DeFiLlama enrichment was unavailable for the CI crypto regime advisory run.",
            payload={"error": f"{type(exc).__name__}: {exc}"},
        )
        return _FeatureCollection(
            feature_values=_missing_named_features(CI_DEFILLAMA_FEATURE_CONTRACT + CI_DEFILLAMA_AUDIT_FEATURES, source="defillama", symbol_scope="market", as_of_at=run_time),
            status="unavailable",
            ready=False,
            used=False,
            degraded_reasons=["defillama_unavailable"],
            summary={},
        )
    finally:
        if adapter is not None:
            adapter.close()

    open_interest_total = snapshot.open_interest_total
    funding_bias = snapshot.funding_bias
    total_tvl = snapshot.defi_tvl_total
    oi_z = _rolling_feature_zscore(db, feature_name="market_open_interest_total", current_value=open_interest_total)
    if oi_z is None and snapshot.derivatives_change_1d is not None:
        oi_z = round(max(-3.0, min(3.0, snapshot.derivatives_change_1d / 10.0)), 6)
    oi_change = _feature_change_pct(
        db,
        feature_name="market_open_interest_total",
        current_value=open_interest_total,
        as_of_at=snapshot.as_of_at,
        lookback_hours=24,
    )
    if oi_change is None:
        oi_change = snapshot.derivatives_change_1d
    tvl_change = _pct_change(current=total_tvl, previous=snapshot.defi_tvl_prev_24h)

    feature_values = [
        _feature_value("market_funding_bias", funding_bias, "defillama", "market", None, snapshot.as_of_at),
        _feature_value("market_open_interest_z", oi_z, "defillama", "market", None, snapshot.as_of_at),
        _feature_value("market_oi_change_24h", oi_change, "defillama", "market", None, snapshot.as_of_at),
        _feature_value("market_defi_tvl_change_24h", tvl_change, "defillama", "market", None, snapshot.as_of_at),
        _feature_value("market_open_interest_total", open_interest_total, "defillama", "market", None, snapshot.as_of_at),
        _feature_value("market_total_defi_tvl", total_tvl, "defillama", "market", None, snapshot.as_of_at),
    ]

    contract_values = {item.feature_name: item.feature_value for item in feature_values if item.feature_name in CI_DEFILLAMA_FEATURE_CONTRACT}
    degraded_reasons: list[str] = []
    if contract_values["market_open_interest_z"] is None:
        degraded_reasons.append("defillama_oi_history_warmup")
    if any(contract_values[name] is None for name in ("market_funding_bias", "market_oi_change_24h", "market_defi_tvl_change_24h")):
        degraded_reasons.append("defillama_partial")

    ready = all(contract_values[name] is not None for name in CI_DEFILLAMA_FEATURE_CONTRACT)
    if ready:
        status = "ready"
    elif funding_bias is None and total_tvl is None and open_interest_total is None:
        status = "unavailable"
    elif open_interest_total is not None or total_tvl is not None or funding_bias is not None:
        status = "warming" if "defillama_oi_history_warmup" in degraded_reasons else "partial"
    else:
        status = "unavailable"
    return _FeatureCollection(
        feature_values=feature_values,
        status=status,
        ready=ready,
        used=ready,
        degraded_reasons=sorted(set(degraded_reasons)) if not ready else [],
        summary={"raw": snapshot.raw},
    )


def _collect_hurst_inputs(
    db: Session,
    *,
    runtime: CiCryptoRegimeSettings,
    run_time: datetime,
) -> _FeatureCollection:
    if not runtime.use_hurst:
        return _FeatureCollection(feature_values=[], status="disabled", ready=False, used=False, degraded_reasons=[], summary={})

    feature_values: list[_FeatureValue] = []
    availability: list[bool] = []
    for symbol, timeframe, required_bars, feature_name in (
        ("XBTUSD", "4h", max(64, runtime.min_bars_4h), "btc_hurst_4h"),
        ("XBTUSD", "1h", max(64, runtime.min_bars_1h), "btc_hurst_1h"),
        ("ETHUSD", "4h", max(64, runtime.min_bars_4h), "eth_hurst_4h"),
        ("ETHUSD", "1h", max(64, runtime.min_bars_1h), "eth_hurst_1h"),
    ):
        rows = _recent_candles(db, symbol=symbol, timeframe=timeframe, limit=required_bars)
        hurst = _hurst_exponent([float(row.close) for row in rows]) if len(rows) >= required_bars else None
        as_of_at = rows[-1].timestamp if rows else run_time
        feature_values.append(_feature_value(feature_name, hurst, "derived", symbol, timeframe, as_of_at))
        availability.append(hurst is not None)

    ready = all(availability) and bool(availability)
    if ready:
        status = "ready"
        degraded_reasons: list[str] = []
    elif any(availability):
        status = "partial"
        degraded_reasons = ["hurst_partial"]
    else:
        status = "warming"
        degraded_reasons = ["hurst_unavailable"]
    return _FeatureCollection(
        feature_values=feature_values,
        status=status,
        ready=ready,
        used=ready,
        degraded_reasons=degraded_reasons,
        summary={},
    )


def _collect_orderbook_inputs(
    db: Session,
    *,
    runtime: CiCryptoRegimeSettings,
    run_time: datetime,
    orderbook_fetcher: Callable[[str, int], OrderBookSnapshot] | None,
) -> _OrderbookCollection:
    if not runtime.use_orderbook:
        return _OrderbookCollection(feature_values=[], snapshots=[], status="disabled", ready=False, used=False, degraded_reasons=[])

    adapter: KrakenOrderBookAdapter | None = None
    fetcher = orderbook_fetcher
    if fetcher is None:
        adapter = KrakenOrderBookAdapter(get_settings())
        fetcher = lambda symbol, depth: adapter.fetch_snapshot(symbol=symbol, depth=depth)

    feature_values: list[_FeatureValue] = []
    snapshots: list[_OrderbookSnapshotInput] = []
    degraded_reasons: list[str] = []
    successful_symbols: set[str] = set()

    try:
        assert fetcher is not None
        for symbol in CI_ORDERBOOK_SYMBOLS:
            try:
                snapshot = fetcher(symbol, 25)
                snapshot_input = _snapshot_input_from_orderbook(snapshot)
                snapshots.append(snapshot_input)
                successful_symbols.add(symbol)
                feature_values.extend(_orderbook_feature_values(snapshot_input))
            except Exception as exc:  # pragma: no cover - exercised by worker tests
                feature_values.extend(_missing_orderbook_feature_values(symbol=symbol, as_of_at=run_time))
                degraded_reasons.append("orderbook_unavailable")
                _emit_worker_event(
                    db,
                    event_type="ci_crypto_regime.orderbook_unavailable",
                    severity="warning",
                    message="Kraken order book enrichment was unavailable for the CI crypto regime advisory run.",
                    payload={"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"},
                )
    finally:
        if adapter is not None:
            adapter.close()

    existing_counts = _orderbook_history_counts(db)
    required = max(1, runtime.min_book_snapshots)
    ready = bool(successful_symbols) and all(existing_counts.get(symbol, 0) + (1 if symbol in successful_symbols else 0) >= required for symbol in CI_ORDERBOOK_SYMBOLS)

    market_score = _market_microstructure_score(snapshots) if snapshots and not degraded_reasons else None
    feature_values.append(
        _feature_value(
            "microstructure_support_score",
            market_score,
            "kraken",
            "market",
            None,
            max((snapshot.as_of_at for snapshot in snapshots if snapshot.as_of_at is not None), default=run_time),
        )
    )

    if degraded_reasons and not snapshots:
        status = "unavailable"
    elif degraded_reasons:
        status = "partial"
    elif ready:
        status = "ready"
    else:
        status = "warming"

    used = ready and market_score is not None and not degraded_reasons
    return _OrderbookCollection(
        feature_values=feature_values,
        snapshots=snapshots,
        status=status,
        ready=ready,
        used=used,
        degraded_reasons=sorted(set(degraded_reasons)),
    )


def _compute_rules_inference(
    *,
    inputs: _InferenceInputs,
    runtime: CiCryptoRegimeSettings,
) -> _ComputedInference:
    feature_map = {item.feature_name: item for item in inputs.feature_values}
    trend_values = [
        feature_map[name].feature_value
        for name in ("btc_trend_4h", "btc_trend_1h", "eth_trend_4h", "eth_trend_1h")
        if name in feature_map and feature_map[name].feature_value is not None
    ]
    trend_score = _mean_optional(trend_values) or 0.0
    breadth_score = float(feature_map.get("crypto_breadth_pct_above_ma", _feature_value("", 0.0, "", "", None, None)).feature_value or 0.0)
    vol_1h = float(feature_map.get("crypto_realized_vol_1h", _feature_value("", 0.0, "", "", None, None)).feature_value or 0.0)
    vol_4h = float(feature_map.get("crypto_realized_vol_4h", _feature_value("", 0.0, "", "", None, None)).feature_value or 0.0)
    z_scores = [
        float(feature_map[name].feature_value)
        for name in ("btc_return_z_1h", "eth_return_z_1h")
        if name in feature_map and feature_map[name].feature_value is not None
    ]
    z_support = _z_support_score(z_scores)
    vol_support = _volatility_support_score(vol_1h=vol_1h, vol_4h=vol_4h)
    base_composite = round((trend_score * 0.45) + (breadth_score * 0.25) + (vol_support * 0.15) + (z_support * 0.15), 6)

    microstructure = feature_map.get("microstructure_support_score")
    microstructure_score = float(microstructure.feature_value) if microstructure and microstructure.feature_value is not None else None
    defillama_support = _defillama_support_score(feature_map)
    hurst_support = _hurst_support_score(feature_map)
    composite = base_composite
    if inputs.orderbook_used and microstructure_score is not None:
        composite = round((composite * 0.80) + (microstructure_score * 0.20), 6)
    if inputs.defillama_used and defillama_support is not None:
        composite = round((composite * 0.85) + (defillama_support * 0.15), 6)
    if inputs.hurst_used and hurst_support is not None:
        composite = round((composite * 0.90) + (hurst_support * 0.10), 6)

    degraded_reasons = list(inputs.degraded_reasons)
    degraded = bool(degraded_reasons)

    if inputs.stale:
        state = "unavailable"
        confidence = 0.35
        degraded = True
        reason_codes = ["stale_internal_data", *degraded_reasons]
    elif composite >= 0.67 and breadth_score >= 0.55 and trend_score >= 0.50:
        state = "bull"
        confidence = _confidence_from_score(state=state, score=composite)
        reason_codes = _reason_codes(
            feature_map=feature_map,
            composite=composite,
            orderbook_status=inputs.orderbook_status,
            defillama_status=inputs.defillama_status,
            hurst_status=inputs.hurst_status,
        )
    elif composite >= 0.40 and breadth_score >= 0.25:
        state = "neutral"
        confidence = _confidence_from_score(state=state, score=composite)
        reason_codes = _reason_codes(
            feature_map=feature_map,
            composite=composite,
            orderbook_status=inputs.orderbook_status,
            defillama_status=inputs.defillama_status,
            hurst_status=inputs.hurst_status,
        )
    else:
        state = "risk_off"
        confidence = _confidence_from_score(state=state, score=composite)
        reason_codes = _reason_codes(
            feature_map=feature_map,
            composite=composite,
            orderbook_status=inputs.orderbook_status,
            defillama_status=inputs.defillama_status,
            hurst_status=inputs.hurst_status,
        )

    core_regime_state = inputs.latest_core_regime.regime if inputs.latest_core_regime is not None else None
    if core_regime_state is None or core_regime_state not in CI_ALLOWED_STATES:
        agreement = "core_unavailable"
    else:
        agreement = "agree" if core_regime_state == state else "disagree"

    if state == "bull":
        advisory_action = "allow" if agreement == "agree" else "tighten"
    elif state == "neutral":
        advisory_action = "tighten"
    elif state == "risk_off":
        advisory_action = "block"
    else:
        advisory_action = "ignore"

    summary = {
        "base_composite_score": base_composite,
        "composite_score": composite,
        "trend_score": round(trend_score, 6),
        "breadth_score": round(breadth_score, 6),
        "volatility_support_score": round(vol_support, 6),
        "return_support_score": round(z_support, 6),
        "microstructure_support_score": round(microstructure_score, 6) if microstructure_score is not None else None,
        "defillama_support_score": round(defillama_support, 6) if defillama_support is not None else None,
        "hurst_support_score": round(hurst_support, 6) if hurst_support is not None else None,
        "core_regime_state": core_regime_state,
        "feature_contract_version": CI_FEATURE_SET_VERSION,
        "run_interval_minutes": runtime.run_interval_minutes,
        "stale": inputs.stale,
        "newest_feature_at": inputs.newest_feature_at.isoformat() if inputs.newest_feature_at else None,
        "oldest_required_feature_at": inputs.oldest_required_feature_at.isoformat() if inputs.oldest_required_feature_at else None,
        "orderbook_status": inputs.orderbook_status,
        "orderbook_ready": inputs.orderbook_ready,
        "orderbook_used": inputs.orderbook_used,
        "defillama_status": inputs.defillama_status,
        "defillama_ready": inputs.defillama_ready,
        "defillama_used": inputs.defillama_used,
        "hurst_status": inputs.hurst_status,
        "hurst_ready": inputs.hurst_ready,
        "hurst_used": inputs.hurst_used,
        "degraded_reasons": degraded_reasons,
    }
    return _ComputedInference(
        state=state,
        confidence=confidence,
        degraded=degraded,
        agreement_with_core=agreement,
        advisory_action=advisory_action,
        cluster_id=None,
        cluster_prob_bull=_probability_for_state(state="bull", chosen_state=state, score=composite),
        cluster_prob_neutral=_probability_for_state(state="neutral", chosen_state=state, score=composite),
        cluster_prob_risk_off=_probability_for_state(state="risk_off", chosen_state=state, score=composite),
        reason_codes=reason_codes[:8],
        summary=summary,
    )


def _create_run(
    db: Session,
    *,
    run_time: datetime,
    status: str,
    skip_reason: str | None,
    settings: CiCryptoRegimeSettings,
    degraded: bool,
    used_orderbook: bool,
    used_defillama: bool,
    used_hurst: bool,
    data_window_end_at: datetime,
) -> CiCryptoRegimeRun:
    run = CiCryptoRegimeRun(
        run_started_at=run_time,
        run_completed_at=run_time,
        status=status,
        skip_reason=skip_reason,
        model_version=settings.model_version,
        feature_set_version=CI_FEATURE_SET_VERSION,
        used_orderbook=used_orderbook,
        used_defillama=used_defillama,
        used_hurst=used_hurst,
        data_window_end_at=data_window_end_at,
        error_message=None,
        degraded=degraded,
    )
    db.add(run)
    db.flush()
    return run


def _write_feature_rows(db: Session, *, run_id: int, feature_values: list[_FeatureValue]) -> None:
    for item in feature_values:
        row = CiCryptoRegimeFeatureSnapshot(
            run_id=run_id,
            symbol_scope=item.symbol_scope,
            timeframe=item.timeframe,
            feature_name=item.feature_name,
            feature_value=item.feature_value,
            feature_status=item.feature_status,
            source=item.source,
            as_of_at=ensure_utc(item.as_of_at),
        )
        db.add(row)


def _write_orderbook_rows(db: Session, *, run_id: int, snapshots: list[_OrderbookSnapshotInput]) -> None:
    for item in snapshots:
        db.add(
            CiCryptoRegimeOrderbookSnapshot(
                run_id=run_id,
                venue=item.venue,
                symbol=item.symbol,
                bid_levels=item.bid_levels,
                ask_levels=item.ask_levels,
                best_bid=item.best_bid,
                best_ask=item.best_ask,
                spread_bps=item.spread_bps,
                top10_imbalance=item.top10_imbalance,
                top25_depth_usd=item.top25_depth_usd,
                sweep_cost_buy_5k_bps=item.sweep_cost_buy_5k_bps,
                sweep_cost_sell_5k_bps=item.sweep_cost_sell_5k_bps,
                as_of_at=ensure_utc(item.as_of_at),
                payload_json=item.payload_json,
            )
        )


def _upsert_ci_state(
    db: Session,
    *,
    run_id: int,
    as_of_at: datetime,
    computed: _ComputedInference,
    core_regime_state: str | None,
) -> CiCryptoRegimeState:
    state = CiCryptoRegimeState(
        run_id=run_id,
        as_of_at=ensure_utc(as_of_at) or datetime.now(UTC),
        state=computed.state,
        confidence=computed.confidence,
        cluster_id=computed.cluster_id,
        cluster_prob_bull=computed.cluster_prob_bull,
        cluster_prob_neutral=computed.cluster_prob_neutral,
        cluster_prob_risk_off=computed.cluster_prob_risk_off,
        agreement_with_core=computed.agreement_with_core,
        advisory_action=computed.advisory_action,
        core_regime_state=core_regime_state,
        degraded=computed.degraded,
        reason_codes_json=computed.reason_codes,
        summary_json=computed.summary,
    )
    db.add(state)
    db.flush()
    return state


def _emit_worker_event(
    db: Session,
    *,
    event_type: str,
    severity: str,
    message: str,
    payload: dict[str, Any] | None,
) -> None:
    create_system_event(
        db,
        event_type=event_type,
        severity=severity,
        message=message,
        event_source=CI_EVENT_SOURCE,
        payload=payload,
        commit=False,
    )


def _latest_feature_snapshot(db: Session, *, symbol: str, timeframe: str) -> FeatureSnapshot | None:
    return (
        db.query(FeatureSnapshot)
        .filter(
            FeatureSnapshot.asset_class == "crypto",
            FeatureSnapshot.symbol == symbol,
            FeatureSnapshot.timeframe == timeframe,
        )
        .order_by(FeatureSnapshot.candle_timestamp.desc())
        .first()
    )


def _latest_core_regime_for_display(db: Session) -> RegimeSnapshot | None:
    return (
        db.query(RegimeSnapshot)
        .filter(RegimeSnapshot.asset_class == "crypto")
        .order_by(RegimeSnapshot.computed_at.desc(), RegimeSnapshot.id.desc())
        .first()
    )


def _recent_candles(db: Session, *, symbol: str, timeframe: str, limit: int) -> list[Candle]:
    rows = (
        db.query(Candle)
        .filter(Candle.asset_class == "crypto", Candle.symbol == symbol, Candle.timeframe == timeframe)
        .order_by(Candle.timestamp.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


def _recent_ci_feature_values(db: Session, *, feature_name: str, limit: int = 96) -> list[tuple[datetime | None, float]]:
    rows = (
        db.query(CiCryptoRegimeFeatureSnapshot)
        .filter(CiCryptoRegimeFeatureSnapshot.feature_name == feature_name, CiCryptoRegimeFeatureSnapshot.feature_value.isnot(None))
        .order_by(CiCryptoRegimeFeatureSnapshot.as_of_at.desc(), CiCryptoRegimeFeatureSnapshot.id.desc())
        .limit(limit)
        .all()
    )
    ordered = list(reversed(rows))
    return [(ensure_utc(row.as_of_at), float(row.feature_value)) for row in ordered if row.feature_value is not None]


def _rolling_feature_zscore(db: Session, *, feature_name: str, current_value: float | None) -> float | None:
    if current_value is None:
        return None
    history = [value for _, value in _recent_ci_feature_values(db, feature_name=feature_name, limit=96)]
    values = [*history, current_value]
    if len(values) < 3:
        return None
    mean_value = fmean(values)
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    stddev = sqrt(variance)
    if stddev <= 0:
        return 0.0
    return round((current_value - mean_value) / stddev, 6)


def _feature_change_pct(
    db: Session,
    *,
    feature_name: str,
    current_value: float | None,
    as_of_at: datetime | None,
    lookback_hours: int,
) -> float | None:
    if current_value is None:
        return None
    anchor = ensure_utc(as_of_at) or datetime.now(UTC)
    cutoff = anchor - timedelta(hours=max(1, lookback_hours))
    candidates = [(as_of_at, value) for as_of_at, value in _recent_ci_feature_values(db, feature_name=feature_name, limit=192) if as_of_at is not None and as_of_at <= cutoff]
    if not candidates:
        return None
    return _pct_change(current=current_value, previous=candidates[-1][1])


def _pct_change(*, current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or abs(previous) <= 1e-12:
        return None
    return round(((current - previous) / abs(previous)) * 100.0, 6)


def _missing_named_features(names: tuple[str, ...], *, source: str, symbol_scope: str, as_of_at: datetime) -> list[_FeatureValue]:
    return [_feature_value(name, None, source, symbol_scope, None, as_of_at) for name in names]


def _hurst_exponent(values: list[float], *, max_lag: int = 20) -> float | None:
    clean = [value for value in values if value is not None and value > 0]
    if len(clean) < max(32, max_lag + 2):
        return None
    logs = [log(value) for value in clean]
    upper_lag = min(max_lag, max(5, len(logs) // 4))
    x_values: list[float] = []
    y_values: list[float] = []
    for lag in range(2, upper_lag + 1):
        diffs = [logs[index] - logs[index - lag] for index in range(lag, len(logs))]
        if len(diffs) < 2:
            continue
        variance = sum(diff * diff for diff in diffs) / len(diffs)
        if variance <= 0:
            continue
        tau = sqrt(variance)
        x_values.append(log(float(lag)))
        y_values.append(log(tau))
    slope = _linear_regression_slope(x_values, y_values)
    if slope is None:
        return None
    hurst = max(0.0, min(1.0, slope * 2.0))
    return round(hurst, 6)


def _linear_regression_slope(x_values: list[float], y_values: list[float]) -> float | None:
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return None
    x_mean = fmean(x_values)
    y_mean = fmean(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    if denominator <= 0:
        return None
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values, strict=False))
    return numerator / denominator


def _orderbook_history_counts(db: Session) -> dict[str, int]:
    rows = (
        db.query(CiCryptoRegimeOrderbookSnapshot.symbol, func.count(CiCryptoRegimeOrderbookSnapshot.id))
        .group_by(CiCryptoRegimeOrderbookSnapshot.symbol)
        .all()
    )
    return {str(symbol): int(count) for symbol, count in rows}


def _snapshot_input_from_orderbook(snapshot: OrderBookSnapshot) -> _OrderbookSnapshotInput:
    best_bid = _safe_float(snapshot.bids[0].price) if snapshot.bids else None
    best_ask = _safe_float(snapshot.asks[0].price) if snapshot.asks else None
    spread_bps = _spread_bps(best_bid=best_bid, best_ask=best_ask)
    top10_imbalance = _top_imbalance(snapshot.bids, snapshot.asks, levels=10)
    top25_depth_usd = _top_depth_usd(snapshot.bids, count=25) + _top_depth_usd(snapshot.asks, count=25)
    sweep_cost_buy = _sweep_cost_bps(snapshot.bids, snapshot.asks, side="buy", notional=5000.0)
    sweep_cost_sell = _sweep_cost_bps(snapshot.bids, snapshot.asks, side="sell", notional=5000.0)
    return _OrderbookSnapshotInput(
        venue="kraken",
        symbol=snapshot.symbol,
        bid_levels=len(snapshot.bids),
        ask_levels=len(snapshot.asks),
        best_bid=best_bid,
        best_ask=best_ask,
        spread_bps=spread_bps,
        top10_imbalance=top10_imbalance,
        top25_depth_usd=round(top25_depth_usd, 6) if top25_depth_usd > 0 else None,
        sweep_cost_buy_5k_bps=sweep_cost_buy,
        sweep_cost_sell_5k_bps=sweep_cost_sell,
        as_of_at=snapshot.as_of,
        payload_json={
            "top_bids": _serialize_levels(snapshot.bids[:5]),
            "top_asks": _serialize_levels(snapshot.asks[:5]),
        },
    )


def _orderbook_feature_values(snapshot: _OrderbookSnapshotInput) -> list[_FeatureValue]:
    prefix = "btc" if snapshot.symbol == "XBTUSD" else "eth"
    return [
        _feature_value(f"{prefix}_spread_bps", snapshot.spread_bps, "kraken", snapshot.symbol, None, snapshot.as_of_at),
        _feature_value(f"{prefix}_top10_imbalance", snapshot.top10_imbalance, "kraken", snapshot.symbol, None, snapshot.as_of_at),
        _feature_value(f"{prefix}_top25_depth_usd", snapshot.top25_depth_usd, "kraken", snapshot.symbol, None, snapshot.as_of_at),
        _feature_value(f"{prefix}_sweep_cost_buy_5k_bps", snapshot.sweep_cost_buy_5k_bps, "kraken", snapshot.symbol, None, snapshot.as_of_at),
        _feature_value(f"{prefix}_sweep_cost_sell_5k_bps", snapshot.sweep_cost_sell_5k_bps, "kraken", snapshot.symbol, None, snapshot.as_of_at),
    ]


def _missing_orderbook_feature_values(*, symbol: str, as_of_at: datetime) -> list[_FeatureValue]:
    prefix = "btc" if symbol == "XBTUSD" else "eth"
    return [
        _feature_value(f"{prefix}_spread_bps", None, "kraken", symbol, None, as_of_at),
        _feature_value(f"{prefix}_top10_imbalance", None, "kraken", symbol, None, as_of_at),
        _feature_value(f"{prefix}_top25_depth_usd", None, "kraken", symbol, None, as_of_at),
        _feature_value(f"{prefix}_sweep_cost_buy_5k_bps", None, "kraken", symbol, None, as_of_at),
        _feature_value(f"{prefix}_sweep_cost_sell_5k_bps", None, "kraken", symbol, None, as_of_at),
    ]


def _serialize_levels(levels: tuple[OrderBookLevel, ...] | list[OrderBookLevel]) -> list[dict[str, Any]]:
    return [
        {
            "price": float(level.price),
            "volume": float(level.volume),
            "timestamp": level.timestamp.isoformat() if level.timestamp else None,
        }
        for level in levels
    ]


def _top_depth_usd(book_levels: tuple[OrderBookLevel, ...], *, count: int = 25) -> float:
    return round(sum(float(level.price) * float(level.volume) for level in tuple(book_levels)[:count]), 6)


def _top_imbalance(bids: tuple[OrderBookLevel, ...], asks: tuple[OrderBookLevel, ...], *, levels: int) -> float | None:
    bid_depth = _top_depth_usd(bids, count=levels)
    ask_depth = _top_depth_usd(asks, count=levels)
    total = bid_depth + ask_depth
    if total <= 0:
        return None
    return round((bid_depth - ask_depth) / total, 6)


def _spread_bps(*, best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
        return None
    mid = (best_bid + best_ask) / 2.0
    if mid <= 0:
        return None
    return round(((best_ask - best_bid) / mid) * 10000.0, 6)


def _sweep_cost_bps(
    bids: tuple[OrderBookLevel, ...],
    asks: tuple[OrderBookLevel, ...],
    *,
    side: str,
    notional: float,
) -> float | None:
    book = asks if side == "buy" else bids
    if not book or notional <= 0:
        return None
    best_bid = _safe_float(bids[0].price) if bids else None
    best_ask = _safe_float(asks[0].price) if asks else None
    mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else None
    if mid is None or mid <= 0:
        return None

    remaining_notional = notional
    total_cost = 0.0
    total_quantity = 0.0
    for level in book:
        price = float(level.price)
        available_quantity = float(level.volume)
        if price <= 0 or available_quantity <= 0:
            continue
        level_notional = price * available_quantity
        consumed_notional = min(remaining_notional, level_notional)
        quantity = consumed_notional / price
        total_cost += quantity * price
        total_quantity += quantity
        remaining_notional -= consumed_notional
        if remaining_notional <= 1e-9:
            break
    if remaining_notional > 1e-6 or total_quantity <= 0:
        return None
    execution_price = total_cost / total_quantity
    if side == "buy":
        return round(((execution_price - mid) / mid) * 10000.0, 6)
    return round(((mid - execution_price) / mid) * 10000.0, 6)


def _market_microstructure_score(snapshots: list[_OrderbookSnapshotInput]) -> float | None:
    scores = [_microstructure_score(snapshot) for snapshot in snapshots]
    available = [score for score in scores if score is not None]
    if not available:
        return None
    return round(sum(available) / len(available), 6)


def _microstructure_score(snapshot: _OrderbookSnapshotInput) -> float | None:
    if snapshot.spread_bps is None or snapshot.top10_imbalance is None or snapshot.top25_depth_usd is None:
        return None
    sweep_values = [value for value in (snapshot.sweep_cost_buy_5k_bps, snapshot.sweep_cost_sell_5k_bps) if value is not None]
    if not sweep_values:
        return None

    spread_score = _clamp01(1.0 - (snapshot.spread_bps / 20.0))
    imbalance_score = _clamp01((snapshot.top10_imbalance + 1.0) / 2.0)
    depth_target = 500000.0 if snapshot.symbol == "XBTUSD" else 250000.0
    depth_score = _clamp01(snapshot.top25_depth_usd / depth_target)
    sweep_score = _clamp01(1.0 - ((sum(sweep_values) / len(sweep_values)) / 25.0))
    return round((spread_score * 0.30) + (imbalance_score * 0.20) + (depth_score * 0.25) + (sweep_score * 0.25), 6)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _trend_flag(row: FeatureSnapshot | None) -> float | None:
    if row is None:
        return None
    if None in (row.sma_20, row.ema_20, row.momentum_20, row.trend_slope_20):
        return None
    return 1.0 if float(row.close) >= float(row.sma_20) and float(row.close) >= float(row.ema_20) and float(row.momentum_20) > 0 and float(row.trend_slope_20) > 0 else 0.0


def _return_z_scores(rows: list[FeatureSnapshot]) -> dict[str, float]:
    values = [float(row.price_return_1) for row in rows if row.price_return_1 is not None]
    if not values:
        return {}
    mean_value = fmean(values)
    if len(values) < 2:
        return {row.symbol: 0.0 for row in rows if row.price_return_1 is not None}
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    stddev = sqrt(variance)
    if stddev <= 0:
        return {row.symbol: 0.0 for row in rows if row.price_return_1 is not None}
    return {row.symbol: round((float(row.price_return_1) - mean_value) / stddev, 6) for row in rows if row.price_return_1 is not None}


def _z_support_score(z_scores: list[float]) -> float:
    if not z_scores:
        return 0.5
    clipped = [max(-2.0, min(2.0, value)) for value in z_scores]
    normalized = [(value + 2.0) / 4.0 for value in clipped]
    return round(sum(normalized) / len(normalized), 6)


def _volatility_support_score(*, vol_1h: float, vol_4h: float) -> float:
    if vol_1h <= 0 and vol_4h <= 0:
        return 0.5
    score_1h = max(0.0, min(1.0, 1.0 - (vol_1h / 0.08)))
    score_4h = max(0.0, min(1.0, 1.0 - (vol_4h / 0.10)))
    return round((score_1h * 0.6) + (score_4h * 0.4), 6)


def _defillama_support_score(feature_map: dict[str, _FeatureValue]) -> float | None:
    funding = _normalize_range(_feature_float(feature_map, "market_funding_bias"), floor=-0.01, ceiling=0.01)
    oi_z = _normalize_range(_feature_float(feature_map, "market_open_interest_z"), floor=-2.0, ceiling=2.0)
    oi_change = _normalize_range(_feature_float(feature_map, "market_oi_change_24h"), floor=-25.0, ceiling=25.0)
    tvl_change = _normalize_range(_feature_float(feature_map, "market_defi_tvl_change_24h"), floor=-10.0, ceiling=10.0)
    return _mean_optional([funding, oi_z, oi_change, tvl_change])


def _hurst_support_score(feature_map: dict[str, _FeatureValue]) -> float | None:
    values = [_feature_float(feature_map, name) for name in CI_HURST_FEATURE_CONTRACT]
    normalized = [_normalize_range(value, floor=0.35, ceiling=0.75) for value in values if value is not None]
    return _mean_optional(normalized)


def _feature_float(feature_map: dict[str, _FeatureValue], name: str) -> float | None:
    feature = feature_map.get(name)
    if feature is None or feature.feature_value is None:
        return None
    return float(feature.feature_value)


def _normalize_range(value: float | None, *, floor: float, ceiling: float) -> float | None:
    if value is None or ceiling <= floor:
        return None
    clipped = max(floor, min(ceiling, value))
    return round((clipped - floor) / (ceiling - floor), 6)


def _probability_for_state(*, state: str, chosen_state: str, score: float) -> float:
    if chosen_state == "unavailable":
        return 0.34 if state == "neutral" else 0.33
    if chosen_state == state:
        return round(min(0.99, max(0.34, 0.40 + (score * 0.60))), 5)
    remaining = max(0.01, 1.0 - min(0.99, max(0.34, 0.40 + (score * 0.60))))
    return round(remaining / 2.0, 5)


def _confidence_from_score(*, state: str, score: float) -> float:
    if state == "bull":
        return round(min(0.99, 0.50 + max(0.0, score - 0.50)), 5)
    if state == "risk_off":
        inverted = max(0.0, 1.0 - score)
        return round(min(0.99, 0.50 + max(0.0, inverted - 0.20)), 5)
    distance = abs(score - 0.50)
    return round(min(0.85, 0.55 + max(0.0, 0.20 - distance)), 5)


def _reason_codes(
    *,
    feature_map: dict[str, _FeatureValue],
    composite: float,
    orderbook_status: str,
    defillama_status: str,
    hurst_status: str,
) -> list[str]:
    reasons: list[str] = []
    if (feature_map["btc_trend_4h"].feature_value or 0.0) < 1.0:
        reasons.append("btc_trend_4h_soft")
    if (feature_map["btc_trend_1h"].feature_value or 0.0) < 1.0:
        reasons.append("btc_trend_1h_soft")
    if (feature_map["eth_trend_4h"].feature_value or 0.0) < 1.0:
        reasons.append("eth_trend_4h_soft")
    if (feature_map["eth_trend_1h"].feature_value or 0.0) < 1.0:
        reasons.append("eth_trend_1h_soft")
    breadth = feature_map["crypto_breadth_pct_above_ma"].feature_value
    if breadth is not None:
        if breadth >= 0.55:
            reasons.append("breadth_support_strong")
        elif breadth >= 0.25:
            reasons.append("breadth_support_mixed")
        else:
            reasons.append("breadth_support_weak")
    micro = feature_map.get("microstructure_support_score")
    if micro is not None and micro.feature_value is not None:
        if micro.feature_value >= 0.65:
            reasons.append("orderbook_bid_support_strong")
        elif micro.feature_value >= 0.45:
            reasons.append("orderbook_bid_support_mixed")
        else:
            reasons.append("orderbook_bid_support_weak")
    elif orderbook_status == "warming":
        reasons.append("orderbook_warmup_pending")
    elif orderbook_status in {"partial", "unavailable"}:
        reasons.append("orderbook_unavailable")
    defillama = feature_map.get("market_funding_bias")
    if defillama is not None and defillama.feature_value is not None:
        if defillama.feature_value >= 0.003:
            reasons.append("defillama_funding_support_strong")
        elif defillama.feature_value >= 0.0:
            reasons.append("defillama_funding_support_mixed")
        else:
            reasons.append("defillama_funding_support_weak")
    elif defillama_status == "warming":
        reasons.append("defillama_warmup_pending")
    elif defillama_status in {"partial", "unavailable"}:
        reasons.append("defillama_unavailable")
    hurst = _mean_optional([
        feature_map[name].feature_value
        for name in CI_HURST_FEATURE_CONTRACT
        if name in feature_map
    ])
    if hurst is not None:
        if hurst >= 0.58:
            reasons.append("hurst_trend_persistence_strong")
        elif hurst >= 0.50:
            reasons.append("hurst_trend_persistence_mixed")
        else:
            reasons.append("hurst_trend_persistence_weak")
    elif hurst_status == "warming":
        reasons.append("hurst_warmup_pending")
    elif hurst_status in {"partial", "unavailable"}:
        reasons.append("hurst_unavailable")
    if composite >= 0.67:
        reasons.append("composite_bull_threshold")
    elif composite >= 0.40:
        reasons.append("composite_neutral_threshold")
    else:
        reasons.append("composite_risk_off_threshold")
    return reasons


def _feature_value(
    feature_name: str,
    feature_value: float | None,
    source: str,
    symbol_scope: str,
    timeframe: str | None,
    as_of_at: datetime | None,
) -> _FeatureValue:
    return _FeatureValue(
        feature_name=feature_name,
        feature_value=round(feature_value, 6) if feature_value is not None else None,
        feature_status="ok" if feature_value is not None else "missing",
        source=source,
        symbol_scope=symbol_scope,
        timeframe=timeframe,
        as_of_at=ensure_utc(as_of_at),
    )


def _mean_optional(values: list[float | None]) -> float | None:
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return round(fmean(filtered), 6)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _share(rows: list[FeatureSnapshot], predicate: Any) -> float | None:
    if not rows:
        return None
    matched = sum(1 for row in rows if predicate(row))
    return round(matched / len(rows), 6)
