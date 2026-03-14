from backend.app.core.config import get_settings
from backend.app.crypto.data.kraken_market_data import KrakenMarketDataAdapter


def test_kraken_ohlcv_fetch_parses_rows(monkeypatch) -> None:
    def handler(request):
        assert request.url.path == "/public/OHLC"
        assert request.url.params["pair"] == "XBTUSD"
        return __import__("httpx").Response(
            200,
            json={
                "error": [],
                "result": {
                    "XBTUSD": [
                        [1710000000, "62000.0", "62500.0", "61800.0", "62350.0", "62210.0", "12.5", 42],
                    ],
                    "last": 1710000000,
                },
            },
        )

    transport = __import__("httpx").MockTransport(handler)
    monkeypatch.setenv("KRAKEN_API_BASE_URL", "https://api.kraken.test")
    get_settings.cache_clear()

    adapter = KrakenMarketDataAdapter(get_settings(), transport=transport)
    bars = adapter.fetch_ohlcv(symbol="XBTUSD", timeframe="1h")

    assert len(bars) == 1
    assert bars[0].symbol == "XBTUSD"
    assert str(bars[0].close) == "62350.0"
    assert bars[0].trade_count == 42
