from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import sqrt
from statistics import fmean, pstdev
from typing import Any, Iterable, Sequence

from backend.app.models.core import Candle, FeatureSnapshot, RegimeSnapshot
from backend.app.services.candle_service import ensure_utc

STRATEGY_STATUS_READY = "ready"
STRATEGY_STATUS_BLOCKED = "blocked"
ENTRY_POLICY_FULL = "full"
ENTRY_POLICY_REDUCED = "reduced"
ENTRY_POLICY_BLOCKED = "blocked"


@dataclass(slots=True, frozen=True)
class StrategyEvaluationInput:
    asset_class: str
    venue: str
    symbol: str
    timeframe: str
    feature_snapshot: FeatureSnapshot | None
    regime_snapshot: RegimeSnapshot | None
    candles: tuple[Candle, ...]
    computed_at: datetime


@dataclass(slots=True, frozen=True)
class StrategyOutcome:
    strategy_name: str
    direction: str
    status: str
    readiness_score: float
    composite_score: float
    threshold_score: float
    trend_score: float
    participation_score: float
    liquidity_score: float
    stability_score: float
    blocked_reasons: tuple[str, ...] = field(default_factory=tuple)
    decision_reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class StrategyDefinition:
    name: str
    evaluator: callable


def decimal_to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def clamp_score(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 6)


def normalized_threshold(base_threshold: float, entry_policy: str | None) -> float:
    if entry_policy == ENTRY_POLICY_REDUCED:
        return clamp_score(base_threshold + 0.075)
    if entry_policy == ENTRY_POLICY_BLOCKED:
        return 1.0
    return clamp_score(base_threshold)


def primary_block_reason(reasons: Sequence[str], *, default: str = "candidate_ready") -> str:
    return reasons[0] if reasons else default


def current_entry_policy(inputs: StrategyEvaluationInput) -> str | None:
    if inputs.regime_snapshot is None:
        return None
    return inputs.regime_snapshot.entry_policy


def regime_name(inputs: StrategyEvaluationInput) -> str | None:
    if inputs.regime_snapshot is None:
        return None
    return inputs.regime_snapshot.regime


def regime_gate_reasons(inputs: StrategyEvaluationInput) -> list[str]:
    if inputs.regime_snapshot is None:
        return ["regime_unavailable"]
    if inputs.regime_snapshot.entry_policy == ENTRY_POLICY_BLOCKED:
        return ["regime_blocked"]
    return []


def latest_candle(candles: Sequence[Candle]) -> Candle | None:
    if not candles:
        return None
    return candles[-1]


def previous_candle(candles: Sequence[Candle]) -> Candle | None:
    if len(candles) < 2:
        return None
    return candles[-2]


def highest_high(candles: Sequence[Candle], *, lookback: int, exclude_latest: bool = True) -> float | None:
    if not candles:
        return None
    pool = list(candles[:-1] if exclude_latest else candles)
    if not pool:
        return None
    subset = pool[-lookback:]
    if not subset:
        return None
    return max(float(item.high) for item in subset)


def lowest_low(candles: Sequence[Candle], *, lookback: int, exclude_latest: bool = True) -> float | None:
    if not candles:
        return None
    pool = list(candles[:-1] if exclude_latest else candles)
    if not pool:
        return None
    subset = pool[-lookback:]
    if not subset:
        return None
    return min(float(item.low) for item in subset)


def percent_distance(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return abs(a - b) / abs(b)


def slope_score(value: float | None, *, target: float) -> float:
    if value is None or target <= 0:
        return 0.0
    return clamp_score(value / target)


def ratio_score(value: float | None, *, target: float) -> float:
    if value is None or target <= 0:
        return 0.0
    return clamp_score(value / target)


def inverse_ratio_score(value: float | None, *, target: float) -> float:
    if value is None or target <= 0:
        return 0.0
    return clamp_score(1.0 - (value / target))


def bool_score(condition: bool) -> float:
    return 1.0 if condition else 0.0


def composite_score(*scores: float, weights: Sequence[float] | None = None) -> float:
    if not scores:
        return 0.0
    if weights is None:
        return clamp_score(fmean(scores))
    total_weight = float(sum(weights))
    if total_weight <= 0:
        return clamp_score(fmean(scores))
    weighted = sum(score * weight for score, weight in zip(scores, weights, strict=False)) / total_weight
    return clamp_score(weighted)


def default_component_scores(inputs: StrategyEvaluationInput) -> tuple[float, float, float, float]:
    feature = inputs.feature_snapshot
    if feature is None:
        return 0.0, 0.0, 0.0, 0.0

    close = decimal_to_float(feature.close)
    sma_20 = decimal_to_float(feature.sma_20)
    ema_20 = decimal_to_float(feature.ema_20)
    momentum_20 = decimal_to_float(feature.momentum_20)
    relative_volume_20 = decimal_to_float(feature.relative_volume_20)
    dollar_volume = decimal_to_float(feature.dollar_volume)
    dollar_volume_sma_20 = decimal_to_float(feature.dollar_volume_sma_20)
    realized_volatility_20 = decimal_to_float(feature.realized_volatility_20)
    atr_14 = decimal_to_float(feature.atr_14)
    trend_slope_20 = decimal_to_float(feature.trend_slope_20)

    trend_score_value = composite_score(
        bool_score(close is not None and sma_20 is not None and close > sma_20),
        bool_score(close is not None and ema_20 is not None and close > ema_20),
        ratio_score(momentum_20, target=0.05),
        slope_score(trend_slope_20, target=0.02),
    )
    participation_score_value = composite_score(
        ratio_score(relative_volume_20, target=1.2),
        ratio_score(momentum_20, target=0.03),
    )

    if inputs.asset_class == "stock":
        liquidity_score_value = composite_score(
            ratio_score(dollar_volume, target=500_000),
            ratio_score(dollar_volume_sma_20, target=400_000),
        )
        volatility_target = 0.035
    else:
        liquidity_score_value = composite_score(
            ratio_score(dollar_volume, target=2_500_000),
            ratio_score(dollar_volume_sma_20, target=2_000_000),
        )
        volatility_target = 0.08

    atr_ratio = None
    if close and atr_14 is not None and close != 0:
        atr_ratio = atr_14 / close
    stability_score_value = composite_score(
        inverse_ratio_score(realized_volatility_20, target=volatility_target),
        inverse_ratio_score(atr_ratio, target=0.04 if inputs.asset_class == "stock" else 0.07),
    )
    return trend_score_value, participation_score_value, liquidity_score_value, stability_score_value


def compute_rsi(candles: Sequence[Candle], *, period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    closes = [float(item.close) for item in candles[-(period + 1) :]]
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(closes, closes[1:], strict=False):
        delta = current - previous
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    if average_loss == 0:
        return 100.0
    rs = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_bollinger_position(
    candles: Sequence[Candle],
    *,
    period: int = 20,
    stdev_multiplier: float = 2.0,
) -> tuple[float | None, float | None, float | None]:
    if len(candles) < period:
        return None, None, None
    closes = [float(item.close) for item in candles[-period:]]
    middle = fmean(closes)
    stdev = pstdev(closes)
    upper = middle + (stdev * stdev_multiplier)
    lower = middle - (stdev * stdev_multiplier)
    return lower, middle, upper


def candidate_timestamp(inputs: StrategyEvaluationInput) -> datetime:
    if inputs.feature_snapshot is not None and ensure_utc(inputs.feature_snapshot.candle_timestamp) is not None:
        return ensure_utc(inputs.feature_snapshot.candle_timestamp) or inputs.computed_at
    if inputs.regime_snapshot is not None and ensure_utc(inputs.regime_snapshot.regime_timestamp) is not None:
        return ensure_utc(inputs.regime_snapshot.regime_timestamp) or inputs.computed_at
    latest = latest_candle(inputs.candles)
    if latest is not None and ensure_utc(latest.timestamp) is not None:
        return ensure_utc(latest.timestamp) or inputs.computed_at
    return ensure_utc(inputs.computed_at) or datetime.now(UTC)


def build_outcome(
    *,
    strategy_name: str,
    threshold_score: float,
    trend_score: float,
    participation_score: float,
    liquidity_score: float,
    stability_score: float,
    signal_score: float,
    blocked_reasons: Iterable[str],
    payload: dict[str, Any] | None = None,
) -> StrategyOutcome:
    reasons = tuple(dict.fromkeys(blocked_reasons))
    composite = composite_score(
        trend_score,
        participation_score,
        liquidity_score,
        stability_score,
        signal_score,
        weights=(0.28, 0.18, 0.18, 0.16, 0.20),
    )
    if composite < threshold_score:
        reasons = tuple(dict.fromkeys([*reasons, "composite_below_threshold"]))
    status = STRATEGY_STATUS_READY if not reasons else STRATEGY_STATUS_BLOCKED
    readiness = composite if status == STRATEGY_STATUS_READY else max(0.0, min(composite, threshold_score))
    return StrategyOutcome(
        strategy_name=strategy_name,
        direction="long",
        status=status,
        readiness_score=clamp_score(readiness),
        composite_score=clamp_score(composite),
        threshold_score=clamp_score(threshold_score),
        trend_score=clamp_score(trend_score),
        participation_score=clamp_score(participation_score),
        liquidity_score=clamp_score(liquidity_score),
        stability_score=clamp_score(stability_score),
        blocked_reasons=reasons,
        decision_reason=primary_block_reason(reasons),
        payload=payload or {},
    )
