from __future__ import annotations

import httpx

from backend.app.common.adapters.alpaca_base import AlpacaPaperTradingAdapterBase
from backend.app.core.config import Settings


class AlpacaStockPaperAdapter(AlpacaPaperTradingAdapterBase):
    asset_class = "stock"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(
            api_key=settings.alpaca_paper_key,
            api_secret=settings.alpaca_paper_secret,
            base_url=settings.alpaca_trading_api_base_url,
            label="alpaca_stock_paper",
            transport=transport,
        )
