from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.app.common.adapters.errors import AdapterParseError, AdapterRequestError

logger = logging.getLogger(__name__)


class JsonApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        label: str,
        default_headers: dict[str, str] | None = None,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.label = label
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers=default_headers or {},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: Any = None,
    ) -> Any:
        try:
            response = self._client.request(
                method=method,
                url=path,
                params=params,
                json=json,
                headers=headers,
                content=data if isinstance(data, (str, bytes)) else None,
                data=None if isinstance(data, (str, bytes)) else data,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _extract_error_detail(exc.response)
            logger.error(
                "%s request failed with status %s on %s: %s",
                self.label,
                exc.response.status_code,
                path,
                detail,
            )
            raise AdapterRequestError(
                f"{self.label} request failed with status {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.error("%s transport error on %s: %s", self.label, path, exc)
            raise AdapterRequestError(f"{self.label} transport error: {exc}") from exc

        if response.status_code == 204 or not response.content:
            return {}

        try:
            return response.json()
        except ValueError as exc:
            logger.error("%s returned non-JSON payload on %s", self.label, path)
            raise AdapterParseError(f"{self.label} returned non-JSON payload") from exc


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason_phrase

    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, list) and value:
                return ", ".join(str(item) for item in value)

    return response.text.strip() or response.reason_phrase
