from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import sqrt
from statistics import fmean
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.core import (
    CiCryptoRegimeFeatureSnapshot,
    CiCryptoRegimeModelRegistry,
    CiCryptoRegimeRun,
    CiCryptoRegimeState,
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
CI_ALLOWED_AGREEMENT = {"agree", "disagree", "core_unavailable"}
CI_ALLOWED_ACTIONS = {"allow", "tighten", "block", "ignore"}
CI_BENCHMARK_SYMBOLS = ("XBTUSD", "ETHUSD")
CI_FEATURE_CONTRACT = (
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
class _InferenceInputs:
    universe_symbols: tuple[str, ...]
    latest_core_regime: RegimeSnapshot | None
    feature_rows_1h: list[FeatureSnapshot]
    feature_rows_4h: list[FeatureSnapshot]
    feature_values: list[_FeatureValue]
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
    return {
        "enabled": settings.enabled,
        "advisory_only": settings.advisory_only,
        "as_of_at": state.as_of_at,
        "state": state.state,
        "confidence": state.confidence,
        "core_regime_state": state.core_regime_state,
        "agreement_with_core": state.agreement_with_core,
        "advisory_action": state.advisory_action,
        "model_version": state.run.model_version if state.run else settings.model_version,
        "feature_set_version": state.run.feature_set_version if state.run else CI_FEATURE_SET_VERSION,
        "degraded": state.degraded,
        "reason_codes": list(state.reason_codes_json or []),
        "summary": state.summary_json or {},
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
    return {
        "run": run,
        "state": state,
        "features": feature_rows,
    }


def run_ci_crypto_regime_advisory(
    db: Session,
    *,
    now: datetime | None = None,
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

    inputs = _collect_inference_inputs(db, runtime=runtime, run_time=run_time)
    if inputs is None:
        run = _create_run(
            db,
            run_time=run_time,
            status="skipped",
            skip_reason="core_regime_not_ready",
            settings=runtime,
            degraded=False,
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
        )
        _write_feature_rows(db, run_id=run.id, feature_values=inputs.feature_values)
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
    )
    _write_feature_rows(db, run_id=run.id, feature_values=inputs.feature_values)
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
        for row in (
            _latest_feature_snapshot(db, symbol=symbol, timeframe="1h")
            for symbol in universe_symbols
        )
        if row is not None
    ]
    feature_rows_4h = [
        row
        for row in (
            _latest_feature_snapshot(db, symbol=symbol, timeframe="4h")
            for symbol in universe_symbols
        )
        if row is not None
    ]

    newest_times = [ensure_utc(row.candle_timestamp) for row in [*feature_rows_1h, *feature_rows_4h] if ensure_utc(row.candle_timestamp) is not None]
    newest_feature_at = max(newest_times) if newest_times else None
    oldest_required_feature_at = min(newest_times) if newest_times else None
    stale_cutoff = run_time - timedelta(seconds=max(60, runtime.stale_after_seconds))
    stale = bool(newest_feature_at is None or newest_feature_at < stale_cutoff)

    feature_values = _build_feature_values(feature_rows_1h=feature_rows_1h, feature_rows_4h=feature_rows_4h, run_time=run_time)
    return _InferenceInputs(
        universe_symbols=universe_symbols,
        latest_core_regime=core_regime,
        feature_rows_1h=feature_rows_1h,
        feature_rows_4h=feature_rows_4h,
        feature_values=feature_values,
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
        _feature_value("crypto_breadth_pct_above_ma", breadth, "internal", "market", "1h", run_time if breadth is None else max((ensure_utc(row.candle_timestamp) or run_time) for row in feature_rows_1h) if feature_rows_1h else run_time),
        _feature_value("crypto_realized_vol_1h", vol_1h, "internal", "market", "1h", run_time if vol_1h is None else max((ensure_utc(row.candle_timestamp) or run_time) for row in feature_rows_1h) if feature_rows_1h else run_time),
        _feature_value("crypto_realized_vol_4h", vol_4h, "internal", "market", "4h", run_time if vol_4h is None else max((ensure_utc(row.candle_timestamp) or run_time) for row in feature_rows_4h) if feature_rows_4h else run_time),
        _feature_value("btc_return_z_1h", z_scores.get("XBTUSD"), "derived", "XBTUSD", "1h", btc_1h.candle_timestamp if btc_1h else None),
        _feature_value("eth_return_z_1h", z_scores.get("ETHUSD"), "derived", "ETHUSD", "1h", eth_1h.candle_timestamp if eth_1h else None),
    ]


def _compute_rules_inference(
    *,
    inputs: _InferenceInputs,
    runtime: CiCryptoRegimeSettings,
) -> _ComputedInference:
    feature_map = {item.feature_name: item for item in inputs.feature_values}
    trend_values = [
        feature_map[name].feature_value
        for name in ("btc_trend_4h", "btc_trend_1h", "eth_trend_4h", "eth_trend_1h")
        if feature_map[name].feature_value is not None
    ]
    trend_score = _mean_optional(trend_values) or 0.0
    breadth_score = float(feature_map["crypto_breadth_pct_above_ma"].feature_value or 0.0)
    vol_1h = float(feature_map["crypto_realized_vol_1h"].feature_value or 0.0)
    vol_4h = float(feature_map["crypto_realized_vol_4h"].feature_value or 0.0)
    z_scores = [
        float(feature_map[name].feature_value)
        for name in ("btc_return_z_1h", "eth_return_z_1h")
        if feature_map[name].feature_value is not None
    ]
    z_support = _z_support_score(z_scores)
    vol_support = _volatility_support_score(vol_1h=vol_1h, vol_4h=vol_4h)
    composite = round((trend_score * 0.45) + (breadth_score * 0.25) + (vol_support * 0.15) + (z_support * 0.15), 6)

    if inputs.stale:
        state = "unavailable"
        confidence = 0.35
        degraded = True
        reason_codes = ["stale_internal_data"]
    elif composite >= 0.67 and breadth_score >= 0.55 and trend_score >= 0.50:
        state = "bull"
        confidence = _confidence_from_score(state=state, score=composite)
        degraded = False
        reason_codes = _reason_codes(feature_map=feature_map, composite=composite)
    elif composite >= 0.40 and breadth_score >= 0.25:
        state = "neutral"
        confidence = _confidence_from_score(state=state, score=composite)
        degraded = False
        reason_codes = _reason_codes(feature_map=feature_map, composite=composite)
    else:
        state = "risk_off"
        confidence = _confidence_from_score(state=state, score=composite)
        degraded = False
        reason_codes = _reason_codes(feature_map=feature_map, composite=composite)

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
        "composite_score": composite,
        "trend_score": round(trend_score, 6),
        "breadth_score": round(breadth_score, 6),
        "volatility_support_score": round(vol_support, 6),
        "return_support_score": round(z_support, 6),
        "core_regime_state": core_regime_state,
        "feature_contract_version": CI_FEATURE_SET_VERSION,
        "run_interval_minutes": runtime.run_interval_minutes,
        "stale": inputs.stale,
        "newest_feature_at": inputs.newest_feature_at.isoformat() if inputs.newest_feature_at else None,
        "oldest_required_feature_at": inputs.oldest_required_feature_at.isoformat() if inputs.oldest_required_feature_at else None,
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
        reason_codes=reason_codes,
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
) -> CiCryptoRegimeRun:
    run = CiCryptoRegimeRun(
        run_started_at=run_time,
        run_completed_at=run_time,
        status=status,
        skip_reason=skip_reason,
        model_version=settings.model_version,
        feature_set_version=CI_FEATURE_SET_VERSION,
        used_orderbook=False,
        used_defillama=False,
        used_hurst=False,
        data_window_end_at=run_time,
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


def _reason_codes(*, feature_map: dict[str, _FeatureValue], composite: float) -> list[str]:
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
    if composite >= 0.67:
        reasons.append("composite_bull_threshold")
    elif composite >= 0.40:
        reasons.append("composite_neutral_threshold")
    else:
        reasons.append("composite_risk_off_threshold")
    return reasons[:6]


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
