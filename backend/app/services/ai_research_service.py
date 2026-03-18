"""ai_research_service.py

Drives the premarket stock research scan.

Sends a swing-trader prompt (with live ET timestamp + available cash) to the
OpenAI *responses* endpoint with the ``web_search_preview`` tool enabled so the
model can pull real premarket data.  Returns a validated list of AiResearchPickResult
objects that callers persist via AiResearchPersistService.
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

_NY_TZ = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class AiResearchPickResult:
    symbol: str
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
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(*, et_now: datetime, cash_available: Decimal | None) -> str:
    ts = et_now.strftime("%A %B %d, %Y %I:%M %p ET")
    cash_str = f"${float(cash_available):,.2f}" if cash_available is not None else "unknown"

    return (
        f"You are an experienced swing trader and equity analyst with real-time market access. "
        f"It's currently {ts}. "
        f"The broader market context is [use your web search access to note futures direction and any "
        f"macro catalysts active right now — e.g., CPI data, Fed speak, sector rotation signals].\n\n"
        f"Perform a fresh, comprehensive premarket/opening-bell scan for 10–15 stocks "
        f"(liquid names, market cap > $5B preferred, avoid pure pennies) that appear **poised for "
        f"positive gains today or this week** based on:\n"
        f"- Latest breaking news (earnings beats/guidance raises, partnerships, FDA approvals, "
        f"upgrades, sector tailwinds like AI/data centers, defense, energy/infra)\n"
        f"- Premarket % moves, volume, and unusual activity\n"
        f"- Analyst upgrades, price target hikes, or strong buy consensus\n"
        f"- Company-specific catalysts decoupling from broader market\n"
        f"- X/Twitter sentiment and fast-moving narratives (if relevant)\n\n"
        f"Account size context (for calibrating setup conviction only): {cash_str} available cash. "
        f"Do NOT suggest position sizes — the trading system handles all position sizing internally "
        f"using ATR-based stops and account risk rules.\n\n"
        f"Return ONLY a JSON object with a single top-level key \"picks\". "
        f"Each pick must include ALL of these fields:\n"
        f"  symbol              (string, e.g. \"NVDA\")\n"
        f"  catalyst            (string, 1-2 sentence max, focus on today's specific driver)\n"
        f"  approximate_price   (number or null — current/premarket price)\n"
        f"  entry_zone_low      (number or null — lower end of ideal entry range)\n"
        f"  entry_zone_high     (number or null — upper end of ideal entry range)\n"
        f"  stop_loss           (number or null — below key support, ~3-5% max from entry)\n"
        f"  take_profit_primary (number or null — primary target, 8-15%+ from entry)\n"
        f"  take_profit_stretch (number or null — optional extended target, else null)\n"
        f"  use_trail_stop      (boolean — true if trailing stop suits this setup better than fixed)\n"
        f"  risk_reward_note    (string — one quick tip: volume confirmation, key level, timing risk)\n"
        f"  is_bonus_pick       (boolean — true for 2-3 higher-volatility/speculative bonus ideas)\n\n"
        f"Prioritize 10–12 strongest setups with specific, real catalysts confirmed by web search. "
        f"Include 2–3 bonus picks (is_bonus_pick=true) for higher-conviction speculative setups. "
        f"Do not include any explanation outside the JSON object."
    )


# ---------------------------------------------------------------------------
# JSON schema for structured output
# ---------------------------------------------------------------------------

_PICK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "symbol":                 {"type": "string"},
        "catalyst":               {"type": "string"},
        "approximate_price":      {"type": ["number", "null"]},
        "entry_zone_low":         {"type": ["number", "null"]},
        "entry_zone_high":        {"type": ["number", "null"]},
        "stop_loss":              {"type": ["number", "null"]},
        "take_profit_primary":    {"type": ["number", "null"]},
        "take_profit_stretch":    {"type": ["number", "null"]},
        "use_trail_stop":         {"type": "boolean"},
        "risk_reward_note":       {"type": "string"},
        "is_bonus_pick":          {"type": "boolean"},
    },
    "required": [
        "symbol", "catalyst", "approximate_price",
        "entry_zone_low", "entry_zone_high",
        "stop_loss", "take_profit_primary", "take_profit_stretch",
        "use_trail_stop",
        "risk_reward_note", "is_bonus_pick",
    ],
}

_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "picks": {
            "type": "array",
            "items": _PICK_SCHEMA,
        }
    },
    "required": ["picks"],
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

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
        """Call OpenAI with the premarket swing-trader prompt.

        *cash_available* is injected into the prompt.
        *now* defaults to the current wall clock time; callers may pass a fixed
        value for deterministic testing.
        """
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
                    "name": "premarket_research_picks",
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

        raw_picks = _parse_picks(text)
        results = [_coerce_pick(p) for p in raw_picks if isinstance(p, dict)]

        logger.info(
            "ai_research_scan_complete",
            extra={"pick_count": len(results)},
        )
        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_response_text(data: dict[str, Any]) -> str | None:
    """Handle both OpenAI /responses and /chat/completions response shapes."""
    # /responses shape: output[].content[].text
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

    # /chat/completions shape
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


def _parse_picks(text: str) -> list[Any]:
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()
    parsed = json.loads(text)
    picks = parsed.get("picks")
    if not isinstance(picks, list):
        raise ValueError("AI research response missing 'picks' array")
    return picks


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _coerce_pick(raw: dict[str, Any]) -> AiResearchPickResult:
    return AiResearchPickResult(
        symbol=str(raw.get("symbol") or "").upper().strip(),
        catalyst=str(raw.get("catalyst") or "")[:500],
        approximate_price=_to_decimal(raw.get("approximate_price")),
        entry_zone_low=_to_decimal(raw.get("entry_zone_low")),
        entry_zone_high=_to_decimal(raw.get("entry_zone_high")),
        stop_loss=_to_decimal(raw.get("stop_loss")),
        take_profit_primary=_to_decimal(raw.get("take_profit_primary")),
        take_profit_stretch=_to_decimal(raw.get("take_profit_stretch")),
        use_trail_stop=bool(raw.get("use_trail_stop", False)),
        position_size_dollars=_to_decimal(raw.get("position_size_dollars")),
        risk_reward_note=str(raw.get("risk_reward_note") or "")[:300],
        is_bonus_pick=bool(raw.get("is_bonus_pick", False)),
        raw=raw,
    )
