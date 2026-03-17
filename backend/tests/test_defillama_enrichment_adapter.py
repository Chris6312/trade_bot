from __future__ import annotations

import httpx

from backend.app.crypto.data.defillama_enrichment import DefiLlamaMetricsAdapter


def test_defillama_adapter_fetches_market_snapshot_from_primary_paths() -> None:
    def yields_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/perps"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"symbol": "BTC-USD-PERP", "fundingRate": 0.01, "openInterest": 1000},
                    {"symbol": "ETH-USD-PERP", "fundingRate": -0.005, "openInterest": 500},
                    {"symbol": "SOL-USD-PERP", "fundingRate": 0.02, "openInterest": 100},
                ]
            },
        )

    def metrics_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/chains":
            return httpx.Response(200, json=[{"chain": "Ethereum", "tvl": 100}, {"chain": "Solana", "tvl": 250}])
        if request.url.path == "/v2/historicalChainTvl":
            return httpx.Response(
                200,
                json=[
                    {"date": 1710000000, "tvl": {"Ethereum": 120, "Solana": 80}},
                    {"date": 1710086400, "tvl": {"Ethereum": 180, "Solana": 170}},
                ],
            )
        if request.url.path == "/overview/derivatives":
            return httpx.Response(200, json={"change_1d": 12.5})
        raise AssertionError(f"unexpected metrics path: {request.url.path}")

    adapter = DefiLlamaMetricsAdapter(
        metrics_base_url="https://metrics.llama.test",
        yields_base_url="https://yields.llama.test",
        metrics_transport=httpx.MockTransport(metrics_handler),
        yields_transport=httpx.MockTransport(yields_handler),
    )
    snapshot = adapter.fetch_market_snapshot()
    adapter.close()

    assert snapshot.funding_bias == 0.005
    assert snapshot.open_interest_total == 1500.0
    assert snapshot.defi_tvl_total == 350.0
    assert snapshot.defi_tvl_prev_24h == 200.0
    assert snapshot.derivatives_change_1d == 12.5
    assert snapshot.raw["matched_perps"] == 2



def test_defillama_adapter_falls_back_to_secondary_paths_and_allows_missing_derivatives() -> None:
    def yields_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/perps":
            return httpx.Response(404, json={"error": "not found"})
        if request.url.path == "/yields/perps":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"symbol": "XBTUSD.PERP", "fundingRate": 0.002, "openInterest": 300},
                        {"symbol": "ETHUSD.PERP", "fundingRate": 0.004, "openInterest": 200},
                    ]
                },
            )
        raise AssertionError(f"unexpected yields path: {request.url.path}")

    def metrics_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/v2/chains", "/v2/historicalChainTvl", "/overview/derivatives", "/api/overview/derivatives"}:
            return httpx.Response(404, json={"error": "not found"})
        if request.url.path == "/api/v2/chains":
            return httpx.Response(200, json=[{"chain": "Ethereum", "tvl": 900.0}])
        if request.url.path == "/api/v2/historicalChainTvl":
            return httpx.Response(200, json=[{"date": 1, "tvl": 880.0}, {"date": 2, "tvl": 900.0}])
        raise AssertionError(f"unexpected metrics path: {request.url.path}")

    adapter = DefiLlamaMetricsAdapter(
        metrics_base_url="https://metrics.llama.test",
        yields_base_url="https://yields.llama.test",
        metrics_transport=httpx.MockTransport(metrics_handler),
        yields_transport=httpx.MockTransport(yields_handler),
    )
    snapshot = adapter.fetch_market_snapshot()
    adapter.close()

    assert snapshot.funding_bias == 0.0028
    assert snapshot.open_interest_total == 500.0
    assert snapshot.defi_tvl_total == 900.0
    assert snapshot.defi_tvl_prev_24h == 880.0
    assert snapshot.derivatives_change_1d is None
    assert snapshot.raw["matched_perps"] == 2
