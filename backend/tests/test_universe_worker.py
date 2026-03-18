from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.models.core import AiResearchPick, UniverseRun
from backend.app.services import universe_service
from backend.app.workers.universe_worker import UniverseWorker


# ---------------------------------------------------------------------------
# Fake adapters (unchanged — still needed for the fallback screener path)
# ---------------------------------------------------------------------------

class FakeScreenerAdapter:
    def __init__(self, rows: list[dict], assets: dict[str, dict]) -> None:
        self.rows = rows
        self.assets = assets
        self.fetch_most_active_calls = 0
        self.fetch_asset_calls: list[str] = []

    def fetch_most_active(self, *, top: int = 50, by: str = "volume") -> list[dict]:
        self.fetch_most_active_calls += 1
        return self.rows

    def fetch_asset(self, *, symbol: str) -> dict:
        self.fetch_asset_calls.append(symbol)
        return self.assets.get(symbol, {})


class FakeRegistry:
    def __init__(self, screener: FakeScreenerAdapter) -> None:
        self._screener = screener

    def alpaca_stock_screener(self) -> FakeScreenerAdapter:
        return self._screener


# ---------------------------------------------------------------------------
# Helper: seed ai_research_picks rows directly
# ---------------------------------------------------------------------------

def _seed_ai_picks(
    db: Session,
    *,
    trade_date: str,
    symbols: list[str],
    scanned_at: datetime | None = None,
    venue: str = "alpaca",
    stop_loss_offset: float = 5.0,
    take_profit_offset: float = 10.0,
) -> list[AiResearchPick]:
    """Insert AiResearchPick rows so resolve_stock_universe sees them."""
    ts = scanned_at or datetime(2026, 3, 14, 13, 0, tzinfo=UTC)
    picks = []
    for rank, symbol in enumerate(symbols, start=1):
        price = Decimal("100.00")
        pick = AiResearchPick(
            trade_date=trade_date,
            scanned_at=ts,
            symbol=symbol,
            catalyst=f"{symbol} catalyst for {trade_date}",
            approximate_price=price,
            entry_zone_low=price - Decimal("1.00"),
            entry_zone_high=price + Decimal("1.00"),
            stop_loss=price - Decimal(str(stop_loss_offset)),
            take_profit_primary=price + Decimal(str(take_profit_offset)),
            take_profit_stretch=price + Decimal(str(take_profit_offset * 1.5)),
            use_trail_stop=False,
            position_size_dollars=Decimal("1000.00"),
            risk_reward_note="2:1 setup",
            is_bonus_pick=rank > len(symbols) - 2,
            account_cash_at_scan=Decimal("25000.00"),
            venue=venue,
        )
        db.add(pick)
        picks.append(pick)
    db.commit()
    return picks


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'phase5_worker.db'}")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(universe_service, "PROJECT_ROOT", tmp_path)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def worker_settings() -> Settings:
    return Settings(
        database_url="sqlite:///phase5_worker.db",
        stock_universe_source="ai",
        stock_universe_max_size=3,
        ai_enabled=True,
        ai_run_once_daily=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ai_first_stock_universe_resolution_persists_snapshot_and_order(
    db_session: Session,
    worker_settings: Settings,
) -> None:
    """When AI research picks exist for the trade date, universe is seeded from them."""
    trade_date = "2026-03-14"
    _seed_ai_picks(db_session, trade_date=trade_date, symbols=["MSFT", "AAPL", "SPY"])
    screener = FakeScreenerAdapter(rows=[], assets={})  # not called on ai_research path
    worker = UniverseWorker(db_session, registry=FakeRegistry(screener), settings=worker_settings)

    summary = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 12, 45, tzinfo=UTC))

    assert summary.source == "ai_research"
    assert summary.symbols == ("MSFT", "AAPL", "SPY")
    assert summary.snapshot_path is not None
    assert Path(summary.snapshot_path).exists()
    run = db_session.query(UniverseRun).filter(UniverseRun.asset_class == "stock").one()
    assert run.source == "ai_research"
    assert len(run.constituents) == 3
    # Screener was NOT called — AI research picks were used directly
    assert screener.fetch_most_active_calls == 0


def test_ai_research_picks_carry_sl_tp_in_payload(db_session: Session, worker_settings: Settings) -> None:
    """AI SL/TP hints from the pick are stored in each constituent's payload."""
    trade_date = "2026-03-14"
    _seed_ai_picks(db_session, trade_date=trade_date, symbols=["NVDA", "AMD"])
    worker = UniverseWorker(
        db_session,
        registry=FakeRegistry(FakeScreenerAdapter([], {})),
        settings=worker_settings,
    )

    summary = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 12, 55, tzinfo=UTC), force=True)

    run = db_session.query(UniverseRun).filter(UniverseRun.asset_class == "stock").one()
    nvda = next(c for c in run.constituents if c.symbol == "NVDA")
    assert nvda.payload is not None
    assert nvda.payload.get("ai_stop_loss") is not None
    assert nvda.payload.get("ai_take_profit_primary") is not None
    assert nvda.payload.get("ai_entry_zone_low") is not None
    assert nvda.payload.get("ai_risk_reward_note") == "2:1 setup"


def test_fallback_universe_used_when_no_ai_picks(db_session: Session, worker_settings: Settings) -> None:
    """When no AI research picks exist, the screener fallback is used."""
    screener = FakeScreenerAdapter(
        rows=[
            {"symbol": "AAPL", "volume": 1000},
            {"symbol": "MSFT", "volume": 900},
            {"symbol": "QQQ", "volume": 850, "is_etf": True},
        ],
        assets={
            "AAPL": {"symbol": "AAPL", "tradable": True, "status": "active", "class": "us_equity"},
            "MSFT": {"symbol": "MSFT", "tradable": True, "status": "active", "class": "us_equity"},
            "QQQ": {"symbol": "QQQ", "tradable": True, "status": "active", "class": "us_equity", "is_etf": True},
        },
    )
    # No AI picks seeded → fallback path
    worker = UniverseWorker(db_session, registry=FakeRegistry(screener), settings=worker_settings)

    summary = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 12, 50, tzinfo=UTC), force=True)

    assert summary.source == "fallback"
    assert summary.symbols == ("AAPL", "MSFT", "QQQ")
    assert screener.fetch_most_active_calls == 1


def test_fallback_used_when_ai_disabled(db_session: Session, worker_settings: Settings) -> None:
    """When ai_enabled=False, always falls back to screener even if picks exist."""
    trade_date = "2026-03-14"
    _seed_ai_picks(db_session, trade_date=trade_date, symbols=["MSFT", "AAPL"])
    settings = worker_settings.model_copy(update={"ai_enabled": False})
    screener = FakeScreenerAdapter(
        rows=[{"symbol": "AAPL", "volume": 1000}, {"symbol": "MSFT", "volume": 900}],
        assets={
            "AAPL": {"symbol": "AAPL", "tradable": True, "status": "active", "class": "us_equity"},
            "MSFT": {"symbol": "MSFT", "tradable": True, "status": "active", "class": "us_equity"},
        },
    )
    worker = UniverseWorker(db_session, registry=FakeRegistry(screener), settings=settings)

    summary = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 12, 50, tzinfo=UTC), force=True)

    assert summary.source == "fallback"
    assert screener.fetch_most_active_calls == 1


def test_etf_filtering_excludes_all_except_spy_and_qqq(db_session: Session, worker_settings: Settings) -> None:
    settings = worker_settings.model_copy(update={"ai_enabled": False})
    screener = FakeScreenerAdapter(
        rows=[
            {"symbol": "ARKK", "volume": 2000, "is_etf": True},
            {"symbol": "SPY", "volume": 1900, "is_etf": True},
            {"symbol": "QQQ", "volume": 1800, "is_etf": True},
            {"symbol": "AAPL", "volume": 1700},
        ],
        assets={
            "ARKK": {"symbol": "ARKK", "tradable": True, "status": "active", "class": "us_equity", "is_etf": True},
            "SPY": {"symbol": "SPY", "tradable": True, "status": "active", "class": "us_equity", "is_etf": True},
            "QQQ": {"symbol": "QQQ", "tradable": True, "status": "active", "class": "us_equity", "is_etf": True},
            "AAPL": {"symbol": "AAPL", "tradable": True, "status": "active", "class": "us_equity"},
        },
    )
    worker = UniverseWorker(db_session, registry=FakeRegistry(screener), settings=settings)

    summary = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 13, 0, tzinfo=UTC), force=True)

    assert summary.symbols == ("SPY", "QQQ", "AAPL")
    assert "ARKK" not in summary.symbols


def test_stock_universe_max_size_is_enforced(db_session: Session, worker_settings: Settings) -> None:
    trade_date = "2026-03-14"
    _seed_ai_picks(
        db_session,
        trade_date=trade_date,
        symbols=["AAPL", "MSFT", "NVDA", "AMZN"],
    )
    settings = worker_settings.model_copy(update={"stock_universe_max_size": 2})
    worker = UniverseWorker(db_session, registry=FakeRegistry(FakeScreenerAdapter([], {})), settings=settings)

    summary = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 13, 5, tzinfo=UTC), force=True)

    assert len(summary.symbols) == 2
    assert summary.symbols == ("AAPL", "MSFT")


def test_hard_coded_kraken_top_15_crypto_universe_is_available_every_cycle(
    db_session: Session,
    worker_settings: Settings,
) -> None:
    worker = UniverseWorker(
        db_session,
        registry=FakeRegistry(FakeScreenerAdapter([], {})),
        settings=worker_settings,
    )

    summary = worker.resolve_crypto_universe(now=datetime(2026, 3, 14, 13, 10, tzinfo=UTC))

    assert summary.source == "static"
    assert len(summary.symbols) == 15
    assert summary.symbols[0] == "XBTUSD"
    assert "XDGUSD" in summary.symbols
    run = db_session.query(UniverseRun).filter(UniverseRun.asset_class == "crypto").one()
    doge_row = next(item for item in run.constituents if item.symbol == "XDGUSD")
    assert doge_row.payload["display_symbol"] == "DOGE/USD"
    assert doge_row.payload["display_name"] == "Dogecoin"
    cached = worker.resolve_crypto_universe(now=datetime(2026, 3, 14, 14, 10, tzinfo=UTC))
    assert cached.from_cache is True
    assert cached.symbols == summary.symbols


def test_downstream_waits_until_stock_universe_is_resolved(db_session: Session, worker_settings: Settings) -> None:
    screener = FakeScreenerAdapter(
        rows=[{"symbol": "AAPL", "volume": 1000}],
        assets={"AAPL": {"symbol": "AAPL", "tradable": True, "status": "active", "class": "us_equity"}},
    )
    worker = UniverseWorker(db_session, registry=FakeRegistry(screener), settings=worker_settings)

    with pytest.raises(RuntimeError, match="stock_universe_unresolved"):
        worker.require_stock_universe_ready(now=datetime(2026, 3, 14, 13, 15, tzinfo=UTC))

    # Seed picks so resolve uses AI research path
    _seed_ai_picks(db_session, trade_date="2026-03-14", symbols=["AAPL"])
    worker.resolve_stock_universe(now=datetime(2026, 3, 14, 13, 15, tzinfo=UTC), force=True)

    assert worker.require_stock_universe_ready(now=datetime(2026, 3, 14, 13, 16, tzinfo=UTC)) == ("AAPL",)


def test_same_day_cache_short_circuits_duplicate_resolve(db_session: Session, worker_settings: Settings) -> None:
    """Second call to resolve_stock_universe on same day returns cache without re-querying picks."""
    trade_date = "2026-03-14"
    _seed_ai_picks(db_session, trade_date=trade_date, symbols=["MSFT", "AAPL"])
    screener = FakeScreenerAdapter(rows=[], assets={})
    worker = UniverseWorker(db_session, registry=FakeRegistry(screener), settings=worker_settings)

    first = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 13, 20, tzinfo=UTC))
    second = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 13, 21, tzinfo=UTC))

    assert first.symbols == ("MSFT", "AAPL")
    assert second.symbols == first.symbols
    assert second.from_cache is True
    assert second.skipped_reason == "already_resolved_today"
    assert screener.fetch_most_active_calls == 0
