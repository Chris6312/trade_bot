from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from backend.app.common.strategy_support import (
    StrategyEvaluationInput,
    StrategyOutcome,
    candidate_timestamp,
    default_component_scores,
    ensure_utc,
)
from backend.app.crypto.strategies import CRYPTO_STRATEGIES
from backend.app.models.core import Candle, FeatureSnapshot, StrategySnapshot, StrategySyncState
from backend.app.services.regime_service import evaluate_regime_freshness, get_latest_regime_snapshot
from backend.app.services.settings_service import get_setting
from backend.app.stocks.strategies import STOCK_STRATEGIES

SINGLE_STRATEGY_WRITER = "strategy_worker"
STRATEGY_SOURCE = "strategy_engine"
VALID_ASSET_CLASSES = {"stock", "crypto"}


@dataclass(slots=True, frozen=True)
class ComputedStrategyRow:
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
    readiness_score: float
    composite_score: float
    threshold_score: float
    trend_score: float
    participation_score: float
    liquidity_score: float
    stability_score: float
    blocked_reasons: tuple[str, ...]
    decision_reason: str | None
    payload: dict[str, Any]


@dataclass(slots=True, frozen=True)
class StrategyPersistenceSummary:
    asset_class: str
    timeframe: str
    requested_symbols: tuple[str, ...]
    evaluated_rows: int
    ready_rows: int
    blocked_rows: int
    last_candidate_at: datetime | None
    last_computed_at: datetime | None
    regime: str | None
    entry_policy: str | None
    skipped_reason: str | None = None


def ensure_single_strategy_writer(writer_name: str) -> None:
    if writer_name != SINGLE_STRATEGY_WRITER:
        raise PermissionError(
            f"{writer_name!r} is not allowed to write strategy rows. "
            f"Only {SINGLE_STRATEGY_WRITER!r} may persist strategy candidates.",
        )


def list_strategy_snapshots(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> list[StrategySnapshot]:
    return (
        db.query(StrategySnapshot)
        .filter(
            StrategySnapshot.asset_class == asset_class,
            StrategySnapshot.timeframe == timeframe,
        )
        .order_by(
            StrategySnapshot.candidate_timestamp.asc(),
            StrategySnapshot.symbol.asc(),
            StrategySnapshot.strategy_name.asc(),
        )
        .all()
    )


def list_current_strategy_snapshots(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
    symbols: Iterable[str] | None = None,
) -> list[StrategySnapshot]:
    query = (
        db.query(StrategySnapshot)
        .filter(
            StrategySnapshot.asset_class == asset_class,
            StrategySnapshot.timeframe == timeframe,
        )
        .order_by(
            StrategySnapshot.candidate_timestamp.desc(),
            StrategySnapshot.computed_at.desc(),
            StrategySnapshot.id.desc(),
        )
    )

    requested_symbols = tuple(dict.fromkeys(str(symbol) for symbol in (symbols or ()) if str(symbol)))
    if symbols is not None and not requested_symbols:
        return []
    if requested_symbols:
        query = query.filter(StrategySnapshot.symbol.in_(requested_symbols))

    rows = query.all()
    current: dict[tuple[str, str], StrategySnapshot] = {}
    for row in rows:
        key = (row.symbol, row.strategy_name)
        if key not in current:
            current[key] = row
    return sorted(current.values(), key=lambda row: (row.symbol, row.strategy_name))


def get_strategy_sync_state(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> StrategySyncState | None:
    return (
        db.query(StrategySyncState)
        .filter(
            StrategySyncState.asset_class == asset_class,
            StrategySyncState.timeframe == timeframe,
        )
        .one_or_none()
    )


def is_strategy_enabled(
    db: Session,
    *,
    asset_class: str,
    strategy_name: str,
    default: bool = True,
) -> bool:
    record = get_setting(db, key=f"strategy_enabled.{asset_class}.{strategy_name}")
    if record is None:
        return default
    return _coerce_bool(record.value, default=default)


def rebuild_strategy_snapshots_for_asset_class(
    db: Session,
    *,
    writer_name: str,
    asset_class: str,
    venue: str,
    source: str,
    symbols: Iterable[str],
    timeframe: str,
    computed_at: datetime | None = None,
) -> StrategyPersistenceSummary:
    ensure_single_strategy_writer(writer_name)
    if asset_class not in VALID_ASSET_CLASSES:
        raise ValueError(f"Unsupported asset class: {asset_class}")

    computed_time = ensure_utc(computed_at) or datetime.now(UTC)
    requested_symbols = tuple(dict.fromkeys(symbols))
    if not requested_symbols:
        _upsert_strategy_sync_state(
            db,
            asset_class=asset_class,
            venue=venue,
            timeframe=timeframe,
            last_computed_at=computed_time,
            last_candidate_at=None,
            candidate_count=0,
            ready_count=0,
            blocked_count=0,
            regime=None,
            entry_policy=None,
            last_status="universe_unresolved",
            last_error=None,
        )
        db.commit()
        return StrategyPersistenceSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            requested_symbols=requested_symbols,
            evaluated_rows=0,
            ready_rows=0,
            blocked_rows=0,
            last_candidate_at=None,
            last_computed_at=computed_time,
            regime=None,
            entry_policy=None,
            skipped_reason="universe_unresolved",
        )

    raw_regime = get_latest_regime_snapshot(db, asset_class=asset_class, timeframe=timeframe)
    regime_freshness = evaluate_regime_freshness(
        db,
        asset_class=asset_class,
        timeframe=timeframe,
        symbols=requested_symbols,
        regime_snapshot=raw_regime,
    )
    regime = None if regime_freshness.is_stale else raw_regime
    definitions = STOCK_STRATEGIES if asset_class == "stock" else CRYPTO_STRATEGIES

    rows: list[ComputedStrategyRow] = []
    symbols_with_features = 0
    for symbol in requested_symbols:
        feature = _latest_feature_snapshot(db, asset_class=asset_class, symbol=symbol, timeframe=timeframe)
        candles = tuple(_recent_candles(db, asset_class=asset_class, symbol=symbol, timeframe=timeframe, limit=60))
        if feature is not None:
            symbols_with_features += 1
        evaluation_input = StrategyEvaluationInput(
            asset_class=asset_class,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,
            feature_snapshot=feature,
            regime_snapshot=regime,
            candles=candles,
            computed_at=computed_time,
        )
        for definition in definitions:
            outcome = definition.evaluator(evaluation_input)
            enabled = is_strategy_enabled(db, asset_class=asset_class, strategy_name=definition.name, default=True)
            if not enabled:
                outcome = _append_block_reason(outcome, "strategy_disabled")
            rows.append(
                _build_row(
                    inputs=evaluation_input,
                    outcome=outcome,
                    source=source,
                )
            )

    ready_rows = 0
    blocked_rows = 0
    last_candidate_at: datetime | None = None
    for row in rows:
        existing = (
            db.query(StrategySnapshot)
            .filter(
                StrategySnapshot.asset_class == row.asset_class,
                StrategySnapshot.symbol == row.symbol,
                StrategySnapshot.strategy_name == row.strategy_name,
                StrategySnapshot.timeframe == row.timeframe,
                StrategySnapshot.candidate_timestamp == row.candidate_timestamp,
            )
            .one_or_none()
        )
        if existing is None:
            existing = StrategySnapshot(
                asset_class=row.asset_class,
                venue=row.venue,
                source=row.source,
                symbol=row.symbol,
                strategy_name=row.strategy_name,
                direction=row.direction,
                timeframe=row.timeframe,
                candidate_timestamp=row.candidate_timestamp,
            )
            db.add(existing)

        existing.venue = row.venue
        existing.source = row.source
        existing.direction = row.direction
        existing.computed_at = row.computed_at
        existing.regime = row.regime
        existing.entry_policy = row.entry_policy
        existing.status = row.status
        existing.readiness_score = row.readiness_score
        existing.composite_score = row.composite_score
        existing.threshold_score = row.threshold_score
        existing.trend_score = row.trend_score
        existing.participation_score = row.participation_score
        existing.liquidity_score = row.liquidity_score
        existing.stability_score = row.stability_score
        existing.blocked_reasons = list(row.blocked_reasons)
        existing.decision_reason = row.decision_reason
        existing.payload = row.payload

        if row.status == "ready":
            ready_rows += 1
        else:
            blocked_rows += 1
        if last_candidate_at is None or row.candidate_timestamp > last_candidate_at:
            last_candidate_at = row.candidate_timestamp

    last_status = "synced"
    skipped_reason: str | None = None
    last_error: str | None = None
    if raw_regime is None:
        last_status = "regime_unavailable"
        skipped_reason = "regime_unavailable"
    elif regime_freshness.is_stale:
        last_status = "regime_stale"
        skipped_reason = "regime_stale"
        last_error = regime_freshness.stale_reason
    elif symbols_with_features == 0:
        last_status = "no_features"
        skipped_reason = "no_features"

    _upsert_strategy_sync_state(
        db,
        asset_class=asset_class,
        venue=venue,
        timeframe=timeframe,
        last_computed_at=computed_time,
        last_candidate_at=last_candidate_at,
        candidate_count=len(rows),
        ready_count=ready_rows,
        blocked_count=blocked_rows,
        regime=regime.regime if regime is not None else None,
        entry_policy=regime.entry_policy if regime is not None else None,
        last_status=last_status,
        last_error=last_error,
    )
    db.commit()
    return StrategyPersistenceSummary(
        asset_class=asset_class,
        timeframe=timeframe,
        requested_symbols=requested_symbols,
        evaluated_rows=len(rows),
        ready_rows=ready_rows,
        blocked_rows=blocked_rows,
        last_candidate_at=last_candidate_at,
        last_computed_at=computed_time,
        regime=regime.regime if regime is not None else None,
        entry_policy=regime.entry_policy if regime is not None else None,
        skipped_reason=skipped_reason,
    )


def _build_row(
    *,
    inputs: StrategyEvaluationInput,
    outcome: StrategyOutcome,
    source: str,
) -> ComputedStrategyRow:
    candidate_at = candidate_timestamp(inputs)
    payload = {
        **(outcome.payload or {}),
        "symbol": inputs.symbol,
        "asset_class": inputs.asset_class,
        "strategy_name": outcome.strategy_name,
    }
    return ComputedStrategyRow(
        asset_class=inputs.asset_class,
        venue=inputs.venue,
        source=source,
        symbol=inputs.symbol,
        strategy_name=outcome.strategy_name,
        direction=outcome.direction,
        timeframe=inputs.timeframe,
        candidate_timestamp=candidate_at,
        computed_at=ensure_utc(inputs.computed_at) or datetime.now(UTC),
        regime=inputs.regime_snapshot.regime if inputs.regime_snapshot is not None else None,
        entry_policy=inputs.regime_snapshot.entry_policy if inputs.regime_snapshot is not None else None,
        status=outcome.status,
        readiness_score=outcome.readiness_score,
        composite_score=outcome.composite_score,
        threshold_score=outcome.threshold_score,
        trend_score=outcome.trend_score,
        participation_score=outcome.participation_score,
        liquidity_score=outcome.liquidity_score,
        stability_score=outcome.stability_score,
        blocked_reasons=outcome.blocked_reasons,
        decision_reason=outcome.decision_reason,
        payload=payload,
    )


def _append_block_reason(outcome: StrategyOutcome, reason: str) -> StrategyOutcome:
    reasons = tuple(dict.fromkeys([*outcome.blocked_reasons, reason]))
    return StrategyOutcome(
        strategy_name=outcome.strategy_name,
        direction=outcome.direction,
        status="blocked",
        readiness_score=min(outcome.readiness_score, outcome.threshold_score),
        composite_score=outcome.composite_score,
        threshold_score=outcome.threshold_score,
        trend_score=outcome.trend_score,
        participation_score=outcome.participation_score,
        liquidity_score=outcome.liquidity_score,
        stability_score=outcome.stability_score,
        blocked_reasons=reasons,
        decision_reason=reasons[0],
        payload=outcome.payload,
    )


def _latest_feature_snapshot(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str,
) -> FeatureSnapshot | None:
    return (
        db.query(FeatureSnapshot)
        .filter(
            FeatureSnapshot.asset_class == asset_class,
            FeatureSnapshot.symbol == symbol,
            FeatureSnapshot.timeframe == timeframe,
        )
        .order_by(FeatureSnapshot.candle_timestamp.desc())
        .first()
    )


def _recent_candles(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str,
    limit: int,
) -> list[Candle]:
    rows = (
        db.query(Candle)
        .filter(
            Candle.asset_class == asset_class,
            Candle.symbol == symbol,
            Candle.timeframe == timeframe,
        )
        .order_by(Candle.timestamp.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


def _coerce_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _upsert_strategy_sync_state(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    timeframe: str,
    last_computed_at: datetime,
    last_candidate_at: datetime | None,
    candidate_count: int,
    ready_count: int,
    blocked_count: int,
    regime: str | None,
    entry_policy: str | None,
    last_status: str,
    last_error: str | None,
) -> StrategySyncState:
    record = get_strategy_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        record = StrategySyncState(
            asset_class=asset_class,
            venue=venue,
            timeframe=timeframe,
        )
        db.add(record)

    record.venue = venue
    record.last_computed_at = ensure_utc(last_computed_at)
    record.last_candidate_at = ensure_utc(last_candidate_at)
    record.candidate_count = candidate_count
    record.ready_count = ready_count
    record.blocked_count = blocked_count
    record.regime = regime
    record.entry_policy = entry_policy
    record.last_status = last_status
    record.last_error = last_error
    return record
