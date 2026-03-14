from backend.app.common.strategy_support import StrategyDefinition
from backend.app.stocks.strategies.opening_range_breakout_long import (
    STRATEGY_NAME as OPENING_RANGE_BREAKOUT_LONG_NAME,
    evaluate as evaluate_opening_range_breakout_long,
)
from backend.app.stocks.strategies.trend_pullback_long import (
    STRATEGY_NAME as TREND_PULLBACK_LONG_NAME,
    evaluate as evaluate_trend_pullback_long,
)
from backend.app.stocks.strategies.vwap_reclaim_long import (
    STRATEGY_NAME as VWAP_RECLAIM_LONG_NAME,
    evaluate as evaluate_vwap_reclaim_long,
)

STOCK_STRATEGIES = (
    StrategyDefinition(name=TREND_PULLBACK_LONG_NAME, evaluator=evaluate_trend_pullback_long),
    StrategyDefinition(name=VWAP_RECLAIM_LONG_NAME, evaluator=evaluate_vwap_reclaim_long),
    StrategyDefinition(name=OPENING_RANGE_BREAKOUT_LONG_NAME, evaluator=evaluate_opening_range_breakout_long),
)

__all__ = ["STOCK_STRATEGIES"]
