from __future__ import annotations

import json

import pytest

from backend.app.services.ai_research_service import (
    AI_RESEARCH_MAX_TOTAL_PICKS,
    _build_prompt,
    _parse_contract_response,
)


def test_ai_research_contract_response_orders_ready_then_watchlist_and_caps_total() -> None:
    payload = {
        "ready_now": [
            {
                "symbol": "NVDA",
                "reason": "Strong catalyst and clean intraday structure.",
                "quality_1h": "high",
                "quality_15m": "high",
                "reclaim_state": "reclaimable",
                "risk_note": "Watch for reclaim failure under VWAP.",
                "approximate_price": 900.5,
            },
            {
                "symbol": "MSFT",
                "reason": "Trend intact and not obviously extended.",
                "quality_1h": "high",
                "quality_15m": "medium",
                "reclaim_state": "reclaimable",
                "risk_note": "Needs clean 5m pullback first.",
                "approximate_price": 410.0,
            },
        ],
        "watchlist": [
            {
                "symbol": "META",
                "reason": "Watch for 5m reclaim later.",
                "quality_1h": "high",
                "quality_15m": "high",
                "reclaim_state": "mixed",
                "risk_note": "Do not chase extension.",
                "approximate_price": 515.0,
            },
            {
                "symbol": "AMD",
                "reason": "Strong liquidity and setup context.",
                "quality_1h": "medium",
                "quality_15m": "medium",
                "reclaim_state": "reclaimable",
                "risk_note": "News follow-through matters.",
                "approximate_price": 188.0,
            },
            {
                "symbol": "AVGO",
                "reason": "Quality trend, waiting for trigger.",
                "quality_1h": "high",
                "quality_15m": "medium",
                "reclaim_state": "mixed",
                "risk_note": "Respect extension risk.",
                "approximate_price": 1410.0,
            },
            {
                "symbol": "AAPL",
                "reason": "Should be truncated by the hard cap.",
                "quality_1h": "medium",
                "quality_15m": "medium",
                "reclaim_state": "reclaimable",
                "risk_note": "Needs stronger catalyst.",
                "approximate_price": 215.0,
            },
        ],
        "none": {"explicit": False, "reason": "Picks were found."},
    }

    rows = _parse_contract_response(json.dumps(payload))

    assert len(rows) == AI_RESEARCH_MAX_TOTAL_PICKS
    assert [row.symbol for row in rows] == ["NVDA", "MSFT", "META", "AMD", "AVGO"]
    assert [row.bucket for row in rows] == ["ready_now", "ready_now", "watchlist", "watchlist", "watchlist"]
    assert rows[0].raw["contract_version"] == "paper_test_v1"
    assert rows[0].risk_reward_note == "Watch for reclaim failure under VWAP."


def test_ai_research_contract_response_requires_explicit_none_when_no_picks() -> None:
    payload = {
        "ready_now": [],
        "watchlist": [],
        "none": {"explicit": True, "reason": "Nothing met the contract."},
    }

    rows = _parse_contract_response(json.dumps(payload))

    assert rows == []


def test_ai_research_contract_response_rejects_missing_explicit_none() -> None:
    payload = {
        "ready_now": [],
        "watchlist": [],
        "none": {"explicit": False, "reason": "Should have been NONE."},
    }

    with pytest.raises(ValueError, match="must mark none.explicit=true"):
        _parse_contract_response(json.dumps(payload))


def test_ai_research_prompt_mentions_strict_bucketed_contract() -> None:
    prompt = _build_prompt(et_now=__import__('datetime').datetime(2026, 3, 19, 8, 40), cash_available=None)

    assert "READY_NOW" in prompt
    assert "WATCHLIST" in prompt
    assert "none.explicit=true" in prompt
    assert "Maximum total symbols" in prompt
