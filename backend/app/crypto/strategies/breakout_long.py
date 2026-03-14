from __future__ import annotations

from backend.app.common.strategy_support import (
    StrategyEvaluationInput,
    build_outcome,
    current_entry_policy,
    decimal_to_float,
    default_component_scores,
    highest_high,
    normalized_threshold,
    ratio_score,
    regime_gate_reasons,
)

STRATEGY_NAME = "breakout_long"


def evaluate(inputs: StrategyEvaluationInput):
    feature = inputs.feature_snapshot
    if feature is None:
        return build_outcome(
            strategy_name=STRATEGY_NAME,
            threshold_score=1.0,
            trend_score=0.0,
            participation_score=0.0,
            liquidity_score=0.0,
            stability_score=0.0,
            signal_score=0.0,
            blocked_reasons=("missing_feature_snapshot",),
            payload={},
        )

    close = decimal_to_float(feature.close)
    relative_volume_20 = decimal_to_float(feature.relative_volume_20)
    momentum_20 = decimal_to_float(feature.momentum_20)
    recent_high = highest_high(inputs.candles, lookback=10, exclude_latest=True)

    trend_score, participation_score, liquidity_score, stability_score = default_component_scores(inputs)
    threshold = normalized_threshold(0.62, current_entry_policy(inputs))
    blocked_reasons = regime_gate_reasons(inputs)

    if recent_high is None:
        blocked_reasons.append("insufficient_candles")
    if close is None or recent_high is None or close <= recent_high:
        blocked_reasons.append("no_recent_breakout")
    if relative_volume_20 is None or relative_volume_20 < 1.0:
        blocked_reasons.append("participation_too_low")
    if momentum_20 is None or momentum_20 <= 0.012:
        blocked_reasons.append("momentum_too_weak")

    breakout_pct = None
    if close is not None and recent_high not in (None, 0):
        breakout_pct = (close - recent_high) / recent_high
    signal_score = ratio_score(breakout_pct, target=0.02)

    return build_outcome(
        strategy_name=STRATEGY_NAME,
        threshold_score=threshold,
        trend_score=trend_score,
        participation_score=participation_score,
        liquidity_score=liquidity_score,
        stability_score=stability_score,
        signal_score=signal_score,
        blocked_reasons=blocked_reasons,
        payload={
            "breakout_pct": round(breakout_pct, 6) if breakout_pct is not None else None,
            "reference_high": recent_high,
        },
    )
