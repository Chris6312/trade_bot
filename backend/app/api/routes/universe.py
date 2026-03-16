from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.models.core import Candle, StrategySnapshot, UniverseRun
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
    "crypto": 4,
}
NY_TZ = ZoneInfo("America/New_York")


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
    strategy_stats = _current_strategy_summary_by_symbol(db, asset_class=asset_class, symbols=symbols)
    enriched_rows: list[UniverseConstituentRead] = []
    for row in ordered_constituents:
        payload = dict(row.payload or {})
        stats = candle_stats.get(row.symbol, {})
        strategy = strategy_stats.get(row.symbol, {})
        if stats:
            for key in ("last_price", "change_pct", "last_candle_at", "change_window", "price_timeframe"):
                if key in stats:
                    payload[key] = stats.get(key)

        if strategy:
            for key, value in strategy.items():
                if value is not None:
                    payload[key] = value

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
    market_data_venue = "kraken" if asset_class == "crypto" else "alpaca"

    rows = (
        db.query(Candle.symbol, Candle.timeframe, Candle.timestamp, Candle.close)
        .filter(
            Candle.asset_class == asset_class,
            Candle.venue == market_data_venue,
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
        change_pct, change_window = _resolve_change_pct(
            asset_class=asset_class,
            by_timeframe=by_timeframe,
            latest=latest,
        )
        stats[symbol] = {
            "last_price": latest_close,
            "change_pct": change_pct,
            "last_candle_at": latest.timestamp,
            "change_window": change_window,
            "price_timeframe": latest.timeframe,
        }

    return stats


def _current_strategy_summary_by_symbol(db: Session, *, asset_class: str, symbols: list[str]) -> dict[str, dict[str, object]]:
    if not symbols:
        return {}

    rows = (
        db.query(StrategySnapshot)
        .filter(
            StrategySnapshot.asset_class == asset_class,
            StrategySnapshot.symbol.in_(symbols),
        )
        .order_by(
            StrategySnapshot.symbol.asc(),
            StrategySnapshot.candidate_timestamp.desc(),
            StrategySnapshot.computed_at.desc(),
            StrategySnapshot.id.desc(),
        )
        .all()
    )

    latest_by_key: dict[tuple[str, str, str], StrategySnapshot] = {}
    for row in rows:
        key = (row.symbol, row.strategy_name, row.timeframe)
        if key not in latest_by_key:
            latest_by_key[key] = row

    grouped: dict[str, list[StrategySnapshot]] = defaultdict(list)
    for row in latest_by_key.values():
        grouped[row.symbol].append(row)

    summaries: dict[str, dict[str, object]] = {}
    for symbol in symbols:
        symbol_rows = grouped.get(symbol, [])
        if not symbol_rows:
            continue

        best_row = max(symbol_rows, key=_strategy_priority_key)
        all_reasons = _dedupe_block_reasons(symbol_rows)
        any_ready = any((row.status or "").lower() == "ready" for row in symbol_rows)
        all_blocked = all((row.status or "").lower() == "blocked" for row in symbol_rows)
        if any_ready:
            eligibility = "Eligible"
            block_reason = None
        elif all_blocked:
            eligibility = "Blocked"
            block_reason = ", ".join(all_reasons) if all_reasons else "all_strategies_blocked"
        else:
            eligibility = "Not ready"
            block_reason = ", ".join(all_reasons) if all_reasons else None

        summaries[symbol] = {
            "eligibility": eligibility,
            "block_reason": block_reason,
            "best_strategy_name": best_row.strategy_name,
            "best_strategy_timeframe": best_row.timeframe,
            "best_strategy_status": best_row.status,
            "last_strategy_evaluated_at": best_row.computed_at,
            "readiness_score": _decimal_to_float(best_row.readiness_score),
            "composite_score": _decimal_to_float(best_row.composite_score),
            "strategy_rank_score": _decimal_to_float(best_row.composite_score),
            "trend_score": _decimal_to_float(best_row.trend_score),
            "participation_score": _decimal_to_float(best_row.participation_score),
            "liquidity_score": _decimal_to_float(best_row.liquidity_score),
            "stability_score": _decimal_to_float(best_row.stability_score),
            "strategy_compatibility": [
                {
                    "strategy_name": row.strategy_name,
                    "timeframe": row.timeframe,
                    "status": row.status,
                    "readiness_score": _decimal_to_float(row.readiness_score),
                    "blocked_reasons": list(row.blocked_reasons or []),
                }
                for row in sorted(symbol_rows, key=_strategy_priority_key, reverse=True)
            ],
        }
    return summaries


def _select_preferred_price_entry(by_timeframe: dict[str, list[object]], timeframe_priority: tuple[str, ...]) -> object | None:
    for timeframe in timeframe_priority:
        entries = by_timeframe.get(timeframe, [])
        if entries:
            return entries[0]

    for entries in by_timeframe.values():
        if entries:
            return entries[0]
    return None


def _resolve_change_pct(*, asset_class: str, by_timeframe: dict[str, list[object]], latest: object) -> tuple[float | None, str | None]:
    latest_close = getattr(latest, "close", None)
    if latest_close in {None, 0}:
        return None, None

    if asset_class == "stock":
        baseline = _find_stock_previous_close(by_timeframe=by_timeframe, latest=latest)
        change_window = "prev_close"
    else:
        if latest.timeframe != "15m":
            return None, None
        baseline = _find_crypto_15m_24h_baseline(by_timeframe=by_timeframe, latest=latest)
        change_window = "24h_15m"

    if baseline is None or baseline.close in {None, 0}:
        return None, None

    latest_value = float(latest_close)
    baseline_value = float(baseline.close)
    if baseline_value == 0:
        return None, None

    change_pct = ((latest_value - baseline_value) / baseline_value) * 100
    if asset_class == "crypto" and abs(change_pct) > 40:
        return None, None

    return change_pct, change_window


def _find_stock_previous_close(*, by_timeframe: dict[str, list[object]], latest: object) -> object | None:
    daily_rows = list(by_timeframe.get("1d", []))
    if not daily_rows:
        return None

    latest_session_date = latest.timestamp.astimezone(NY_TZ).date()
    for entry in daily_rows:
        if entry.close in {None, 0}:
            continue
        entry_session_date = entry.timestamp.astimezone(NY_TZ).date()
        if latest.timeframe == "1d" and entry.timestamp == latest.timestamp:
            continue
        if entry_session_date < latest_session_date:
            return entry
    return None


def _find_crypto_15m_24h_baseline(*, by_timeframe: dict[str, list[object]], latest: object) -> object | None:
    rows_15m = [row for row in by_timeframe.get("15m", []) if row.close not in {None, 0}]
    if len(rows_15m) < 2:
        return None

    target = latest.timestamp - timedelta(hours=24)

    for entry in rows_15m[1:]:
        if entry.timestamp == target:
            return entry

    candidates: list[tuple[timedelta, object]] = []
    for entry in rows_15m[1:]:
        deviation = abs(entry.timestamp - target)
        if deviation <= timedelta(minutes=15):
            candidates.append((deviation, entry))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _find_closest_entry(
    entries: list[object],
    latest_timestamp: datetime,
    *,
    target_age: timedelta,
    max_deviation: timedelta,
) -> object | None:
    if not entries:
        return None

    target = latest_timestamp - target_age
    candidates = []
    for entry in entries[1:]:
        if entry.close in {None, 0}:
            continue
        deviation = abs(entry.timestamp - target)
        if deviation <= max_deviation:
            candidates.append((deviation, entry))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _find_previous_entry(entries: list[object], latest_timestamp: datetime, *, max_age: timedelta | None = None) -> object | None:
    for entry in entries[1:]:
        if entry.close in {None, 0}:
            continue
        if max_age is not None and (latest_timestamp - entry.timestamp) > max_age:
            continue
        return entry
    return None


def _max_24h_deviation(timeframe: str) -> timedelta:
    return {
        "5m": timedelta(minutes=25),
        "15m": timedelta(minutes=45),
        "1h": timedelta(hours=2),
        "4h": timedelta(hours=4),
        "1d": timedelta(hours=18),
    }.get(timeframe, timedelta(hours=2))


def _strategy_priority_key(row: StrategySnapshot) -> tuple[int, float, float, datetime, int]:
    return (
        1 if (row.status or "").lower() == "ready" else 0,
        float(row.readiness_score or 0),
        float(row.composite_score or 0),
        row.candidate_timestamp,
        row.id,
    )


def _dedupe_block_reasons(rows: list[StrategySnapshot]) -> list[str]:
    reasons: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for reason in row.blocked_reasons or []:
            normalized = str(reason)
            if normalized and normalized not in seen:
                reasons.append(normalized)
                seen.add(normalized)
    return reasons


def _decimal_to_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")