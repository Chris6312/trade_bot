from __future__ import annotations

from backend.app.common.strategy_support import (
    StrategyEvaluationInput,
    build_outcome,
    clamp_score,
    compute_bollinger_position,
    compute_rsi,
    current_entry_policy,
    decimal_to_float,
    default_component_scores,
    latest_candle,
    normalized_threshold,
    previous_candle,
    regime_gate_reasons,
)

STRATEGY_NAME = "bbrsi_mean_reversion_long"


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
    rsi = compute_rsi(inputs.candles, period=14)
    lower_band, middle_band, upper_band = compute_bollinger_position(inputs.candles, period=20)
    previous_close = decimal_to_float(previous.close) if previous is not None else None

    trend_score, participation_score, liquidity_score, stability_score = default_component_scores(inputs)
    threshold = normalized_threshold(0.57, current_entry_policy(inputs))
    blocked_reasons = regime_gate_reasons(inputs)

    if rsi is None or lower_band is None:
        blocked_reasons.append("insufficient_candles")
    if rsi is None or rsi > 45:
        blocked_reasons.append("rsi_not_reset")
    if close is None or lower_band is None or close <= lower_band:
        blocked_reasons.append("still_below_lower_band")
    if previous_close is None or close is None or close <= previous_close:
        blocked_reasons.append("no_reversal_confirmation")

    rsi_score = 0.0 if rsi is None else clamp_score((50.0 - rsi) / 20.0)
    band_score = 0.0
    if close is not None and middle_band not in (None, 0):
        band_score = clamp_score((close - lower_band) / max((middle_band - lower_band), 1e-9)) if lower_band is not None else 0.0
    signal_score = clamp_score((rsi_score * 0.55) + (band_score * 0.45))

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
            "rsi_14": round(rsi, 6) if rsi is not None else None,
            "bollinger_lower": round(lower_band, 6) if lower_band is not None else None,
            "bollinger_middle": round(middle_band, 6) if middle_band is not None else None,
            "bollinger_upper": round(upper_band, 6) if upper_band is not None else None,
        },
    )
