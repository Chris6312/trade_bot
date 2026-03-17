from backend.app.core.config import get_settings
from backend.app.crypto.data.kraken_orderbook import KrakenOrderBookAdapter


def test_kraken_orderbook_fetch_parses_snapshot(monkeypatch) -> None:
    def handler(request):
        assert request.url.path == "/public/Depth"
        assert request.url.params["pair"] == "XBTUSD"
        assert request.url.params["count"] == "25"
        return __import__("httpx").Response(
            200,
            json={
                "error": [],
                "result": {
                    "XBTUSD": {
                        "bids": [
                            ["62000.0", "1.25", 1710000000],
                            ["61990.0", "0.75", 1710000000],
                        ],
                        "asks": [
                            ["62010.0", "1.10", 1710000000],
                            ["62020.0", "0.80", 1710000000],
                        ],
                    }
                },
            },
        )

    transport = __import__("httpx").MockTransport(handler)
    monkeypatch.setenv("KRAKEN_API_BASE_URL", "https://api.kraken.test")
    get_settings.cache_clear()

    adapter = KrakenOrderBookAdapter(get_settings(), transport=transport)
    snapshot = adapter.fetch_snapshot(symbol="XBTUSD", depth=25)

    assert snapshot.symbol == "XBTUSD"
    assert len(snapshot.bids) == 2
    assert len(snapshot.asks) == 2
    assert str(snapshot.bids[0].price) == "62000.0"
    assert str(snapshot.asks[0].volume) == "1.10"
