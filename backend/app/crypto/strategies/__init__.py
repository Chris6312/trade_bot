from backend.app.common.strategy_support import StrategyDefinition
from backend.app.crypto.strategies.bbrsi_mean_reversion_long import (
    STRATEGY_NAME as BBRSI_MEAN_REVERSION_LONG_NAME,
    evaluate as evaluate_bbrsi_mean_reversion_long,
)
from backend.app.crypto.strategies.breakout_long import (
    STRATEGY_NAME as BREAKOUT_LONG_NAME,
    evaluate as evaluate_breakout_long,
)
from backend.app.crypto.strategies.trend_continuation_long import (
    STRATEGY_NAME as TREND_CONTINUATION_LONG_NAME,
    evaluate as evaluate_trend_continuation_long,
)
from backend.app.crypto.strategies.vwap_reclaim_long import (
    STRATEGY_NAME as VWAP_RECLAIM_LONG_NAME,
    evaluate as evaluate_vwap_reclaim_long,
)

CRYPTO_STRATEGIES = (
    StrategyDefinition(name=TREND_CONTINUATION_LONG_NAME, evaluator=evaluate_trend_continuation_long),
    StrategyDefinition(name=VWAP_RECLAIM_LONG_NAME, evaluator=evaluate_vwap_reclaim_long),
    StrategyDefinition(name=BREAKOUT_LONG_NAME, evaluator=evaluate_breakout_long),
    StrategyDefinition(name=BBRSI_MEAN_REVERSION_LONG_NAME, evaluator=evaluate_bbrsi_mean_reversion_long),
)

__all__ = ["CRYPTO_STRATEGIES"]
