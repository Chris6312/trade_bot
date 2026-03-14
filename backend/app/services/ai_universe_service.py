from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from backend.app.core.config import Settings, get_settings


@dataclass
class AIUniverseService:
    settings: Settings | None = None

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = get_settings()

    def rank_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candidates:
            return []
        settings = self.settings
        assert settings is not None

        if not settings.ai_enabled:
            raise ValueError("AI universe ranking is disabled")
        if not settings.ai_api_url:
            raise ValueError("AI API URL is not configured")
        if not settings.ai_api_key:
            raise ValueError("AI API key is not configured")

        compact: list[dict[str, Any]] = []
        for candidate in candidates:
            compact.append(
                {
                    "symbol": str(candidate.get("symbol") or "").upper(),
                    "volume": candidate.get("volume"),
                    "trade_count": candidate.get("trade_count"),
                    "dollar_volume": candidate.get("dollar_volume"),
                    "price": candidate.get("price"),
                    "change_percent": candidate.get("change_percent"),
                    "name": candidate.get("name"),
                    "sector": candidate.get("sector"),
                }
            )

        prompt = (
            "You will rank stock universe candidates for a small-account trading bot watchlist. "
            "These candidates already came from a liquid most-actives screen. Favor liquid, institutional, "
            "cleanly tradable names. Penalize noisy names, leveraged ETFs, and unclear symbols. "
            "Return ONLY a JSON object with a single field named 'rankings'.\n"
            "Each rankings item must contain: symbol, ai_rank_score, confidence, brief_reason.\n"
            f"Maximum final list size target: {settings.stock_universe_max_size}.\n"
            f"Candidates: {json.dumps(compact)}"
        )

        payload = {
            "model": settings.ai_model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "stock_universe_rankings",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "rankings": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "symbol": {"type": "string"},
                                        "ai_rank_score": {"type": "number"},
                                        "confidence": {"type": "number"},
                                        "brief_reason": {"type": "string"},
                                    },
                                    "required": ["symbol", "ai_rank_score", "confidence", "brief_reason"],
                                },
                            }
                        },
                        "required": ["rankings"],
                    },
                }
            },
        }

        headers = {
            "Authorization": f"Bearer {settings.ai_api_key}",
            "Content-Type": "application/json",
        }
        url = settings.ai_api_url.rstrip("/") + "/responses"

        with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        text = self._extract_response_text(data)
        if not text:
            raise ValueError(f"AI provider returned no text content. Keys={list(data.keys())}")

        parsed = json.loads(text)
        rankings = parsed.get("rankings")
        if not isinstance(rankings, list):
            raise ValueError("AI provider returned invalid rankings payload")

        output: list[dict[str, Any]] = []
        for item in rankings:
            if not isinstance(item, dict):
                continue
            output.append(
                {
                    "symbol": str(item.get("symbol") or "").upper(),
                    "ai_rank_score": float(item.get("ai_rank_score", 0.0)),
                    "confidence": float(item.get("confidence", 0.0)),
                    "brief_reason": str(item.get("brief_reason") or "")[:140],
                }
            )
        return output

    @staticmethod
    def _extract_response_text(data: dict[str, Any]) -> str | None:
        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    for child in content:
                        if not isinstance(child, dict):
                            continue
                        if isinstance(child.get("text"), str):
                            return child["text"]
                        if child.get("type") == "output_text" and isinstance(child.get("text"), str):
                            return child["text"]

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message") or first
                if isinstance(message, dict):
                    for key in ("content", "text", "message"):
                        value = message.get(key)
                        if isinstance(value, str):
                            return value

        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return output_text

        return None
