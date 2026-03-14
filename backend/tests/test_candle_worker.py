from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.common.adapters.models import OhlcvBar
from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.models.core import Candle, CandleFreshness
from backend.app.services.candle_service import (
    SINGLE_CANDLE_WRITER,
    get_sync_state,
    persist_ohlcv_batch,
)
from backend.app.workers.candle_worker import SingleCandleWorker


class FakeAlpacaStockAdapter:
    def __init__(self, bars_by_symbol: dict[str, list[OhlcvBar]]) -> None:
        self.bars_by_symbol = bars_by_symbol
        self.calls: list[dict[str, object]] = []

    def fetch_ohlcv(self, **kwargs) -> dict[str, list[OhlcvBar]]:
        self.calls.append(kwargs)
        return self.bars_by_symbol


class FakeKrakenMarketDataAdapter:
    def __init__(self, bars_by_symbol: dict[str, list[OhlcvBar]]) -> None:
        self.bars_by_symbol = bars_by_symbol
        self.calls: list[dict[str, object]] = []

    def fetch_ohlcv(self, *, symbol: str, timeframe: str, since: int | None = None) -> list[OhlcvBar]:
        self.calls.append({"symbol": symbol, "timeframe": timeframe, "since": since})
        return self.bars_by_symbol.get(symbol, [])


class FakeRegistry:
    def __init__(
        self,
        *,
        alpaca_adapter: FakeAlpacaStockAdapter | None = None,
        kraken_adapter: FakeKrakenMarketDataAdapter | None = None,
    ) -> None:
        self._alpaca_adapter = alpaca_adapter or FakeAlpacaStockAdapter({})
        self._kraken_adapter = kraken_adapter or FakeKrakenMarketDataAdapter({})

    def alpaca_stock_ohlcv(self) -> FakeAlpacaStockAdapter:
        return self._alpaca_adapter

    def kraken_market_data(self) -> FakeKrakenMarketDataAdapter:
        return self._kraken_adapter


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'phase4_worker.db'}")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def worker_settings() -> Settings:
    return Settings(
        database_url="sqlite:///phase4_worker.db",
        stock_default_backfill_bars=10,
        crypto_default_backfill_bars=10,
    )


def _coerce_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _bar(symbol: str, timeframe: str, timestamp: datetime, close: str) -> OhlcvBar:
    return OhlcvBar(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        open=Decimal(close) - Decimal("1"),
        high=Decimal(close) + Decimal("1"),
        low=Decimal(close) - Decimal("2"),
        close=Decimal(close),
        volume=Decimal("100"),
        vwap=Decimal(close),
        trade_count=10,
    )


def test_stock_backfill_persists_candles_watermark_and_freshness(db_session: Session, worker_settings: Settings) -> None:
    bar_time = datetime(2026, 3, 13, 14, 30, tzinfo=UTC)
    alpaca_adapter = FakeAlpacaStockAdapter({"AAPL": [_bar("AAPL", "1m", bar_time, "211.90")]})
    worker = SingleCandleWorker(
        db_session,
        registry=FakeRegistry(alpaca_adapter=alpaca_adapter),
        settings=worker_settings,
    )

    summary = worker.sync_stock_backfill(
        symbols=["AAPL"],
        timeframe="1m",
        start=bar_time - timedelta(minutes=5),
        end=bar_time + timedelta(minutes=1),
        now=bar_time + timedelta(minutes=1),
    )

    assert summary.upserted_bars == 1
    candle = db_session.query(Candle).one()
    assert candle.symbol == "AAPL"
    state = get_sync_state(db_session, asset_class="stock", symbol="AAPL", timeframe="1m")
    assert state is not None
    assert _coerce_utc(state.last_candle_at) == bar_time
    freshness = db_session.query(CandleFreshness).one()
    assert _coerce_utc(freshness.last_candle_at) == bar_time
    assert _coerce_utc(freshness.fresh_through) == bar_time + timedelta(minutes=1)
    assert alpaca_adapter.calls[0]["start"] == "2026-03-13T14:25:00Z"


def test_stock_incremental_only_runs_during_nyse_hours(db_session: Session, worker_settings: Settings) -> None:
    alpaca_adapter = FakeAlpacaStockAdapter({"AAPL": []})
    worker = SingleCandleWorker(
        db_session,
        registry=FakeRegistry(alpaca_adapter=alpaca_adapter),
        settings=worker_settings,
    )

    summary = worker.sync_stock_incremental(
        symbols=["AAPL"],
        timeframe="1m",
        now=datetime(2026, 3, 14, 15, 0, tzinfo=UTC),
    )

    assert summary.upserted_bars == 0
    assert summary.skipped_reason == "outside_nyse_hours"
    assert alpaca_adapter.calls == []


def test_stock_incremental_uses_watermark_overlap_and_updates_state(db_session: Session, worker_settings: Settings) -> None:
    existing_bar_time = datetime(2026, 3, 13, 14, 30, tzinfo=UTC)
    persist_ohlcv_batch(
        db_session,
        writer_name=SINGLE_CANDLE_WRITER,
        asset_class="stock",
        venue="alpaca",
        source="alpaca_stock_ohlcv",
        bars=[_bar("AAPL", "1m", existing_bar_time, "211.90")],
        synced_at=existing_bar_time,
    )

    new_bar_time = datetime(2026, 3, 13, 14, 31, tzinfo=UTC)
    alpaca_adapter = FakeAlpacaStockAdapter({
        "AAPL": [
            _bar("AAPL", "1m", existing_bar_time, "211.90"),
            _bar("AAPL", "1m", new_bar_time, "212.10"),
        ]
    })
    worker = SingleCandleWorker(
        db_session,
        registry=FakeRegistry(alpaca_adapter=alpaca_adapter),
        settings=worker_settings,
    )

    summary = worker.sync_stock_incremental(
        symbols=["AAPL"],
        timeframe="1m",
        now=datetime(2026, 3, 13, 14, 35, tzinfo=UTC),
    )

    assert summary.upserted_bars == 2
    assert alpaca_adapter.calls[0]["start"] == "2026-03-13T14:29:00Z"
    state = get_sync_state(db_session, asset_class="stock", symbol="AAPL", timeframe="1m")
    assert state is not None
    assert _coerce_utc(state.last_candle_at) == new_bar_time


def test_crypto_backfill_and_incremental_use_persisted_watermarks(db_session: Session, worker_settings: Settings) -> None:
    first_bar = datetime(2026, 3, 13, 10, 0, tzinfo=UTC)
    kraken_adapter = FakeKrakenMarketDataAdapter({
        "XBTUSD": [_bar("XBTUSD", "1h", first_bar, "62000")],
    })
    worker = SingleCandleWorker(
        db_session,
        registry=FakeRegistry(kraken_adapter=kraken_adapter),
        settings=worker_settings,
    )

    backfill = worker.sync_crypto_backfill(
        symbols=["XBTUSD"],
        timeframe="1h",
        since=first_bar - timedelta(hours=2),
        now=first_bar + timedelta(minutes=5),
    )
    assert backfill.upserted_bars == 1

    second_bar = datetime(2026, 3, 13, 11, 0, tzinfo=UTC)
    incremental_adapter = FakeKrakenMarketDataAdapter({
        "XBTUSD": [
            _bar("XBTUSD", "1h", first_bar, "62000"),
            _bar("XBTUSD", "1h", second_bar, "62100"),
        ]
    })
    incremental_worker = SingleCandleWorker(
        db_session,
        registry=FakeRegistry(kraken_adapter=incremental_adapter),
        settings=worker_settings,
    )

    incremental = incremental_worker.sync_crypto_incremental(
        symbols=["XBTUSD"],
        timeframe="1h",
        now=second_bar + timedelta(minutes=5),
    )

    assert incremental.upserted_bars == 2
    assert incremental_adapter.calls[0]["since"] == int((first_bar - timedelta(hours=1)).timestamp())
    state = get_sync_state(db_session, asset_class="crypto", symbol="XBTUSD", timeframe="1h")
    assert state is not None
    assert _coerce_utc(state.last_candle_at) == second_bar
    freshness = db_session.query(CandleFreshness).filter(CandleFreshness.symbol == "XBTUSD").one()
    assert _coerce_utc(freshness.fresh_through) == second_bar + timedelta(hours=1)


def test_single_writer_enforcement_rejects_other_writers(db_session: Session) -> None:
    with pytest.raises(PermissionError):
        persist_ohlcv_batch(
            db_session,
            writer_name="strategy_worker",
            asset_class="stock",
            venue="alpaca",
            source="alpaca_stock_ohlcv",
            bars=[_bar("AAPL", "1m", datetime(2026, 3, 13, 14, 30, tzinfo=UTC), "211.90")],
        )
