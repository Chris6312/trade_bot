from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.models.core import UniverseRun
from backend.app.services import universe_service
from backend.app.workers.universe_worker import UniverseWorker


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


class FakeAIService:
    def __init__(self, rankings: list[dict] | None = None, error: Exception | None = None) -> None:
        self.rankings = rankings or []
        self.error = error
        self.calls = 0

    def rank_candidates(self, candidates: list[dict]) -> list[dict]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.rankings


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


def test_ai_first_stock_universe_resolution_persists_snapshot_and_order(
    db_session: Session,
    worker_settings: Settings,
) -> None:
    screener = FakeScreenerAdapter(
        rows=[
            {"symbol": "AAPL", "volume": 1000},
            {"symbol": "MSFT", "volume": 900},
            {"symbol": "SPY", "volume": 800, "is_etf": True},
        ],
        assets={
            "AAPL": {"symbol": "AAPL", "tradable": True, "status": "active", "class": "us_equity"},
            "MSFT": {"symbol": "MSFT", "tradable": True, "status": "active", "class": "us_equity"},
            "SPY": {"symbol": "SPY", "tradable": True, "status": "active", "class": "us_equity", "is_etf": True},
        },
    )
    ai_service = FakeAIService(
        rankings=[
            {"symbol": "MSFT", "ai_rank_score": 0.99, "confidence": 0.8, "brief_reason": "strong liquidity"},
            {"symbol": "AAPL", "ai_rank_score": 0.88, "confidence": 0.7, "brief_reason": "quality trend"},
            {"symbol": "SPY", "ai_rank_score": 0.50, "confidence": 0.6, "brief_reason": "benchmark ETF"},
        ]
    )
    worker = UniverseWorker(
        db_session,
        registry=FakeRegistry(screener),
        settings=worker_settings,
        ai_service=ai_service,
    )

    summary = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 12, 45, tzinfo=UTC))

    assert summary.source == "ai"
    assert summary.symbols == ("MSFT", "AAPL", "SPY")
    assert summary.snapshot_path is not None
    assert Path(summary.snapshot_path).exists()
    run = db_session.query(UniverseRun).filter(UniverseRun.asset_class == "stock").one()
    assert run.source == "ai"
    assert len(run.constituents) == 3
    assert ai_service.calls == 1


def test_ai_run_marks_ranked_and_fill_rows_separately(db_session: Session, worker_settings: Settings) -> None:
    screener = FakeScreenerAdapter(
        rows=[
            {"symbol": "AAPL", "volume": 1000},
            {"symbol": "MSFT", "volume": 900},
            {"symbol": "SPY", "volume": 800, "is_etf": True},
        ],
        assets={
            "AAPL": {"symbol": "AAPL", "tradable": True, "status": "active", "class": "us_equity"},
            "MSFT": {"symbol": "MSFT", "tradable": True, "status": "active", "class": "us_equity"},
            "SPY": {"symbol": "SPY", "tradable": True, "status": "active", "class": "us_equity", "is_etf": True},
        },
    )
    ai_service = FakeAIService(
        rankings=[
            {"symbol": "MSFT", "ai_rank_score": 0.99, "confidence": 0.8, "brief_reason": "strong liquidity"},
            {"symbol": "AAPL", "ai_rank_score": 0.88, "confidence": 0.7, "brief_reason": "quality trend"},
        ]
    )
    worker = UniverseWorker(
        db_session,
        registry=FakeRegistry(screener),
        settings=worker_settings,
        ai_service=ai_service,
    )

    summary = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 12, 55, tzinfo=UTC), force=True)

    assert summary.source == "ai"
    run = db_session.query(UniverseRun).filter(UniverseRun.asset_class == "stock").one()
    constituents = {item.symbol: item for item in run.constituents}

    assert constituents["MSFT"].source == "ai"
    assert constituents["MSFT"].payload["ai_scored"] is True
    assert constituents["MSFT"].payload["selection_source"] == "ai_ranked"
    assert constituents["MSFT"].payload["ai_rank_score"] == 0.99
    assert constituents["MSFT"].payload["confidence"] == 0.8

    assert constituents["SPY"].source == "ai"
    assert constituents["SPY"].payload["ai_scored"] is False
    assert constituents["SPY"].payload["selection_source"] == "ai_fill"
    assert "ai_rank_score" not in constituents["SPY"].payload
    assert "confidence" not in constituents["SPY"].payload
    assert constituents["SPY"].selection_reason == "Selected from fallback liquidity screen after AI returned a partial ranking."


def test_fallback_universe_used_when_ai_fails(db_session: Session, worker_settings: Settings) -> None:
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
    ai_service = FakeAIService(error=RuntimeError("provider_down"))
    worker = UniverseWorker(
        db_session,
        registry=FakeRegistry(screener),
        settings=worker_settings,
        ai_service=ai_service,
    )

    summary = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 12, 50, tzinfo=UTC), force=True)

    assert summary.source == "fallback"
    assert summary.symbols == ("AAPL", "MSFT", "QQQ")
    run = db_session.query(UniverseRun).filter(UniverseRun.asset_class == "stock").one()
    assert "provider_down" in (run.last_error or "")


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
    worker = UniverseWorker(db_session, registry=FakeRegistry(screener), settings=settings, ai_service=FakeAIService())

    summary = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 13, 0, tzinfo=UTC), force=True)

    assert summary.symbols == ("SPY", "QQQ", "AAPL")
    assert "ARKK" not in summary.symbols


def test_stock_universe_max_size_is_enforced(db_session: Session, worker_settings: Settings) -> None:
    settings = worker_settings.model_copy(update={"ai_enabled": False, "stock_universe_max_size": 2})
    screener = FakeScreenerAdapter(
        rows=[
            {"symbol": "AAPL", "volume": 4000},
            {"symbol": "MSFT", "volume": 3000},
            {"symbol": "NVDA", "volume": 2000},
            {"symbol": "AMZN", "volume": 1000},
        ],
        assets={
            symbol: {"symbol": symbol, "tradable": True, "status": "active", "class": "us_equity"}
            for symbol in ("AAPL", "MSFT", "NVDA", "AMZN")
        },
    )
    worker = UniverseWorker(db_session, registry=FakeRegistry(screener), settings=settings, ai_service=FakeAIService())

    summary = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 13, 5, tzinfo=UTC), force=True)

    assert summary.symbols == ("AAPL", "MSFT")


def test_hard_coded_kraken_top_15_crypto_universe_is_available_every_cycle(
    db_session: Session,
    worker_settings: Settings,
) -> None:
    worker = UniverseWorker(
        db_session,
        registry=FakeRegistry(FakeScreenerAdapter([], {})),
        settings=worker_settings,
        ai_service=FakeAIService(),
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
    worker = UniverseWorker(db_session, registry=FakeRegistry(screener), settings=worker_settings, ai_service=FakeAIService())

    with pytest.raises(RuntimeError, match="stock_universe_unresolved"):
        worker.require_stock_universe_ready(now=datetime(2026, 3, 14, 13, 15, tzinfo=UTC))

    worker.resolve_stock_universe(now=datetime(2026, 3, 14, 13, 15, tzinfo=UTC), force=True)

    assert worker.require_stock_universe_ready(now=datetime(2026, 3, 14, 13, 16, tzinfo=UTC)) == ("AAPL",)


def test_same_day_jsonl_snapshot_short_circuits_duplicate_ai_run(db_session: Session, worker_settings: Settings) -> None:
    screener = FakeScreenerAdapter(
        rows=[
            {"symbol": "AAPL", "volume": 1000},
            {"symbol": "MSFT", "volume": 900},
        ],
        assets={
            "AAPL": {"symbol": "AAPL", "tradable": True, "status": "active", "class": "us_equity"},
            "MSFT": {"symbol": "MSFT", "tradable": True, "status": "active", "class": "us_equity"},
        },
    )
    ai_service = FakeAIService(
        rankings=[
            {"symbol": "MSFT", "ai_rank_score": 0.9, "confidence": 0.7, "brief_reason": "deep liquidity"},
            {"symbol": "AAPL", "ai_rank_score": 0.8, "confidence": 0.7, "brief_reason": "broad participation"},
        ]
    )
    worker = UniverseWorker(
        db_session,
        registry=FakeRegistry(screener),
        settings=worker_settings,
        ai_service=ai_service,
    )

    first = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 13, 20, tzinfo=UTC))
    second = worker.resolve_stock_universe(now=datetime(2026, 3, 14, 13, 21, tzinfo=UTC))

    assert first.symbols == ("MSFT", "AAPL")
    assert second.symbols == first.symbols
    assert second.from_cache is True
    assert second.skipped_reason == "already_resolved_today"
    assert ai_service.calls == 1
    assert screener.fetch_most_active_calls == 1