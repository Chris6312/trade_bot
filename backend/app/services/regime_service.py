from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import fmean
from typing import Any, Iterable

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from backend.app.models.core import FeatureSnapshot, RegimeSnapshot, RegimeSyncState
from backend.app.services.candle_service import ensure_utc

SINGLE_REGIME_WRITER = "regime_worker"
REGIME_BULL = "bull"
REGIME_NEUTRAL = "neutral"
REGIME_RISK_OFF = "risk_off"
REGIME_ENTRY_POLICY = {
    REGIME_BULL: "full",
    REGIME_NEUTRAL: "reduced",
    REGIME_RISK_OFF: "blocked",
}
REGIME_BENCHMARKS = {
    "stock": ("SPY", "QQQ"),
    "crypto": ("XBTUSD", "ETHUSD"),
}
REGIME_VOLATILITY_THRESHOLDS = {
    "stock": 0.02,
    "crypto": 0.04,
}


@dataclass(slots=True, frozen=True)
class ComputedRegimeRow:
    asset_class: str
    venue: str
    source: str
    timeframe: str
    regime_timestamp: datetime
    computed_at: datetime
    regime: str
    entry_policy: str
    symbol_count: int
    bull_score: float
    breadth_ratio: float
    benchmark_support_ratio: float
    participation_ratio: float
    volatility_support_ratio: float
    payload: dict[str, Any]


@dataclass(slots=True, frozen=True)
class RegimePersistenceSummary:
    asset_class: str
    timeframe: str
    regime: str | None
    entry_policy: str | None
    snapshot_count: int
    symbol_count: int
    regime_timestamp: datetime | None
    last_computed_at: datetime | None
    skipped_reason: str | None = None


@dataclass(slots=True, frozen=True)
class RegimeFreshness:
    is_stale: bool
    stale_reason: str | None
    latest_feature_at: datetime | None
    regime_timestamp: datetime | None
    feature_lag_seconds: int


def ensure_single_regime_writer(writer_name: str) -> None:
    if writer_name != SINGLE_REGIME_WRITER:
        raise PermissionError(
            f"{writer_name!r} is not allowed to write regime rows. "
            f"Only {SINGLE_REGIME_WRITER!r} may persist computed regime state.",
        )


def list_regime_snapshots(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> list[RegimeSnapshot]:
    return (
        db.query(RegimeSnapshot)
        .filter(
            RegimeSnapshot.asset_class == asset_class,
            RegimeSnapshot.timeframe == timeframe,
        )
        .order_by(RegimeSnapshot.regime_timestamp.asc())
        .all()
    )


def get_latest_regime_snapshot(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> RegimeSnapshot | None:
    return (
        db.query(RegimeSnapshot)
        .filter(
            RegimeSnapshot.asset_class == asset_class,
            RegimeSnapshot.timeframe == timeframe,
        )
        .order_by(RegimeSnapshot.regime_timestamp.desc())
        .first()
    )


def get_regime_sync_state(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> RegimeSyncState | None:
    return (
        db.query(RegimeSyncState)
        .filter(
            RegimeSyncState.asset_class == asset_class,
            RegimeSyncState.timeframe == timeframe,
        )
        .one_or_none()
    )


def list_latest_feature_snapshots_for_symbols(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
    symbols: Iterable[str],
) -> list[FeatureSnapshot]:
    requested_symbols = tuple(dict.fromkeys(str(symbol) for symbol in symbols if str(symbol)))
    if not requested_symbols:
        return []

    latest_per_symbol = (
        db.query(
            FeatureSnapshot.symbol.label("symbol"),
            func.max(FeatureSnapshot.candle_timestamp).label("latest_candle_timestamp"),
        )
        .filter(
            FeatureSnapshot.asset_class == asset_class,
            FeatureSnapshot.timeframe == timeframe,
            FeatureSnapshot.symbol.in_(requested_symbols),
        )
        .group_by(FeatureSnapshot.symbol)
        .subquery()
    )

    return (
        db.query(FeatureSnapshot)
        .join(
            latest_per_symbol,
            and_(
                FeatureSnapshot.symbol == latest_per_symbol.c.symbol,
                FeatureSnapshot.candle_timestamp == latest_per_symbol.c.latest_candle_timestamp,
            ),
        )
        .filter(
            FeatureSnapshot.asset_class == asset_class,
            FeatureSnapshot.timeframe == timeframe,
            FeatureSnapshot.symbol.in_(requested_symbols),
        )
        .order_by(FeatureSnapshot.symbol.asc())
        .all()
    )


def get_latest_feature_timestamp(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
    symbols: Iterable[str] | None = None,
) -> datetime | None:
    query = db.query(func.max(FeatureSnapshot.candle_timestamp)).filter(
        FeatureSnapshot.asset_class == asset_class,
        FeatureSnapshot.timeframe == timeframe,
    )
    requested_symbols = tuple(dict.fromkeys(str(symbol) for symbol in (symbols or ()) if str(symbol)))
    if symbols is not None and not requested_symbols:
        return None
    if requested_symbols:
        query = query.filter(FeatureSnapshot.symbol.in_(requested_symbols))
    value = query.scalar()
    return ensure_utc(value)


def evaluate_regime_freshness(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
    symbols: Iterable[str] | None = None,
    regime_snapshot: RegimeSnapshot | None = None,
) -> RegimeFreshness:
    snapshot = regime_snapshot or get_latest_regime_snapshot(db, asset_class=asset_class, timeframe=timeframe)
    regime_timestamp = ensure_utc(snapshot.regime_timestamp) if snapshot is not None else None
    latest_feature_at = get_latest_feature_timestamp(
        db,
        asset_class=asset_class,
        timeframe=timeframe,
        symbols=symbols,
    )
    sync_state = get_regime_sync_state(db, asset_class=asset_class, timeframe=timeframe)

    stale_reason: str | None = None
    if snapshot is None:
        stale_reason = "regime_missing"
    elif sync_state is not None and sync_state.last_status != "synced":
        stale_reason = f"regime_sync_{sync_state.last_status}"
    elif latest_feature_at is not None and regime_timestamp is not None and regime_timestamp < latest_feature_at:
        stale_reason = "features_newer_than_regime"
    elif (
        sync_state is not None
        and ensure_utc(sync_state.last_feature_at) is not None
        and regime_timestamp is not None
        and ensure_utc(sync_state.last_feature_at) > regime_timestamp
    ):
        stale_reason = "sync_state_ahead_of_regime"

    feature_lag_seconds = 0
    if regime_timestamp is not None and latest_feature_at is not None and latest_feature_at > regime_timestamp:
        feature_lag_seconds = int((latest_feature_at - regime_timestamp).total_seconds())

    return RegimeFreshness(
        is_stale=stale_reason is not None,
        stale_reason=stale_reason,
        latest_feature_at=latest_feature_at,
        regime_timestamp=regime_timestamp,
        feature_lag_seconds=feature_lag_seconds,
    )


def get_latest_fresh_regime_snapshot(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
    symbols: Iterable[str] | None = None,
) -> RegimeSnapshot | None:
    snapshot = get_latest_regime_snapshot(db, asset_class=asset_class, timeframe=timeframe)
    freshness = evaluate_regime_freshness(
        db,
        asset_class=asset_class,
        timeframe=timeframe,
        symbols=symbols,
        regime_snapshot=snapshot,
    )
    if freshness.is_stale:
        return None
    return snapshot


def build_regime_current_snapshot(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> dict[str, Any] | None:
    snapshot = get_latest_regime_snapshot(db, asset_class=asset_class, timeframe=timeframe)
    if snapshot is None:
        return None
    freshness = evaluate_regime_freshness(
        db,
        asset_class=asset_class,
        timeframe=timeframe,
        regime_snapshot=snapshot,
    )
    payload = dict(snapshot.payload or {})
    payload.setdefault("is_stale", freshness.is_stale)
    payload.setdefault("stale_reason", freshness.stale_reason)
    payload.setdefault("latest_feature_at", freshness.latest_feature_at.isoformat() if freshness.latest_feature_at else None)
    payload.setdefault("feature_lag_seconds", freshness.feature_lag_seconds)
    return {
        "id": snapshot.id,
        "asset_class": snapshot.asset_class,
        "venue": snapshot.venue,
        "source": snapshot.source,
        "timeframe": snapshot.timeframe,
        "regime_timestamp": snapshot.regime_timestamp,
        "computed_at": snapshot.computed_at,
        "regime": snapshot.regime,
        "entry_policy": snapshot.entry_policy,
        "symbol_count": snapshot.symbol_count,
        "bull_score": snapshot.bull_score,
        "breadth_ratio": snapshot.breadth_ratio,
        "benchmark_support_ratio": snapshot.benchmark_support_ratio,
        "participation_ratio": snapshot.participation_ratio,
        "volatility_support_ratio": snapshot.volatility_support_ratio,
        "payload": payload,
        "is_stale": freshness.is_stale,
        "stale_reason": freshness.stale_reason,
        "latest_feature_at": freshness.latest_feature_at,
        "feature_lag_seconds": freshness.feature_lag_seconds,
    }


def build_regime_sync_snapshot(
    db: Session,
    *,
    asset_class: str,
    timeframe: str,
) -> dict[str, Any] | None:
    record = get_regime_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if record is None:
        return None
    freshness = evaluate_regime_freshness(db, asset_class=asset_class, timeframe=timeframe)
    return {
        "asset_class": record.asset_class,
        "venue": record.venue,
        "timeframe": record.timeframe,
        "last_computed_at": record.last_computed_at,
        "last_feature_at": record.last_feature_at,
        "regime": record.regime,
        "entry_policy": record.entry_policy,
        "symbol_count": record.symbol_count,
        "last_status": record.last_status,
        "last_error": record.last_error,
        "is_stale": freshness.is_stale,
        "stale_reason": freshness.stale_reason,
        "latest_feature_at": freshness.latest_feature_at,
        "feature_lag_seconds": freshness.feature_lag_seconds,
    }


def classify_regime_from_features(
    *,
    asset_class: str,
    venue: str,
    source: str,
    timeframe: str,
    feature_snapshots: Iterable[FeatureSnapshot],
    computed_at: datetime | None = None,
) -> ComputedRegimeRow | None:
    snapshots = sorted(
        feature_snapshots,
        key=lambda row: (
            ensure_utc(row.candle_timestamp) or datetime.min.replace(tzinfo=UTC),
            row.symbol,
        ),
    )
    if not snapshots:
        return None

    computed_time = ensure_utc(computed_at) or datetime.now(UTC)
    valid_snapshots = [
        row
        for row in snapshots
        if row.sma_20 is not None
        and row.ema_20 is not None
        and row.momentum_20 is not None
        and row.relative_volume_20 is not None
        and row.realized_volatility_20 is not None
        and row.trend_slope_20 is not None
    ]
    if not valid_snapshots:
        return None

    breadth_ratio = _share(valid_snapshots, _is_positive_trend)
    benchmark_symbols = set(REGIME_BENCHMARKS.get(asset_class, ()))
    benchmark_rows = [row for row in valid_snapshots if row.symbol in benchmark_symbols]
    benchmark_pool = benchmark_rows or valid_snapshots
    benchmark_support_ratio = _share(benchmark_pool, _is_positive_trend)
    participation_ratio = _share(valid_snapshots, _has_healthy_participation)
    volatility_support_ratio = _share(valid_snapshots, lambda row: _supports_risk(asset_class=asset_class, row=row))

    bull_score = round(
        (breadth_ratio * 0.45)
        + (benchmark_support_ratio * 0.25)
        + (participation_ratio * 0.20)
        + (volatility_support_ratio * 0.10),
        6,
    )

    if bull_score >= 0.67 and breadth_ratio >= 0.55 and benchmark_support_ratio >= 0.50:
        regime = REGIME_BULL
    elif bull_score >= 0.40 and breadth_ratio >= 0.25:
        regime = REGIME_NEUTRAL
    else:
        regime = REGIME_RISK_OFF

    regime_timestamp = max(ensure_utc(row.candle_timestamp) or computed_time for row in valid_snapshots)
    volatility_values = [float(row.realized_volatility_20) for row in valid_snapshots if row.realized_volatility_20 is not None]
    payload = {
        "benchmark_symbols": sorted(benchmark_symbols),
        "contributing_symbols": [row.symbol for row in valid_snapshots],
        "positive_trend_symbols": [row.symbol for row in valid_snapshots if _is_positive_trend(row)],
        "healthy_participation_symbols": [row.symbol for row in valid_snapshots if _has_healthy_participation(row)],
        "low_volatility_symbols": [row.symbol for row in valid_snapshots if _supports_risk(asset_class=asset_class, row=row)],
        "average_realized_volatility_20": round(fmean(volatility_values), 8) if volatility_values else None,
    }
    return ComputedRegimeRow(
        asset_class=asset_class,
        venue=venue,
        source=source,
        timeframe=timeframe,
        regime_timestamp=regime_timestamp,
        computed_at=computed_time,
        regime=regime,
        entry_policy=REGIME_ENTRY_POLICY[regime],
        symbol_count=len(valid_snapshots),
        bull_score=bull_score,
        breadth_ratio=round(breadth_ratio, 6),
        benchmark_support_ratio=round(benchmark_support_ratio, 6),
        participation_ratio=round(participation_ratio, 6),
        volatility_support_ratio=round(volatility_support_ratio, 6),
        payload=payload,
    )


def rebuild_regime_snapshot_for_asset_class(
    db: Session,
    *,
    writer_name: str,
    asset_class: str,
    venue: str,
    source: str,
    symbols: Iterable[str],
    timeframe: str,
    computed_at: datetime | None = None,
) -> RegimePersistenceSummary:
    ensure_single_regime_writer(writer_name)
    computed_time = ensure_utc(computed_at) or datetime.now(UTC)
    requested_symbols = tuple(dict.fromkeys(symbols))
    if not requested_symbols:
        _upsert_regime_sync_state(
            db,
            asset_class=asset_class,
            venue=venue,
            timeframe=timeframe,
            last_computed_at=computed_time,
            last_feature_at=None,
            regime=None,
            entry_policy=None,
            symbol_count=0,
            last_status="universe_unresolved",
            last_error=None,
        )
        db.commit()
        return RegimePersistenceSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            regime=None,
            entry_policy=None,
            snapshot_count=0,
            symbol_count=0,
            regime_timestamp=None,
            last_computed_at=computed_time,
            skipped_reason="universe_unresolved",
        )

    features = list_latest_feature_snapshots_for_symbols(
        db,
        asset_class=asset_class,
        timeframe=timeframe,
        symbols=requested_symbols,
    )
    if not features:
        _upsert_regime_sync_state(
            db,
            asset_class=asset_class,
            venue=venue,
            timeframe=timeframe,
            last_computed_at=computed_time,
            last_feature_at=None,
            regime=None,
            entry_policy=None,
            symbol_count=0,
            last_status="no_features",
            last_error=None,
        )
        db.commit()
        return RegimePersistenceSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            regime=None,
            entry_policy=None,
            snapshot_count=0,
            symbol_count=0,
            regime_timestamp=None,
            last_computed_at=computed_time,
            skipped_reason="no_features",
        )

    computed = classify_regime_from_features(
        asset_class=asset_class,
        venue=venue,
        source=source,
        timeframe=timeframe,
        feature_snapshots=features,
        computed_at=computed_time,
    )
    if computed is None:
        last_feature_at = max(ensure_utc(item.candle_timestamp) for item in features if ensure_utc(item.candle_timestamp) is not None)
        _upsert_regime_sync_state(
            db,
            asset_class=asset_class,
            venue=venue,
            timeframe=timeframe,
            last_computed_at=computed_time,
            last_feature_at=last_feature_at,
            regime=None,
            entry_policy=None,
            symbol_count=len(features),
            last_status="insufficient_features",
            last_error=None,
        )
        db.commit()
        return RegimePersistenceSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            regime=None,
            entry_policy=None,
            snapshot_count=0,
            symbol_count=len(features),
            regime_timestamp=last_feature_at,
            last_computed_at=computed_time,
            skipped_reason="insufficient_features",
        )

    existing = (
        db.query(RegimeSnapshot)
        .filter(
            RegimeSnapshot.asset_class == asset_class,
            RegimeSnapshot.timeframe == timeframe,
            RegimeSnapshot.regime_timestamp == computed.regime_timestamp,
        )
        .one_or_none()
    )
    if existing is None:
        existing = RegimeSnapshot(
            asset_class=computed.asset_class,
            venue=computed.venue,
            source=computed.source,
            timeframe=computed.timeframe,
            regime_timestamp=computed.regime_timestamp,
        )
        db.add(existing)

    existing.venue = computed.venue
    existing.source = computed.source
    existing.computed_at = computed.computed_at
    existing.regime = computed.regime
    existing.entry_policy = computed.entry_policy
    existing.symbol_count = computed.symbol_count
    existing.bull_score = computed.bull_score
    existing.breadth_ratio = computed.breadth_ratio
    existing.benchmark_support_ratio = computed.benchmark_support_ratio
    existing.participation_ratio = computed.participation_ratio
    existing.volatility_support_ratio = computed.volatility_support_ratio
    existing.payload = computed.payload

    _upsert_regime_sync_state(
        db,
        asset_class=asset_class,
        venue=venue,
        timeframe=timeframe,
        last_computed_at=computed.computed_at,
        last_feature_at=computed.regime_timestamp,
        regime=computed.regime,
        entry_policy=computed.entry_policy,
        symbol_count=computed.symbol_count,
        last_status="synced",
        last_error=None,
    )
    db.commit()
    return RegimePersistenceSummary(
        asset_class=asset_class,
        timeframe=timeframe,
        regime=computed.regime,
        entry_policy=computed.entry_policy,
        snapshot_count=1,
        symbol_count=computed.symbol_count,
        regime_timestamp=computed.regime_timestamp,
        last_computed_at=computed.computed_at,
    )


def _upsert_regime_sync_state(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    timeframe: str,
    last_computed_at: datetime | None,
    last_feature_at: datetime | None,
    regime: str | None,
    entry_policy: str | None,
    symbol_count: int,
    last_status: str,
    last_error: str | None,
) -> RegimeSyncState:
    state = get_regime_sync_state(db, asset_class=asset_class, timeframe=timeframe)
    if state is None:
        state = RegimeSyncState(
            asset_class=asset_class,
            venue=venue,
            timeframe=timeframe,
        )
        db.add(state)

    state.venue = venue
    state.last_computed_at = ensure_utc(last_computed_at)
    state.last_feature_at = ensure_utc(last_feature_at)
    state.regime = regime
    state.entry_policy = entry_policy
    state.symbol_count = symbol_count
    state.last_status = last_status
    state.last_error = last_error
    return state


def _is_positive_trend(row: FeatureSnapshot) -> bool:
    close = float(row.close)
    sma_20 = float(row.sma_20)
    ema_20 = float(row.ema_20)
    momentum_20 = float(row.momentum_20)
    trend_slope_20 = float(row.trend_slope_20)
    return close >= sma_20 and close >= ema_20 and momentum_20 > 0 and trend_slope_20 > 0


def _has_healthy_participation(row: FeatureSnapshot) -> bool:
    return float(row.relative_volume_20) >= 0.90


def _supports_risk(*, asset_class: str, row: FeatureSnapshot) -> bool:
    threshold = REGIME_VOLATILITY_THRESHOLDS.get(asset_class, 0.03)
    return float(row.realized_volatility_20) <= threshold


def _share(rows: Iterable[FeatureSnapshot], predicate: Any) -> float:
    materialized = list(rows)
    if not materialized:
        return 0.0
    matched = sum(1 for row in materialized if predicate(row))
    return matched / len(materialized)
