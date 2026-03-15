import httpx

from backend.app.core.config import get_settings
from backend.app.crypto.brokers.alpaca_crypto_paper import AlpacaCryptoPaperAdapter
from backend.app.stocks.brokers.alpaca_stock_paper import AlpacaStockPaperAdapter
from backend.app.stocks.data.alpaca_stock_ohlcv import AlpacaStockOhlcvAdapter


def _seed_alpaca_env(monkeypatch) -> None:
    monkeypatch.setenv("ALPACA_PAPER_KEY", "alpaca-stock-key")
    monkeypatch.setenv("ALPACA_PAPER_SECRET", "alpaca-stock-secret")
    monkeypatch.setenv("ALPACA_PAPER_KEY_CRYPTO", "alpaca-crypto-key")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_CRYPTO", "alpaca-crypto-secret")
    monkeypatch.setenv("ALPACA_TRADING_API_BASE_URL", "https://paper-api.alpaca.test")
    monkeypatch.setenv("ALPACA_MARKET_DATA_BASE_URL", "https://data.alpaca.test")
    monkeypatch.setenv("ALPACA_STOCK_DATA_FEED", "iex")
    get_settings.cache_clear()


def test_alpaca_stock_paper_account_state(monkeypatch) -> None:
    _seed_alpaca_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/account":
            return httpx.Response(200, json={"id": "acct-stock", "equity": "512.11", "cash": "220.50", "buying_power": "400.00"})
        if request.url.path == "/v2/positions":
            return httpx.Response(200, json=[{"symbol": "AAPL", "qty": "1", "market_value": "201.25", "cost_basis": "198.00", "avg_entry_price": "198.00"}])
        raise AssertionError(f"Unexpected path {request.url.path}")

    adapter = AlpacaStockPaperAdapter(get_settings(), transport=httpx.MockTransport(handler))
    state = adapter.get_account_state()

    assert state.asset_class == "stock"
    assert state.account_id == "acct-stock"
    assert state.positions[0].symbol == "AAPL"


def test_alpaca_crypto_paper_account_state(monkeypatch) -> None:
    _seed_alpaca_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/account":
            return httpx.Response(200, json={"id": "acct-crypto", "equity": "700.00", "cash": "100.00", "buying_power": "350.00"})
        if request.url.path == "/v2/positions":
            return httpx.Response(200, json=[{"symbol": "BTCUSD", "qty": "0.01", "market_value": "600.00", "cost_basis": "590.00", "avg_entry_price": "59000.00"}])
        raise AssertionError(f"Unexpected path {request.url.path}")

    adapter = AlpacaCryptoPaperAdapter(get_settings(), transport=httpx.MockTransport(handler))
    state = adapter.get_account_state()

    assert state.asset_class == "crypto"
    assert state.positions[0].symbol == "BTCUSD"
    assert str(state.positions[0].quantity) == "0.01"


def test_alpaca_stock_ohlcv_fetch_defaults_to_iex_feed(monkeypatch) -> None:
    _seed_alpaca_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/stocks/bars"
        assert request.url.params["symbols"] == "AAPL,MSFT"
        assert request.url.params["feed"] == "iex"
        return httpx.Response(
            200,
            json={
                "bars": {
                    "AAPL": [{"t": "2026-03-13T14:30:00Z", "o": 211.5, "h": 212.1, "l": 210.8, "c": 211.9, "v": 12345, "n": 321, "vw": 211.6}],
                    "MSFT": [],
                }
            },
        )

    adapter = AlpacaStockOhlcvAdapter(get_settings(), transport=httpx.MockTransport(handler))
    bars = adapter.fetch_ohlcv(symbols=["AAPL", "MSFT"], timeframe="1m", start="2026-03-13T14:30:00Z")

    assert list(bars.keys()) == ["AAPL", "MSFT"]
    assert str(bars["AAPL"][0].close) == "211.9"
