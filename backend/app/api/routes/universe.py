from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.core.config import get_settings
from backend.app.models.core import AiResearchPick, Candle, StrategySnapshot, UniverseRun
from backend.app.schemas.core import UniverseConstituentRead, UniverseRunRead
from backend.app.services.universe_service import get_universe_run, trading_date_for_now
from backend.app.workers.ai_research_worker import AiResearchWorker
from backend.app.workers.universe_worker import UniverseWorker

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


@router.post("/stock/ai-research/trigger", status_code=200)
def trigger_ai_research_scan(
    db: Session = Depends(get_db),
) -> dict:
    """Force-run the premarket AI research scan immediately, bypassing the
    08:40–09:00 ET time window guard.  Seeds ``ai_research_picks`` for today,
    then re-resolves the stock universe from those picks.

    Use this when:
    - The bot started after 09:00 ET and the scan was skipped
    - You want to refresh picks mid-day with updated market context
    - Testing the AI research pipeline end-to-end
    """
    settings = get_settings()
    now = datetime.now(UTC)
    trade_date = trading_date_for_now(now)

    # 1. Run the AI research scan (force=True bypasses time-window guard)
    ai_worker = AiResearchWorker(db, settings=settings)
    ai_summary = ai_worker.run_if_due(now=now, force=True)

    if ai_summary.status == "failed":
        raise HTTPException(
            status_code=502,
            detail=f"AI research scan failed: {ai_summary.error}",
        )

    # 2. Re-resolve the stock universe from today's picks
    universe_worker = UniverseWorker(db, settings=settings)
    universe_summary = universe_worker.resolve_stock_universe(now=now, force=True)

    # 3. Return a summary the UI can display
    picks = (
        db.query(AiResearchPick)
        .filter(AiResearchPick.trade_date == trade_date.isoformat())
        .order_by(AiResearchPick.is_bonus_pick.asc(), AiResearchPick.id.asc())
        .all()
    )

    return {
        "status": ai_summary.status,
        "trade_date": ai_summary.trade_date,
        "pick_count": ai_summary.pick_count,
        "venue": ai_summary.venue,
        "universe_source": universe_summary.source,
        "universe_symbol_count": len(universe_summary.symbols),
        "universe_symbols": list(universe_summary.symbols),
        "picks": [
            {
                "symbol": p.symbol,
                "catalyst": p.catalyst,
                "approximate_price": float(p.approximate_price) if p.approximate_price else None,
                "entry_zone_low": float(p.entry_zone_low) if p.entry_zone_low else None,
                "entry_zone_high": float(p.entry_zone_high) if p.entry_zone_high else None,
                "stop_loss": float(p.stop_loss) if p.stop_loss else None,
                "take_profit_primary": float(p.take_profit_primary) if p.take_profit_primary else None,
                "take_profit_stretch": float(p.take_profit_stretch) if p.take_profit_stretch else None,
                "use_trail_stop": p.use_trail_stop,
                "risk_reward_note": p.risk_reward_note,
                "is_bonus_pick": p.is_bonus_pick,
            }
            for p in picks
        ],
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
        best_row_reasons = [str(reason) for reason in (best_row.blocked_reasons or []) if str(reason)]
        eligibility = _classify_universe_eligibility(best_row)
        if eligibility == "Eligible":
            block_reason = None
        else:
            block_reason = ", ".join(best_row_reasons) if best_row_reasons else best_row.decision_reason
            if not block_reason and eligibility == "Blocked by Regime":
                block_reason = "regime_blocked"
            if not block_reason and eligibility == "Not Ready":
                block_reason = "awaiting_signal_quality"

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


def _classify_universe_eligibility(best_row: StrategySnapshot) -> str:
    status = (best_row.status or "").lower()
    if status == "ready":
        return "Eligible"
    if _is_regime_blocked(best_row):
        return "Blocked by Regime"
    if _is_near_ready(best_row):
        return "Near Ready"
    return "Not Ready"


def _is_regime_blocked(row: StrategySnapshot) -> bool:
    reasons = {str(reason).lower() for reason in (row.blocked_reasons or []) if str(reason)}
    decision = str(row.decision_reason or "").lower()
    entry_policy = str(row.entry_policy or "").lower()
    regime = str(row.regime or "").lower()
    status = str(row.status or "").lower()
    return (
        "regime_blocked" in reasons
        or decision == "regime_blocked"
        or entry_policy == "blocked"
        or (status == "blocked" and regime == "risk_off")
    )


def _is_near_ready(row: StrategySnapshot) -> bool:
    reasons = {str(reason).lower() for reason in (row.blocked_reasons or []) if str(reason)}
    severe_reasons = {
        "missing_feature_snapshot",
        "insufficient_candles",
        "vwap_missing",
        "regime_unavailable",
        "strategy_disabled",
    }
    if reasons & severe_reasons:
        return False

    readiness = float(row.readiness_score or 0)
    threshold = float(row.threshold_score or 0)
    if threshold > 0:
        return readiness >= max(0.6, threshold - 0.03)
    return readiness >= 0.65



def _strategy_priority_key(row: StrategySnapshot) -> tuple[int, float, float, datetime, int]:
    return (
        1 if (row.status or "").lower() == "ready" else 0,
        float(row.readiness_score or 0),
        float(row.composite_score or 0),
        row.candidate_timestamp,
        row.id,
    )



def _decimal_to_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")