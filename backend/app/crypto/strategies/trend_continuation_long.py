from __future__ import annotations

from backend.app.common.strategy_support import (
    StrategyEvaluationInput,
    build_outcome,
    current_entry_policy,
    decimal_to_float,
    default_component_scores,
    normalized_threshold,
    percent_distance,
    ratio_score,
    regime_gate_reasons,
)

STRATEGY_NAME = "trend_continuation_long"


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
    ema_20 = decimal_to_float(feature.ema_20)
    sma_20 = decimal_to_float(feature.sma_20)
    momentum_20 = decimal_to_float(feature.momentum_20)
    trend_slope_20 = decimal_to_float(feature.trend_slope_20)

    trend_score, participation_score, liquidity_score, stability_score = default_component_scores(inputs)
    threshold = normalized_threshold(0.61, current_entry_policy(inputs))
    blocked_reasons = regime_gate_reasons(inputs)

    if close is None or ema_20 is None or close <= ema_20:
        blocked_reasons.append("close_below_ema20")
    if close is None or sma_20 is None or close <= sma_20:
        blocked_reasons.append("close_below_sma20")
    if momentum_20 is None or momentum_20 <= 0.012:
        blocked_reasons.append("momentum_too_weak")
    if trend_slope_20 is None or trend_slope_20 <= 0.006:
        blocked_reasons.append("trend_slope_too_weak")

    extension_from_ema = percent_distance(close, ema_20)
    if extension_from_ema is None or extension_from_ema > 0.06:
        blocked_reasons.append("trend_too_extended")
    signal_score = ratio_score(0.07 - min(extension_from_ema or 0.07, 0.07), target=0.07)

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
            "extension_from_ema20": round(extension_from_ema, 6) if extension_from_ema is not None else None,
        },
    )
