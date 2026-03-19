from backend.app.common.strategy_support import StrategyDefinition
from backend.app.stocks.strategies.htf_reclaim_long import (
    STRATEGY_NAME as HTF_RECLAIM_LONG_NAME,
    evaluate as evaluate_htf_reclaim_long,
)

STOCK_STRATEGIES = (
    StrategyDefinition(name=HTF_RECLAIM_LONG_NAME, evaluator=evaluate_htf_reclaim_long),
)

__all__ = ["STOCK_STRATEGIES"]
