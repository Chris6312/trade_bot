"""ai_research_service.py

Drives the premarket stock research scan.

Sends a strict stock paper-contract prompt to the OpenAI *responses* endpoint
with the ``web_search_preview`` tool enabled so the model can pull fresh market
context. Returns a validated, ordered list of ``AiResearchPickResult`` objects
that callers persist via ``AiResearchWorker``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from backend.app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

AI_RESEARCH_RESPONSE_TIMEOUT = 240.0
AI_RESEARCH_CONNECT_TIMEOUT = 15.0
AI_RESEARCH_MAX_TOTAL_PICKS = 5

_NY_TZ = ZoneInfo("America/New_York")
_VALID_BUCKETS = {"ready_now", "watchlist"}
_VALID_QUALITY = {"high", "medium", "low", "unknown"}
_VALID_RECLAIM_STATES = {"reclaimable", "extended", "mixed", "unknown"}


@dataclass
class AiResearchPickResult:
    symbol: str
    bucket: str
    catalyst: str
    approximate_price: Decimal | None
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    stop_loss: Decimal | None
    take_profit_primary: Decimal | None
    take_profit_stretch: Decimal | None
    use_trail_stop: bool
    position_size_dollars: Decimal | None
    risk_reward_note: str
    is_bonus_pick: bool
    structure_quality_1h: str = "unknown"
    structure_quality_15m: str = "unknown"
    reclaim_state: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


def _build_prompt(*, et_now: datetime, cash_available: Decimal | None) -> str:
    ts = et_now.strftime("%A %B %d, %Y %I:%M %p ET")
    cash_str = f"${float(cash_available):,.2f}" if cash_available is not None else "unknown"

    return f"""You are selecting stocks for a paper-trading watchlist built around a strict multi-timeframe trend-and-reclaim contract. It's currently {ts}. Use web search to ground the answer in today's real market context, news, premarket action, and catalysts.

Your task is NOT to produce a broad ideas list. Your task is to return only liquid U.S. stocks that are most likely to produce valid setups under this contract today. Favor institutional, high-volume names with real movement and clean structure. Avoid thin names, messy charts, leveraged ETFs, and names that already look too extended for a fresh reclaim.

Paper-trading contract:
1. Higher-timeframe trend quality matters first.
2. We want names likely to pass:
   - 1h bias: fast MA above slow MA and price above both
   - 15m setup: fast MA above slow MA and price above both
3. Entry is allowed only after a fresh 5m reclaim:
   - price above VWAP
   - price above EMA9
   - recent pullback into EMA9 and/or VWAP
   - bullish reclaim candle after the pullback
4. Be strict. Fewer high-quality names are better than many weak names.
5. Maximum total symbols across READY_NOW and WATCHLIST combined: {AI_RESEARCH_MAX_TOTAL_PICKS}.

Account size context for setup selectivity only: {cash_str}. Do NOT suggest sizing. The trading system handles risk, sizing, stops, and targets.

Return ONLY a JSON object using this shape:
{{
  "ready_now": [{{pick}}, ...],
  "watchlist": [{{pick}}, ...],
  "none": {{"explicit": true|false, "reason": string}}
}}

Each pick must include:
  symbol                (string, e.g. "NVDA")
  reason                (string, why it fits this contract today)
  quality_1h            (one of: high, medium, low, unknown)
  quality_15m           (one of: high, medium, low, unknown)
  reclaim_state         (one of: reclaimable, extended, mixed, unknown)
  risk_note             (string, one-line risk note)
  approximate_price     (number or null)

Rules for buckets:
- ready_now: closest to satisfying the full contract right now
- watchlist: strong 1h and 15m structure, waiting for a 5m pullback/reclaim
- if nothing is good enough, set both arrays empty and set none.explicit=true
- if you provide any picks, set none.explicit=false
- do not add any text outside the JSON object"""


_PICK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "symbol": {"type": "string"},
        "reason": {"type": "string"},
        "quality_1h": {"type": "string", "enum": sorted(_VALID_QUALITY)},
        "quality_15m": {"type": "string", "enum": sorted(_VALID_QUALITY)},
        "reclaim_state": {"type": "string", "enum": sorted(_VALID_RECLAIM_STATES)},
        "risk_note": {"type": "string"},
        "approximate_price": {"type": ["number", "null"]},
    },
    "required": [
        "symbol",
        "reason",
        "quality_1h",
        "quality_15m",
        "reclaim_state",
        "risk_note",
        "approximate_price",
    ],
}

_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ready_now": {"type": "array", "items": _PICK_SCHEMA},
        "watchlist": {"type": "array", "items": _PICK_SCHEMA},
        "none": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "explicit": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["explicit", "reason"],
        },
    },
    "required": ["ready_now", "watchlist", "none"],
}


@dataclass
class AiResearchService:
    settings: Settings | None = None

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = get_settings()

    def run_premarket_scan(
        self,
        *,
        cash_available: Decimal | None,
        now: datetime | None = None,
    ) -> list[AiResearchPickResult]:
        settings = self.settings
        assert settings is not None

        if not settings.ai_enabled:
            raise ValueError("AI research scan is disabled (ai_enabled=False)")
        if not settings.ai_api_url:
            raise ValueError("AI API URL is not configured")
        if not settings.ai_api_key:
            raise ValueError("AI API key is not configured")

        et_now = (now or datetime.now(_NY_TZ)).astimezone(_NY_TZ)
        prompt = _build_prompt(et_now=et_now, cash_available=cash_available)

        payload: dict[str, Any] = {
            "model": settings.ai_model,
            "tools": [{"type": "web_search_preview"}],
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "paper_contract_watchlist",
                    "strict": True,
                    "schema": _RESPONSE_SCHEMA,
                }
            },
        }

        headers = {
            "Authorization": f"Bearer {settings.ai_api_key}",
            "Content-Type": "application/json",
        }
        url = settings.ai_api_url.rstrip("/") + "/responses"

        logger.info(
            "ai_research_scan_started",
            extra={"et_time": et_now.isoformat(), "cash": str(cash_available)},
        )

        with httpx.Client(
            timeout=httpx.Timeout(AI_RESEARCH_RESPONSE_TIMEOUT, connect=AI_RESEARCH_CONNECT_TIMEOUT)
        ) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        text = _extract_response_text(data)
        if not text:
            raise ValueError(f"AI research: provider returned no text. Keys={list(data.keys())}")

        results = _parse_contract_response(text)

        logger.info(
            "ai_research_scan_complete",
            extra={"pick_count": len(results)},
        )
        return results


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
                    if child.get("type") in ("output_text", "text") and isinstance(child.get("text"), str):
                        return child["text"]

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message") or first
            if isinstance(msg, dict):
                for key in ("content", "text", "message"):
                    val = msg.get(key)
                    if isinstance(val, str):
                        return val

    if isinstance(data.get("output_text"), str):
        return data["output_text"]

    return None


def _parse_contract_response(text: str) -> list[AiResearchPickResult]:
    payload = _parse_json_object(text)
    ready_now = payload.get("ready_now")
    watchlist = payload.get("watchlist")
    none_section = payload.get("none") or {}

    if not isinstance(ready_now, list) or not isinstance(watchlist, list):
        raise ValueError("AI research response missing ready_now/watchlist arrays")
    if not isinstance(none_section, dict) or not isinstance(none_section.get("explicit"), bool):
        raise ValueError("AI research response missing none section")

    picks: list[AiResearchPickResult] = []
    for bucket, items in (("ready_now", ready_now), ("watchlist", watchlist)):
        for raw in items:
            if not isinstance(raw, dict):
                continue
            picks.append(_coerce_pick(raw, bucket=bucket))
            if len(picks) >= AI_RESEARCH_MAX_TOTAL_PICKS:
                return picks

    if picks and bool(none_section.get("explicit")):
        raise ValueError("AI research response cannot mark none.explicit=true when picks are present")
    if not picks and not bool(none_section.get("explicit")):
        raise ValueError("AI research response must mark none.explicit=true when no picks qualify")

    return picks


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```"))
        text = text.strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("AI research response must be a JSON object")
    return parsed


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _normalize_token(value: Any, *, valid: set[str], default: str) -> str:
    token = str(value or "").strip().lower()
    return token if token in valid else default


def _coerce_pick(raw: dict[str, Any], *, bucket: str) -> AiResearchPickResult:
    symbol = str(raw.get("symbol") or "").upper().strip()
    reason = str(raw.get("reason") or "").strip()
    risk_note = str(raw.get("risk_note") or "").strip()
    quality_1h = _normalize_token(raw.get("quality_1h"), valid=_VALID_QUALITY, default="unknown")
    quality_15m = _normalize_token(raw.get("quality_15m"), valid=_VALID_QUALITY, default="unknown")
    reclaim_state = _normalize_token(raw.get("reclaim_state"), valid=_VALID_RECLAIM_STATES, default="unknown")
    normalized_bucket = bucket if bucket in _VALID_BUCKETS else "watchlist"

    raw_payload = dict(raw)
    raw_payload.update(
        {
            "bucket": normalized_bucket,
            "quality_1h": quality_1h,
            "quality_15m": quality_15m,
            "reclaim_state": reclaim_state,
            "contract_version": "paper_test_v1",
            "ai_named": True,
        }
    )

    return AiResearchPickResult(
        symbol=symbol,
        bucket=normalized_bucket,
        catalyst=reason[:500],
        approximate_price=_to_decimal(raw.get("approximate_price")),
        entry_zone_low=None,
        entry_zone_high=None,
        stop_loss=None,
        take_profit_primary=None,
        take_profit_stretch=None,
        use_trail_stop=False,
        position_size_dollars=None,
        risk_reward_note=risk_note[:300],
        is_bonus_pick=False,
        structure_quality_1h=quality_1h,
        structure_quality_15m=quality_15m,
        reclaim_state=reclaim_state,
        raw=raw_payload,
    )
