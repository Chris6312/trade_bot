from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.models.core import Candle, UniverseRun
from backend.app.schemas.core import UniverseConstituentRead, UniverseRunRead
from backend.app.services.universe_service import get_universe_run, trading_date_for_now

router = APIRouter(prefix="/universe", tags=["universe"])
VALID_ASSET_CLASSES = {"stock", "crypto"}
UNIVERSE_PRICE_TIMEFRAME_PRIORITY = {
    "stock": ("5m", "15m", "1h", "1d"),
    "crypto": ("15m", "1h", "4h", "1d"),
}
UNIVERSE_STATS_LOOKBACK_DAYS = {
    "stock": 7,
    "crypto": 3,
}


@router.get("/{asset_class}/current", response_model=list[UniverseConstituentRead])
def get_current_universe(
    asset_class: str,
    trade_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[UniverseConstituentRead]:
    _validate_asset_class(asset_class)
    target_trade_date = trade_date or trading_date_for_now(None)
    record = get_universe_run(db, asset_class=asset_class, trade_date=target_trade_date)
    if record is None or record.status != "resolved":
        return []

    ordered_constituents = sorted(record.constituents, key=lambda row: (row.rank, row.symbol))
    symbols = [row.symbol for row in ordered_constituents]
    candle_stats = _latest_candle_stats_by_symbol(db, asset_class=asset_class, symbols=symbols)
    enriched_rows: list[UniverseConstituentRead] = []
    for row in ordered_constituents:
        payload = dict(row.payload or {})
        stats = candle_stats.get(row.symbol, {})
        if stats:
            payload.setdefault("last_price", stats.get("last_price"))
            payload.setdefault("change_pct", stats.get("change_pct"))
            payload.setdefault("last_candle_at", stats.get("last_candle_at"))
            payload.setdefault("change_window", stats.get("change_window"))
            payload.setdefault("price_timeframe", stats.get("price_timeframe"))

        enriched_rows.append(
            UniverseConstituentRead(
                id=row.id,
                universe_run_id=row.universe_run_id,
                asset_class=row.asset_class,
                venue=row.venue,
                symbol=row.symbol,
                rank=row.rank,
                source=row.source,
                selection_reason=row.selection_reason,
                payload=payload,
            )
        )
    return enriched_rows


@router.get("/{asset_class}/run", response_model=UniverseRunRead)
def get_current_universe_run(
    asset_class: str,
    trade_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> UniverseRunRead:
    _validate_asset_class(asset_class)
    target_trade_date = trade_date or trading_date_for_now(None)
    record: UniverseRun | None = get_universe_run(db, asset_class=asset_class, trade_date=target_trade_date)
    if record is None:
        raise HTTPException(status_code=404, detail="Universe run not found")
    return UniverseRunRead.model_validate(record)


def _latest_candle_stats_by_symbol(db: Session, *, asset_class: str, symbols: list[str]) -> dict[str, dict[str, object]]:
    if not symbols:
        return {}

    timeframe_priority = UNIVERSE_PRICE_TIMEFRAME_PRIORITY.get(asset_class, ("1h", "1d"))
    lookback_days = UNIVERSE_STATS_LOOKBACK_DAYS.get(asset_class, 3)
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

    rows = (
        db.query(Candle.symbol, Candle.timeframe, Candle.timestamp, Candle.close)
        .filter(
            Candle.asset_class == asset_class,
            Candle.symbol.in_(symbols),
            Candle.timeframe.in_(timeframe_priority),
            Candle.timestamp >= cutoff,
        )
        .order_by(Candle.symbol.asc(), Candle.timeframe.asc(), Candle.timestamp.desc())
        .all()
    )

    grouped: dict[str, dict[str, list[object]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        grouped[row.symbol][row.timeframe].append(row)

    stats: dict[str, dict[str, object]] = {}
    for symbol in symbols:
        by_timeframe = grouped.get(symbol, {})
        latest = _select_preferred_price_entry(by_timeframe, timeframe_priority)
        if latest is None or latest.close is None:
            continue

        latest_close = float(latest.close)
        change_pct = _resolve_change_pct(by_timeframe, latest)
        stats[symbol] = {
            "last_price": latest_close,
            "change_pct": change_pct,
            "last_candle_at": latest.timestamp,
            "change_window": "24h" if change_pct is not None else None,
            "price_timeframe": latest.timeframe,
        }

    return stats


def _select_preferred_price_entry(by_timeframe: dict[str, list[object]], timeframe_priority: tuple[str, ...]) -> object | None:
    for timeframe in timeframe_priority:
        entries = by_timeframe.get(timeframe, [])
        if entries:
            return entries[0]

    for entries in by_timeframe.values():
        if entries:
            return entries[0]
    return None


def _resolve_change_pct(by_timeframe: dict[str, list[object]], latest: object) -> float | None:
    latest_close = getattr(latest, "close", None)
    if latest_close in {None, 0}:
        return None

    timeframe_rows = list(by_timeframe.get(latest.timeframe, []))
    baseline = _find_rolling_baseline(timeframe_rows, latest.timestamp, min_age=timedelta(hours=18), max_age=timedelta(hours=36))

    if baseline is None and latest.timeframe != "1d":
        daily_rows = list(by_timeframe.get("1d", []))
        baseline = _find_rolling_baseline(daily_rows, latest.timestamp, min_age=timedelta(hours=12), max_age=timedelta(hours=60))
        if baseline is None:
            baseline = _find_previous_entry(daily_rows, latest.timestamp, max_age=timedelta(days=2))

    if baseline is None:
        baseline = _find_previous_entry(timeframe_rows, latest.timestamp, max_age=_max_previous_entry_age(latest.timeframe))
    if baseline is None or baseline.close in {None, 0}:
        return None

    latest_value = float(latest_close)
    baseline_value = float(baseline.close)
    if baseline_value == 0:
        return None
    return ((latest_value - baseline_value) / baseline_value) * 100


def _find_rolling_baseline(
    entries: list[object],
    latest_timestamp: datetime,
    *,
    min_age: timedelta,
    max_age: timedelta,
) -> object | None:
    if not entries:
        return None

    target = latest_timestamp - timedelta(hours=24)
    candidates = [
        entry
        for entry in entries
        if entry.close not in {None, 0}
        and min_age <= (latest_timestamp - entry.timestamp) <= max_age
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda entry: abs((entry.timestamp - target).total_seconds()))


def _find_previous_entry(entries: list[object], latest_timestamp: datetime, *, max_age: timedelta | None = None) -> object | None:
    for entry in entries[1:]:
        if entry.close in {None, 0}:
            continue
        if max_age is not None and (latest_timestamp - entry.timestamp) > max_age:
            continue
        return entry
    return None


def _max_previous_entry_age(timeframe: str) -> timedelta:
    return {
        "5m": timedelta(hours=2),
        "15m": timedelta(hours=6),
        "1h": timedelta(hours=12),
        "4h": timedelta(hours=24),
        "1d": timedelta(days=3),
    }.get(timeframe, timedelta(hours=12))


def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
