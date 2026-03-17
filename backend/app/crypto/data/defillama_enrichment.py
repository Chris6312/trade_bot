from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import fmean
from typing import Any

import httpx

from backend.app.common.adapters.http import JsonApiClient


@dataclass(slots=True, frozen=True)
class DefiLlamaMarketSnapshot:
    funding_bias: float | None
    open_interest_total: float | None
    defi_tvl_total: float | None
    defi_tvl_prev_24h: float | None
    derivatives_change_1d: float | None
    as_of_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)


class DefiLlamaMetricsAdapter:
    def __init__(
        self,
        *,
        metrics_base_url: str = "https://api.llama.fi",
        yields_base_url: str = "https://yields.llama.fi",
        timeout_seconds: float = 8.0,
        metrics_transport: httpx.BaseTransport | None = None,
        yields_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._metrics = JsonApiClient(
            base_url=metrics_base_url,
            label="DeFiLlama metrics",
            timeout_seconds=timeout_seconds,
            transport=metrics_transport,
        )
        self._yields = JsonApiClient(
            base_url=yields_base_url,
            label="DeFiLlama yields",
            timeout_seconds=timeout_seconds,
            transport=yields_transport,
        )

    def close(self) -> None:
        self._metrics.close()
        self._yields.close()

    def fetch_market_snapshot(self) -> DefiLlamaMarketSnapshot:
        perps_payload = self._request_first(self._yields, ("/perps", "/yields/perps"))
        chains_payload = self._request_first(self._metrics, ("/v2/chains", "/api/v2/chains"))
        historical_payload = self._request_first(
            self._metrics,
            ("/v2/historicalChainTvl", "/api/v2/historicalChainTvl"),
        )
        derivatives_payload = self._request_optional_first(
            self._metrics,
            ("/overview/derivatives", "/api/overview/derivatives"),
        )

        funding_bias, open_interest_total, matched_rows = _derive_perps_metrics(perps_payload)
        defi_tvl_total = _derive_total_chain_tvl(chains_payload)
        defi_tvl_prev_24h = _derive_previous_total_tvl(historical_payload)
        derivatives_change_1d = _safe_float((derivatives_payload or {}).get("change_1d"))
        as_of_at = datetime.now(UTC)
        return DefiLlamaMarketSnapshot(
            funding_bias=funding_bias,
            open_interest_total=open_interest_total,
            defi_tvl_total=defi_tvl_total,
            defi_tvl_prev_24h=defi_tvl_prev_24h,
            derivatives_change_1d=derivatives_change_1d,
            as_of_at=as_of_at,
            raw={
                "matched_perps": matched_rows,
                "derivatives_change_1d": derivatives_change_1d,
            },
        )

    @staticmethod
    def _request_first(client: JsonApiClient, paths: tuple[str, ...]) -> Any:
        last_error: Exception | None = None
        for path in paths:
            try:
                return client.request_json("GET", path)
            except Exception as exc:  # pragma: no cover - exercised indirectly in runtime fallback
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("No request path configured for DeFiLlama adapter")

    @staticmethod
    def _request_optional_first(client: JsonApiClient, paths: tuple[str, ...]) -> Any | None:
        for path in paths:
            try:
                return client.request_json("GET", path)
            except Exception:
                continue
        return None


def _derive_perps_metrics(payload: Any) -> tuple[float | None, float | None, int]:
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return None, None, 0

    matched: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if "USD" not in symbol:
            continue
        if not any(token in symbol for token in ("BTC", "XBT", "ETH")):
            continue
        matched.append(row)

    if not matched:
        return None, None, 0

    open_interests = [_safe_float(row.get("openInterest")) for row in matched]
    open_interests = [value for value in open_interests if value is not None and value >= 0]
    open_interest_total = round(sum(open_interests), 6) if open_interests else None

    weighted_rates: list[float] = []
    weights: list[float] = []
    fallback_rates: list[float] = []
    for row in matched:
        rate = _safe_float(row.get("fundingRate"))
        open_interest = _safe_float(row.get("openInterest"))
        if rate is None:
            continue
        fallback_rates.append(rate)
        if open_interest is not None and open_interest > 0:
            weighted_rates.append(rate * open_interest)
            weights.append(open_interest)

    funding_bias: float | None
    if weights and sum(weights) > 0:
        funding_bias = round(sum(weighted_rates) / sum(weights), 6)
    elif fallback_rates:
        funding_bias = round(fmean(fallback_rates), 6)
    else:
        funding_bias = None
    return funding_bias, open_interest_total, len(matched)


def _derive_total_chain_tvl(payload: Any) -> float | None:
    if not isinstance(payload, list):
        return None
    values = [_safe_float(item.get("tvl")) for item in payload if isinstance(item, dict)]
    clean = [value for value in values if value is not None and value >= 0]
    if not clean:
        return None
    return round(sum(clean), 6)


def _derive_previous_total_tvl(payload: Any) -> float | None:
    if not isinstance(payload, list):
        return None
    if len(payload) < 2:
        return None
    rows = [item for item in payload if isinstance(item, dict)]
    if len(rows) < 2:
        return None
    latest = rows[-1].get("tvl")
    previous = rows[-2].get("tvl")
    if isinstance(previous, dict):
        values = [_safe_float(value) for value in previous.values()]
    else:
        values = [_safe_float(previous)]
    clean = [value for value in values if value is not None and value >= 0]
    if not clean:
        return None
    return round(sum(clean), 6)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
