from __future__ import annotations

from backend.app.common.strategy_support import (
    StrategyEvaluationInput,
    bool_score,
    build_outcome,
    composite_score,
    current_entry_policy,
    decimal_to_float,
    default_component_scores,
    exponential_moving_average_series,
    latest_candle,
    moving_average,
    normalized_threshold,
    regime_gate_reasons,
)

STRATEGY_NAME = "htf_reclaim_long"
_SUPPORTED_TIMEFRAME = "5m"


def evaluate(inputs: StrategyEvaluationInput):
    feature = inputs.feature_snapshot
    trigger_candles = inputs.candles_by_timeframe.get(_SUPPORTED_TIMEFRAME, inputs.candles)
    trigger_candle = latest_candle(trigger_candles)
    if feature is None or trigger_candle is None:
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

    config = dict(inputs.strategy_config or {})
    bias_config = dict(config.get("bias") or {})
    setup_config = dict(config.get("setup") or {})
    trigger_config = dict(config.get("trigger") or {})

    blocked_reasons = regime_gate_reasons(inputs)
    if inputs.timeframe != _SUPPORTED_TIMEFRAME:
        blocked_reasons.append("unsupported_strategy_timeframe")

    bias_timeframe = str(bias_config.get("timeframe") or "1h")
    setup_timeframe = str(setup_config.get("timeframe") or "15m")
    trigger_timeframe = str(trigger_config.get("timeframe") or _SUPPORTED_TIMEFRAME)

    bias_state = _evaluate_ma_context(inputs.candles_by_timeframe.get(bias_timeframe, ()), bias_config, prefix="1h_bias")
    setup_state = _evaluate_ma_context(inputs.candles_by_timeframe.get(setup_timeframe, ()), setup_config, prefix="15m_setup")
    blocked_reasons.extend(bias_state["blocked_reasons"])
    blocked_reasons.extend(setup_state["blocked_reasons"])

    close = decimal_to_float(feature.close)
    vwap = decimal_to_float(trigger_candle.vwap)
    ema_length = int(trigger_config.get("ema_length") or 9)
    pullback_lookback = int(trigger_config.get("pullback_lookback_bars") or 3)
    ema_series = exponential_moving_average_series(trigger_candles, period=ema_length)
    ema9 = ema_series[-1] if ema_series else None

    price_above_vwap = close is not None and vwap is not None and close > vwap
    price_above_ema9 = close is not None and ema9 is not None and close > ema9
    bullish_reclaim = close is not None and decimal_to_float(trigger_candle.open) is not None and close > decimal_to_float(trigger_candle.open)
    recent_pullback = _recent_pullback_into_support(
        candles=trigger_candles,
        ema_series=ema_series,
        lookback=pullback_lookback,
    )

    if vwap is None:
        blocked_reasons.append("5m_trigger_vwap_missing")
    if ema9 is None:
        blocked_reasons.append("5m_trigger_ema9_unavailable")
    if not price_above_vwap:
        blocked_reasons.append("5m_trigger_price_below_vwap")
    if not price_above_ema9:
        blocked_reasons.append("5m_trigger_price_below_ema9")
    if not recent_pullback:
        blocked_reasons.append("5m_trigger_pullback_missing")
    if not bullish_reclaim:
        blocked_reasons.append("5m_trigger_bullish_reclaim_missing")

    trigger_distance_pct = None
    support_reference = None
    if vwap is not None and ema9 is not None:
        support_reference = max(vwap, ema9)
    elif vwap is not None:
        support_reference = vwap
    elif ema9 is not None:
        support_reference = ema9
    if close is not None and support_reference not in (None, 0):
        trigger_distance_pct = (close - support_reference) / support_reference

    contract_trend_score = composite_score(
        bias_state["score"],
        setup_state["score"],
        weights=(0.5, 0.5),
    )
    _default_trend, participation_score, liquidity_score, stability_score = default_component_scores(inputs)
    signal_score = composite_score(
        bool_score(price_above_vwap),
        bool_score(price_above_ema9),
        bool_score(recent_pullback),
        bool_score(bullish_reclaim),
    )
    threshold = normalized_threshold(0.65, current_entry_policy(inputs))

    return build_outcome(
        strategy_name=STRATEGY_NAME,
        threshold_score=threshold,
        trend_score=contract_trend_score,
        participation_score=participation_score,
        liquidity_score=liquidity_score,
        stability_score=stability_score,
        signal_score=signal_score,
        blocked_reasons=blocked_reasons,
        payload={
            "contract_version": "paper_test_v1",
            "contract_timeframe": inputs.timeframe,
            "bias_timeframe": bias_timeframe,
            "setup_timeframe": setup_timeframe,
            "trigger_timeframe": trigger_timeframe,
            "bias_pass": bias_state["passed"],
            "setup_pass": setup_state["passed"],
            "trigger_pass": bool(price_above_vwap and price_above_ema9 and recent_pullback and bullish_reclaim),
            "bias_fast_ma": _serialize_ma_state(bias_state.get("fast_ma")),
            "bias_slow_ma": _serialize_ma_state(bias_state.get("slow_ma")),
            "setup_fast_ma": _serialize_ma_state(setup_state.get("fast_ma")),
            "setup_slow_ma": _serialize_ma_state(setup_state.get("slow_ma")),
            "trigger_ema9": round(ema9, 6) if ema9 is not None else None,
            "trigger_vwap": round(vwap, 6) if vwap is not None else None,
            "trigger_reclaim_distance_pct": round(trigger_distance_pct, 6) if trigger_distance_pct is not None else None,
            "recent_pullback_detected": recent_pullback,
            "bullish_reclaim_candle": bullish_reclaim,
            "selected_pairs": {
                "1h": {
                    "fast_type": bias_config.get("fast_ma_type"),
                    "fast_length": bias_config.get("fast_ma_length"),
                    "slow_type": bias_config.get("slow_ma_type"),
                    "slow_length": bias_config.get("slow_ma_length"),
                },
                "15m": {
                    "fast_type": setup_config.get("fast_ma_type"),
                    "fast_length": setup_config.get("fast_ma_length"),
                    "slow_type": setup_config.get("slow_ma_type"),
                    "slow_length": setup_config.get("slow_ma_length"),
                },
            },
        },
    )


def _evaluate_ma_context(candles, config, *, prefix: str) -> dict[str, object]:
    fast_family = str(config.get("fast_ma_type") or "sma")
    slow_family = str(config.get("slow_ma_type") or "sma")
    fast_length = int(config.get("fast_ma_length") or 20)
    slow_length = int(config.get("slow_ma_length") or 50)
    latest = latest_candle(candles)
    fast_ma = moving_average(candles, family=fast_family, period=fast_length)
    slow_ma = moving_average(candles, family=slow_family, period=slow_length)
    close = decimal_to_float(latest.close) if latest is not None else None

    blocked_reasons: list[str] = []
    if latest is None:
        blocked_reasons.append(f"{prefix}_candles_unavailable")
    if fast_ma is None:
        blocked_reasons.append(f"{prefix}_fast_ma_unavailable")
    if slow_ma is None:
        blocked_reasons.append(f"{prefix}_slow_ma_unavailable")
    if fast_ma is not None and slow_ma is not None and fast_ma <= slow_ma:
        blocked_reasons.append(f"{prefix}_fast_not_above_slow")
    if close is None or fast_ma is None or close <= fast_ma:
        blocked_reasons.append(f"{prefix}_price_below_fast_ma")
    if close is None or slow_ma is None or close <= slow_ma:
        blocked_reasons.append(f"{prefix}_price_below_slow_ma")

    score = composite_score(
        bool_score(fast_ma is not None and slow_ma is not None and fast_ma > slow_ma),
        bool_score(close is not None and fast_ma is not None and close > fast_ma),
        bool_score(close is not None and slow_ma is not None and close > slow_ma),
    )
    return {
        "passed": not blocked_reasons,
        "score": score,
        "blocked_reasons": blocked_reasons,
        "close": close,
        "fast_ma": {
            "family": fast_family,
            "length": fast_length,
            "value": fast_ma,
        },
        "slow_ma": {
            "family": slow_family,
            "length": slow_length,
            "value": slow_ma,
        },
    }


def _recent_pullback_into_support(*, candles, ema_series: list[float], lookback: int) -> bool:
    if len(candles) < 2 or not ema_series:
        return False
    history = list(candles[-(lookback + 1) : -1])
    if not history:
        return False
    for offset, candle in enumerate(history, start=len(candles) - len(history)):
        ema_value = ema_series[offset] if offset < len(ema_series) else None
        vwap_value = decimal_to_float(candle.vwap)
        low = decimal_to_float(candle.low)
        close = decimal_to_float(candle.close)
        touched_ema = low is not None and ema_value is not None and low <= ema_value
        touched_vwap = low is not None and vwap_value is not None and low <= vwap_value
        closed_into_ema = close is not None and ema_value is not None and close <= ema_value
        closed_into_vwap = close is not None and vwap_value is not None and close <= vwap_value
        if touched_ema or touched_vwap or closed_into_ema or closed_into_vwap:
            return True
    return False


def _serialize_ma_state(state):
    if not isinstance(state, dict):
        return None
    value = state.get("value")
    return {
        "family": state.get("family"),
        "length": state.get("length"),
        "value": round(value, 6) if isinstance(value, (int, float)) else None,
    }
