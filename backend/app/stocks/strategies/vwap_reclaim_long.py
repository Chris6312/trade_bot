from __future__ import annotations

from backend.app.common.strategy_support import (
    StrategyEvaluationInput,
    build_outcome,
    current_entry_policy,
    decimal_to_float,
    default_component_scores,
    latest_candle,
    normalized_threshold,
    previous_candle,
    ratio_score,
    regime_gate_reasons,
)

STRATEGY_NAME = "vwap_reclaim_long"


def evaluate(inputs: StrategyEvaluationInput):
    feature = inputs.feature_snapshot
    candle = latest_candle(inputs.candles)
    previous = previous_candle(inputs.candles)
    if feature is None or candle is None:
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
    relative_volume_20 = decimal_to_float(feature.relative_volume_20)
    vwap = decimal_to_float(candle.vwap)
    previous_close = decimal_to_float(previous.close) if previous is not None else None
    previous_vwap = decimal_to_float(previous.vwap) if previous is not None else None

    trend_score, participation_score, liquidity_score, stability_score = default_component_scores(inputs)
    threshold = normalized_threshold(0.59, current_entry_policy(inputs))
    blocked_reasons = regime_gate_reasons(inputs)

    if vwap is None:
        blocked_reasons.append("vwap_missing")
    if close is None or ema_20 is None or close <= ema_20:
        blocked_reasons.append("close_below_ema20")
    if close is None or vwap is None or close <= vwap:
        blocked_reasons.append("close_below_vwap")
    if previous is None:
        blocked_reasons.append("insufficient_candles")
    elif previous_close is not None and previous_vwap is not None and previous_close > previous_vwap:
        blocked_reasons.append("already_above_vwap")
    if relative_volume_20 is None or relative_volume_20 < 0.9:
        blocked_reasons.append("participation_too_low")

    reclaim_distance = None
    if close is not None and vwap not in (None, 0):
        reclaim_distance = (close - vwap) / vwap
    signal_score = ratio_score(reclaim_distance, target=0.012)

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
            "reclaim_distance_from_vwap": round(reclaim_distance, 6) if reclaim_distance is not None else None,
        },
    )
