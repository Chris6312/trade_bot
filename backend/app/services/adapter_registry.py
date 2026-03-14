from __future__ import annotations

from backend.app.core.config import Settings, get_settings
from backend.app.crypto.brokers.alpaca_crypto_paper import AlpacaCryptoPaperAdapter
from backend.app.crypto.brokers.kraken_trading import KrakenTradingAdapter
from backend.app.crypto.data.kraken_market_data import KrakenMarketDataAdapter
from backend.app.stocks.brokers.alpaca_stock_paper import AlpacaStockPaperAdapter
from backend.app.stocks.brokers.public_trading import PublicTradingAdapter
from backend.app.stocks.data.alpaca_stock_ohlcv import AlpacaStockOhlcvAdapter
from backend.app.stocks.data.alpaca_stock_screener import AlpacaStockScreenerAdapter


class AdapterRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def kraken_trading(self) -> KrakenTradingAdapter:
        return KrakenTradingAdapter(self.settings)

    def kraken_market_data(self) -> KrakenMarketDataAdapter:
        return KrakenMarketDataAdapter(self.settings)

    def public_trading(self) -> PublicTradingAdapter:
        return PublicTradingAdapter(self.settings)

    def alpaca_stock_paper(self) -> AlpacaStockPaperAdapter:
        return AlpacaStockPaperAdapter(self.settings)

    def alpaca_crypto_paper(self) -> AlpacaCryptoPaperAdapter:
        return AlpacaCryptoPaperAdapter(self.settings)

    def alpaca_stock_ohlcv(self) -> AlpacaStockOhlcvAdapter:
        return AlpacaStockOhlcvAdapter(self.settings)


    def alpaca_stock_screener(self) -> AlpacaStockScreenerAdapter:
        return AlpacaStockScreenerAdapter(self.settings)
