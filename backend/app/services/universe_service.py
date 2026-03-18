from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.app.core.config import PROJECT_ROOT
from backend.app.models.core import UniverseConstituent, UniverseRun

ALLOWED_ETFS = {"SPY", "QQQ"}

# ---------------------------------------------------------------------------
# Fallback universe allowlist
# ---------------------------------------------------------------------------
# When the AI research scan fails, the screener fallback is constrained to
# this curated set of the 25 most liquid, large-cap US equities.  Only
# symbols on this list are admitted; screener ordering (by volume) still
# determines rank within the list, so the most active names come first.
# Update periodically as market-cap leaders change.
FALLBACK_UNIVERSE_ALLOWLIST: frozenset[str] = frozenset({
    # Mega-cap tech / AI
    "NVDA", "AAPL", "MSFT", "GOOGL", "META", "AMZN", "TSLA",
    # Semiconductors
    "AMD", "AVGO", "QCOM",
    # Financials
    "JPM", "BAC", "GS", "V", "MA",
    # Healthcare / Pharma
    "UNH", "LLY", "JNJ",
    # Energy / Industrials
    "XOM", "CVX",
    # Consumer / Media
    "WMT", "COST", "NFLX",
    # Allowed ETFs (broad market proxies)
    "SPY", "QQQ",
})

FALLBACK_UNIVERSE_MAX_SIZE = 25
CRYPTO_TOP_15 = (
    {"symbol": "XBTUSD", "display_symbol": "BTC/USD", "display_name": "Bitcoin", "base_asset": "BTC"},
    {"symbol": "ETHUSD", "display_symbol": "ETH/USD", "display_name": "Ethereum", "base_asset": "ETH"},
    {"symbol": "SOLUSD", "display_symbol": "SOL/USD", "display_name": "Solana", "base_asset": "SOL"},
    {"symbol": "XRPUSD", "display_symbol": "XRP/USD", "display_name": "XRP", "base_asset": "XRP"},
    {"symbol": "ADAUSD", "display_symbol": "ADA/USD", "display_name": "Cardano", "base_asset": "ADA"},
    {"symbol": "XDGUSD", "display_symbol": "DOGE/USD", "display_name": "Dogecoin", "base_asset": "DOGE"},
    {"symbol": "AVAXUSD", "display_symbol": "AVAX/USD", "display_name": "Avalanche", "base_asset": "AVAX"},
    {"symbol": "LINKUSD", "display_symbol": "LINK/USD", "display_name": "Chainlink", "base_asset": "LINK"},
    {"symbol": "LTCUSD", "display_symbol": "LTC/USD", "display_name": "Litecoin", "base_asset": "LTC"},
    {"symbol": "DOTUSD", "display_symbol": "DOT/USD", "display_name": "Polkadot", "base_asset": "DOT"},
    {"symbol": "BCHUSD", "display_symbol": "BCH/USD", "display_name": "Bitcoin Cash", "base_asset": "BCH"},
    {"symbol": "TRXUSD", "display_symbol": "TRX/USD", "display_name": "TRON", "base_asset": "TRX"},
    {"symbol": "XLMUSD", "display_symbol": "XLM/USD", "display_name": "Stellar", "base_asset": "XLM"},
    {"symbol": "ATOMUSD", "display_symbol": "ATOM/USD", "display_name": "Cosmos", "base_asset": "ATOM"},
    {"symbol": "NEARUSD", "display_symbol": "NEAR/USD", "display_name": "NEAR Protocol", "base_asset": "NEAR"},
)


@dataclass(slots=True, frozen=True)
class UniverseSymbolRecord:
    symbol: str
    rank: int
    source: str
    venue: str
    asset_class: str
    selection_reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def trading_date_for_now(now: datetime | None) -> date:
    at = ensure_utc(now) or datetime.now(UTC)
    return at.astimezone(ZoneInfo("America/New_York")).date()


def get_universe_run(db: Session, *, asset_class: str, trade_date: date) -> UniverseRun | None:
    return (
        db.query(UniverseRun)
        .filter(
            UniverseRun.asset_class == asset_class,
            UniverseRun.trade_date == trade_date,
        )
        .one_or_none()
    )


def get_latest_resolved_universe_run(db: Session, *, asset_class: str) -> UniverseRun | None:
    return (
        db.query(UniverseRun)
        .filter(
            UniverseRun.asset_class == asset_class,
            UniverseRun.status == "resolved",
        )
        .order_by(UniverseRun.trade_date.desc(), UniverseRun.resolved_at.desc(), UniverseRun.id.desc())
        .first()
    )


def list_latest_universe_symbols(db: Session, *, asset_class: str) -> list[UniverseSymbolRecord]:
    run = get_latest_resolved_universe_run(db, asset_class=asset_class)
    if run is None:
        return []
    return [
        UniverseSymbolRecord(
            symbol=item.symbol,
            rank=item.rank,
            source=item.source,
            venue=item.venue,
            asset_class=item.asset_class,
            selection_reason=item.selection_reason,
            payload=item.payload or {},
        )
        for item in run.constituents
    ]


def list_universe_symbols(db: Session, *, asset_class: str, trade_date: date) -> list[UniverseSymbolRecord]:
    run = get_universe_run(db, asset_class=asset_class, trade_date=trade_date)
    if run is None or run.status != "resolved":
        return []
    return [
        UniverseSymbolRecord(
            symbol=item.symbol,
            rank=item.rank,
            source=item.source,
            venue=item.venue,
            asset_class=item.asset_class,
            selection_reason=item.selection_reason,
            payload=item.payload or {},
        )
        for item in run.constituents
    ]


def persist_universe_run(
    db: Session,
    *,
    asset_class: str,
    venue: str,
    trade_date: date,
    source: str,
    status: str,
    symbols: Iterable[UniverseSymbolRecord],
    snapshot_path: str | None = None,
    resolved_at: datetime | None = None,
    last_error: str | None = None,
    payload: dict[str, Any] | None = None,
) -> UniverseRun:
    run = get_universe_run(db, asset_class=asset_class, trade_date=trade_date)
    if run is None:
        run = UniverseRun(
            asset_class=asset_class,
            venue=venue,
            trade_date=trade_date,
            source=source,
            status=status,
            resolved_at=ensure_utc(resolved_at),
            snapshot_path=snapshot_path,
            last_error=last_error,
            payload=payload,
        )
        db.add(run)
        db.flush()
    else:
        run.venue = venue
        run.source = source
        run.status = status
        run.resolved_at = ensure_utc(resolved_at)
        run.snapshot_path = snapshot_path
        run.last_error = last_error
        run.payload = payload
        run.constituents.clear()
        db.flush()

    for item in symbols:
        run.constituents.append(
            UniverseConstituent(
                asset_class=item.asset_class,
                venue=item.venue,
                symbol=item.symbol,
                rank=item.rank,
                source=item.source,
                selection_reason=item.selection_reason,
                payload=item.payload,
            )
        )

    db.commit()
    db.refresh(run)
    return run


def stock_universe_ready(db: Session, *, trade_date: date) -> bool:
    run = get_universe_run(db, asset_class="stock", trade_date=trade_date)
    return bool(run and run.status == "resolved" and run.constituents)


def default_snapshot_path(*, asset_class: str, trade_date: date) -> Path:
    directory = PROJECT_ROOT / "backups" / "universe_snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{asset_class}_universe_{trade_date.isoformat()}.jsonl"


def write_snapshot(*, path: Path, symbols: Iterable[UniverseSymbolRecord], trade_date: date, resolved_at: datetime) -> str:
    resolved = ensure_utc(resolved_at) or datetime.now(UTC)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for item in symbols:
            row = {
                "symbol": item.symbol,
                "rank": item.rank,
                "source": item.source,
                "venue": item.venue,
                "asset_class": item.asset_class,
                "selection_reason": item.selection_reason,
                "payload": item.payload,
                "trade_date": trade_date.isoformat(),
                "resolved_at": resolved.isoformat(),
            }
            fh.write(json.dumps(row, default=str) + "\n")
    return str(path)


def read_snapshot(*, path: str | Path) -> list[UniverseSymbolRecord]:
    file_path = Path(path)
    if not file_path.exists():
        return []

    records: list[UniverseSymbolRecord] = []
    with file_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").upper()
            if not symbol:
                continue
            records.append(
                UniverseSymbolRecord(
                    symbol=symbol,
                    rank=int(item.get("rank") or len(records) + 1),
                    source=str(item.get("source") or "snapshot"),
                    venue=str(item.get("venue") or "unknown"),
                    asset_class=str(item.get("asset_class") or "stock"),
                    selection_reason=item.get("selection_reason"),
                    payload=item.get("payload") or {},
                )
            )
    return records


def normalize_stock_candidates(
    *,
    candidates: Iterable[dict[str, Any]],
    asset_metadata: dict[str, dict[str, Any]] | None = None,
    max_size: int,
    source: str,
    venue: str = "alpaca",
) -> list[UniverseSymbolRecord]:
    metadata = asset_metadata or {}
    normalized: list[UniverseSymbolRecord] = []
    seen: set[str] = set()

    ordered_candidates = list(candidates)
    ordered_candidates.sort(
        key=lambda item: (
            -float(item.get("ai_rank_score", 0.0) or 0.0),
            -float(item.get("volume", 0.0) or 0.0),
            str(item.get("symbol") or ""),
        )
    )

    # Fallback path: constrain to the curated allowlist and hard-cap at 25.
    # This keeps the bot on highly liquid large-caps when the AI scan is
    # unavailable, ensuring the ATR-based stop/TP logic has clean data.
    if source == "fallback":
        ordered_candidates = [
            c for c in ordered_candidates
            if str(c.get("symbol") or "").upper().strip() in FALLBACK_UNIVERSE_ALLOWLIST
        ]
        max_size = min(max_size, FALLBACK_UNIVERSE_MAX_SIZE)

    for candidate in ordered_candidates:
        symbol = str(candidate.get("symbol") or "").upper().strip()
        if not symbol or symbol in seen:
            continue

        asset = asset_metadata.get(symbol, {}) if asset_metadata else {}
        if not _is_tradable_us_equity(symbol=symbol, candidate=candidate, asset=asset):
            continue
        if _is_excluded_etf(symbol=symbol, candidate=candidate, asset=asset):
            continue

        ai_scored = _candidate_has_ai_ranking(candidate) if source == "ai" else False
        selection_source = _resolve_stock_selection_source(source=source, ai_scored=ai_scored)
        payload = {
            **asset,
            **candidate,
            "ai_scored": ai_scored,
            "selection_source": selection_source,
        }

        seen.add(symbol)
        normalized.append(
            UniverseSymbolRecord(
                symbol=symbol,
                rank=len(normalized) + 1,
                source=source,
                venue=venue,
                asset_class="stock",
                selection_reason=_resolve_stock_selection_reason(
                    candidate=candidate,
                    source=source,
                    ai_scored=ai_scored,
                ),
                payload=payload,
            )
        )
        if len(normalized) >= max_size:
            break

    return normalized


def crypto_universe_records() -> list[UniverseSymbolRecord]:
    return [
        UniverseSymbolRecord(
            symbol=str(item["symbol"]),
            rank=index,
            source="static",
            venue="kraken",
            asset_class="crypto",
            selection_reason="hard_coded_top_15",
            payload={
                "kraken_pair": str(item["symbol"]),
                "display_symbol": str(item["display_symbol"]),
                "display_name": str(item["display_name"]),
                "base_asset": str(item["base_asset"]),
                "quote_asset": "USD",
            },
        )
        for index, item in enumerate(CRYPTO_TOP_15, start=1)
    ]


def _is_tradable_us_equity(*, symbol: str, candidate: dict[str, Any], asset: dict[str, Any]) -> bool:
    if symbol in ALLOWED_ETFS:
        return True

    for row in (candidate, asset):
        status = row.get("status")
        if isinstance(status, str) and status.lower() not in {"active", "tradable"}:
            return False
        tradable = row.get("tradable")
        if tradable is False:
            return False
        asset_class = row.get("class") or row.get("asset_class")
        if isinstance(asset_class, str) and asset_class.lower() not in {"us_equity", "equity", "stock", ""}:
            return False

    return True


def _is_excluded_etf(*, symbol: str, candidate: dict[str, Any], asset: dict[str, Any]) -> bool:
    if symbol in ALLOWED_ETFS:
        return False

    for row in (candidate, asset):
        is_etf = row.get("is_etf")
        if isinstance(is_etf, bool):
            return is_etf

        for key in ("type", "asset_type", "security_type", "category"):
            value = row.get(key)
            if isinstance(value, str) and "etf" in value.lower():
                return True

        attributes = row.get("attributes")
        if isinstance(attributes, list):
            if any("etf" in str(item).lower() for item in attributes):
                return True

        name = row.get("name")
        if isinstance(name, str):
            upper_name = name.upper()
            if " ETF" in upper_name or upper_name.endswith("ETF"):
                return True

    return False


def _candidate_has_ai_ranking(candidate: dict[str, Any]) -> bool:
    for key in ("ai_rank_score", "confidence"):
        if key in candidate and candidate.get(key) is not None:
            return True
    return False


def _resolve_stock_selection_source(*, source: str, ai_scored: bool) -> str:
    if source == "ai":
        return "ai_ranked" if ai_scored else "ai_fill"
    return source


def _resolve_stock_selection_reason(*, candidate: dict[str, Any], source: str, ai_scored: bool) -> str | None:
    reason = str(candidate.get("brief_reason") or candidate.get("reason") or "")[:200].strip()
    if reason:
        return reason
    if source == "ai" and not ai_scored:
        return "Selected from fallback liquidity screen after AI returned a partial ranking."
    return None