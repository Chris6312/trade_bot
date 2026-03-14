from __future__ import annotations

import httpx

from backend.app.common.adapters.alpaca_base import AlpacaPaperTradingAdapterBase
from backend.app.core.config import Settings


class AlpacaCryptoPaperAdapter(AlpacaPaperTradingAdapterBase):
    asset_class = "crypto"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(
            api_key=settings.alpaca_paper_key_crypto,
            api_secret=settings.alpaca_paper_secret_crypto,
            base_url=settings.alpaca_trading_api_base_url,
            label="alpaca_crypto_paper",
            transport=transport,
        )
