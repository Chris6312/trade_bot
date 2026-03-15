from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.models.core import Candle, UniverseRun
from backend.app.schemas.core import UniverseConstituentRead, UniverseRunRead
from backend.app.services.universe_service import get_universe_run, trading_date_for_now

router = APIRouter(prefix="/universe", tags=["universe"])
VALID_ASSET_CLASSES = {"stock", "crypto"}


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

    symbols = [row.symbol for row in record.constituents]
    candle_stats = _latest_candle_stats_by_symbol(db, asset_class=asset_class, symbols=symbols, timeframe="1h")
    enriched_rows: list[UniverseConstituentRead] = []
    for row in record.constituents:
        payload = dict(row.payload or {})
        stats = candle_stats.get(row.symbol, {})
        if stats:
            payload.setdefault("last_price", stats.get("last_price"))
            payload.setdefault("change_pct", stats.get("change_pct"))
            payload.setdefault("last_candle_at", stats.get("last_candle_at"))

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


def _latest_candle_stats_by_symbol(db: Session, *, asset_class: str, symbols: list[str], timeframe: str) -> dict[str, dict[str, object]]:
    if not symbols:
        return {}

    ranked = (
        db.query(
            Candle.symbol.label("symbol"),
            Candle.timestamp.label("timestamp"),
            Candle.close.label("close"),
            func.row_number().over(partition_by=Candle.symbol, order_by=Candle.timestamp.desc()).label("row_number"),
        )
        .filter(
            Candle.asset_class == asset_class,
            Candle.timeframe == timeframe,
            Candle.symbol.in_(symbols),
        )
        .subquery()
    )

    rows = (
        db.query(ranked.c.symbol, ranked.c.timestamp, ranked.c.close, ranked.c.row_number)
        .filter(ranked.c.row_number <= 2)
        .order_by(ranked.c.symbol.asc(), ranked.c.row_number.asc())
        .all()
    )

    grouped: dict[str, list[object]] = {}
    for row in rows:
        grouped.setdefault(row.symbol, []).append(row)

    stats: dict[str, dict[str, object]] = {}
    for symbol, entries in grouped.items():
        latest = next((entry for entry in entries if entry.row_number == 1), None)
        previous = next((entry for entry in entries if entry.row_number == 2), None)
        if latest is None or latest.close is None:
            continue

        latest_close = float(latest.close)
        change_pct = None
        if previous is not None and previous.close not in {None, 0}:
            previous_close = float(previous.close)
            if previous_close != 0:
                change_pct = ((latest_close - previous_close) / previous_close) * 100

        stats[symbol] = {
            "last_price": latest_close,
            "change_pct": change_pct,
            "last_candle_at": latest.timestamp,
        }

    return stats


def _validate_asset_class(asset_class: str) -> None:
    if asset_class not in VALID_ASSET_CLASSES:
        raise HTTPException(status_code=404, detail="Asset class not supported")
