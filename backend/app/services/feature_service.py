from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import fmean, pstdev
from typing import Any, Iterable

from sqlalchemy.orm import Session

from backend.app.models.core import Candle, FeatureSnapshot, FeatureSyncState
from backend.app.services.candle_service import ensure_utc, list_candles

SINGLE_FEATURE_WRITER = "feature_worker"
DEFAULT_SMA_PERIOD = 20
DEFAULT_EMA_PERIOD = 20
DEFAULT_ATR_PERIOD = 14
DEFAULT_VOLATILITY_PERIOD = 20


@dataclass(slots=True, frozen=True)
class ComputedFeatureRow:
    asset_class: str
    venue: str
    source: str
    symbol: str
    timeframe: str
    candle_timestamp: datetime
    computed_at: datetime
    close: float
    volume: float
    price_return_1: float | None
    sma_20: float | None
    ema_20: float | None
    momentum_20: float | None
    volume_sma_20: float | None
    relative_volume_20: float | None
    dollar_volume: float | None
    dollar_volume_sma_20: float | None
    atr_14: float | None
    realized_volatility_20: float | None
    trend_slope_20: float | None
    payload: dict[str, Any]


@dataclass(slots=True, frozen=True)
class FeaturePersistenceSummary:
    asset_class: str
    timeframe: str
    symbol: str
    upserted_rows: int
    last_candle_at: datetime | None
    last_computed_at: datetime | None
    skipped_reason: str | None = None


def ensure_single_feature_writer(writer_name: str) -> None:
    if writer_name != SINGLE_FEATURE_WRITER:
        raise PermissionError(
            f"{writer_name!r} is not allowed to write feature rows. "
            f"Only {SINGLE_FEATURE_WRITER!r} may persist computed features.",
        )


def list_feature_snapshots(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str,
) -> list[FeatureSnapshot]:
    return (
        db.query(FeatureSnapshot)
        .filter(
            FeatureSnapshot.asset_class == asset_class,
            FeatureSnapshot.symbol == symbol,
            FeatureSnapshot.timeframe == timeframe,
        )
        .order_by(FeatureSnapshot.candle_timestamp.asc())
        .all()
    )


def get_latest_feature_snapshot(
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


def get_feature_sync_state(
    db: Session,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str,
) -> FeatureSyncState | None:
    return (
        db.query(FeatureSyncState)
        .filter(
            FeatureSyncState.asset_class == asset_class,
            FeatureSyncState.symbol == symbol,
            FeatureSyncState.timeframe == timeframe,
        )
        .one_or_none()
    )


def compute_feature_rows_from_candles(
    *,
    asset_class: str,
    venue: str,
    source: str,
    symbol: str,
    timeframe: str,
    candles: Iterable[Candle],
    computed_at: datetime | None = None,
    sma_period: int = DEFAULT_SMA_PERIOD,
    ema_period: int = DEFAULT_EMA_PERIOD,
    atr_period: int = DEFAULT_ATR_PERIOD,
    volatility_period: int = DEFAULT_VOLATILITY_PERIOD,
) -> list[ComputedFeatureRow]:
    candle_rows = sorted(candles, key=lambda row: ensure_utc(row.timestamp) or datetime.min.replace(tzinfo=UTC))
    if not candle_rows:
        return []

    closes = [float(row.close) for row in candle_rows]
    highs = [float(row.high) for row in candle_rows]
    lows = [float(row.low) for row in candle_rows]
    volumes = [float(row.volume) for row in candle_rows]
    timestamps = [ensure_utc(row.timestamp) or datetime.now(UTC) for row in candle_rows]
    dollar_volumes = [close * volume for close, volume in zip(closes, volumes, strict=False)]

    computed_time = ensure_utc(computed_at) or datetime.now(UTC)
    min_index = max(sma_period, ema_period, atr_period, volatility_period) - 1
    if len(candle_rows) <= min_index:
        return []

    true_ranges: list[float] = []
    for index, (high, low, close) in enumerate(zip(highs, lows, closes, strict=False)):
        if index == 0:
            true_ranges.append(high - low)
            continue
        previous_close = closes[index - 1]
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))

    ema_seed_cache: dict[int, float] = {}
    rows: list[ComputedFeatureRow] = []
    for index in range(min_index, len(candle_rows)):
        close = closes[index]
        volume = volumes[index]
        timestamp = timestamps[index]
        close_window = closes[index - (sma_period - 1) : index + 1]
        volume_window = volumes[index - (sma_period - 1) : index + 1]
        dollar_window = dollar_volumes[index - (sma_period - 1) : index + 1]
        tr_window = true_ranges[index - (atr_period - 1) : index + 1]

        sma_20 = fmean(close_window)
        ema_20 = _ema_at_index(closes=closes, index=index, period=ema_period, seed_cache=ema_seed_cache)
        volume_sma_20 = fmean(volume_window)
        dollar_volume = dollar_volumes[index]
        dollar_volume_sma_20 = fmean(dollar_window)
        relative_volume_20 = volume / volume_sma_20 if volume_sma_20 else None
        atr_14 = fmean(tr_window)
        price_return_1 = None
        if index > 0 and closes[index - 1] != 0:
            price_return_1 = (close / closes[index - 1]) - 1.0
        momentum_20 = None
        if closes[index - (sma_period - 1)] != 0:
            momentum_20 = (close / closes[index - (sma_period - 1)]) - 1.0
        realized_volatility_20 = _window_realized_volatility(close_window)
        trend_slope_20 = _normalized_slope(close_window)

        payload = {
            "close_window_size": len(close_window),
            "volume_window_size": len(volume_window),
            "atr_window_size": len(tr_window),
            "volatility_window_size": len(close_window),
        }

        rows.append(
            ComputedFeatureRow(
                asset_class=asset_class,
                venue=venue,
                source=source,
                symbol=symbol,
                timeframe=timeframe,
                candle_timestamp=timestamp,
                computed_at=computed_time,
                close=close,
                volume=volume,
                price_return_1=price_return_1,
                sma_20=sma_20,
                ema_20=ema_20,
                momentum_20=momentum_20,
                volume_sma_20=volume_sma_20,
                relative_volume_20=relative_volume_20,
                dollar_volume=dollar_volume,
                dollar_volume_sma_20=dollar_volume_sma_20,
                atr_14=atr_14,
                realized_volatility_20=realized_volatility_20,
                trend_slope_20=trend_slope_20,
                payload=payload,
            )
        )

    return rows


def rebuild_feature_snapshots_for_symbol(
    db: Session,
    *,
    writer_name: str,
    asset_class: str,
    venue: str,
    source: str,
    symbol: str,
    timeframe: str,
    computed_at: datetime | None = None,
) -> FeaturePersistenceSummary:
    ensure_single_feature_writer(writer_name)
    candles = list_candles(db, asset_class=asset_class, symbol=symbol, timeframe=timeframe)
    computed_time = ensure_utc(computed_at) or datetime.now(UTC)
    rows = compute_feature_rows_from_candles(
        asset_class=asset_class,
        venue=venue,
        source=source,
        symbol=symbol,
        timeframe=timeframe,
        candles=candles,
        computed_at=computed_time,
    )

    if not candles:
        _upsert_feature_sync_state(
            db,
            asset_class=asset_class,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,
            last_computed_at=computed_time,
            last_candle_at=None,
            feature_count=0,
            last_status="no_candles",
            last_error=None,
        )
        db.commit()
        return FeaturePersistenceSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            symbol=symbol,
            upserted_rows=0,
            last_candle_at=None,
            last_computed_at=computed_time,
            skipped_reason="no_candles",
        )

    if not rows:
        last_candle_at = ensure_utc(candles[-1].timestamp)
        _upsert_feature_sync_state(
            db,
            asset_class=asset_class,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,
            last_computed_at=computed_time,
            last_candle_at=last_candle_at,
            feature_count=0,
            last_status="insufficient_candles",
            last_error=None,
        )
        db.commit()
        return FeaturePersistenceSummary(
            asset_class=asset_class,
            timeframe=timeframe,
            symbol=symbol,
            upserted_rows=0,
            last_candle_at=last_candle_at,
            last_computed_at=computed_time,
            skipped_reason="insufficient_candles",
        )

    upserted = 0
    for row in rows:
        existing = (
            db.query(FeatureSnapshot)
            .filter(
                FeatureSnapshot.asset_class == asset_class,
                FeatureSnapshot.symbol == symbol,
                FeatureSnapshot.timeframe == timeframe,
                FeatureSnapshot.candle_timestamp == row.candle_timestamp,
            )
            .one_or_none()
        )
        if existing is None:
            existing = FeatureSnapshot(
                asset_class=row.asset_class,
                venue=row.venue,
                source=row.source,
                symbol=row.symbol,
                timeframe=row.timeframe,
                candle_timestamp=row.candle_timestamp,
            )
            db.add(existing)

        existing.venue = row.venue
        existing.source = row.source
        existing.computed_at = row.computed_at
        existing.close = row.close
        existing.volume = row.volume
        existing.price_return_1 = row.price_return_1
        existing.sma_20 = row.sma_20
        existing.ema_20 = row.ema_20
        existing.momentum_20 = row.momentum_20
        existing.volume_sma_20 = row.volume_sma_20
        existing.relative_volume_20 = row.relative_volume_20
        existing.dollar_volume = row.dollar_volume
        existing.dollar_volume_sma_20 = row.dollar_volume_sma_20
        existing.atr_14 = row.atr_14
        existing.realized_volatility_20 = row.realized_volatility_20
        existing.trend_slope_20 = row.trend_slope_20
        existing.payload = row.payload
        upserted += 1

    last_candle_at = rows[-1].candle_timestamp
    _upsert_feature_sync_state(
        db,
        asset_class=asset_class,
        venue=venue,
        symbol=symbol,
        timeframe=timeframe,
        last_computed_at=computed_time,
        last_candle_at=last_candle_at,
        feature_count=len(rows),
        last_status="synced",
        last_error=None,
    )
    db.commit()
    return FeaturePersistenceSummary(
        asset_class=asset_class,
        timeframe=timeframe,
        symbol=symbol,
        upserted_rows=upserted,
        last_candle_at=last_candle_at,
        last_computed_at=computed_time,
    )


def _upsert_feature_sync_state(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    symbol: str,
    timeframe: str,
    last_computed_at: datetime | None,
    last_candle_at: datetime | None,
    feature_count: int,
    last_status: str,
    last_error: str | None,
) -> FeatureSyncState:
    state = get_feature_sync_state(db, asset_class=asset_class, symbol=symbol, timeframe=timeframe)
    if state is None:
        state = FeatureSyncState(
            asset_class=asset_class,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,
        )
        db.add(state)

    state.venue = venue
    state.last_computed_at = ensure_utc(last_computed_at)
    state.last_candle_at = ensure_utc(last_candle_at)
    state.feature_count = feature_count
    state.last_status = last_status
    state.last_error = last_error
    return state


def _ema_at_index(*, closes: list[float], index: int, period: int, seed_cache: dict[int, float]) -> float:
    seed_index = period - 1
    if index < seed_index:
        raise ValueError("EMA cannot be computed before seed index")

    if seed_index not in seed_cache:
        seed_cache[seed_index] = fmean(closes[:period])

    multiplier = 2.0 / (period + 1.0)
    ema_value = seed_cache[seed_index]
    for value_index in range(seed_index + 1, index + 1):
        ema_value = ((closes[value_index] - ema_value) * multiplier) + ema_value
    return ema_value


def _window_realized_volatility(close_window: list[float]) -> float | None:
    returns: list[float] = []
    for previous_close, close in zip(close_window, close_window[1:], strict=False):
        if previous_close == 0:
            continue
        returns.append((close / previous_close) - 1.0)
    if len(returns) < 2:
        return None
    return pstdev(returns)


def _normalized_slope(close_window: list[float]) -> float | None:
    if len(close_window) < 2:
        return None
    avg_close = fmean(close_window)
    if math.isclose(avg_close, 0.0):
        return None
    x_values = list(range(len(close_window)))
    x_mean = fmean(x_values)
    y_mean = fmean(close_window)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, close_window, strict=False))
    denominator = sum((x - x_mean) ** 2 for x in x_values)
    if math.isclose(denominator, 0.0):
        return None
    slope = numerator / denominator
    return slope / avg_close
