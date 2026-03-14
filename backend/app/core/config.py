from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    app_name: str = "Small Account Multi-Asset Trading Bot"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8101
    frontend_port: int = 4174
    postgres_db: str = "tradingbot"
    postgres_user: str = "tradingbot"
    postgres_password: str = "tradingbot"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_host_port: int = 55432
    database_url: str = "postgresql+psycopg://tradingbot:tradingbot@postgres:5432/tradingbot"
    database_url_alembic: str | None = None
    cors_origins: str = "http://localhost:4174,http://127.0.0.1:4174"
    vite_api_base_url: str = "http://localhost:8101"

    alpaca_paper_key: str | None = None
    alpaca_paper_secret: str | None = None
    alpaca_paper_key_crypto: str | None = None
    alpaca_paper_secret_crypto: str | None = None
    kraken_api_key: str | None = None
    kraken_api_secret: str | None = None
    public_api_secret: str | None = None
    public_account_id: str | None = None
    public_access_token_validity_minutes: int = 60

    kraken_api_base_url: str = "https://api.kraken.com/0"
    alpaca_trading_api_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_market_data_base_url: str = "https://data.alpaca.markets"
    public_api_base_url: str = "https://api.public.com"
    broker_request_timeout_seconds: float = 10.0
    kraken_quote_currency: str = "ZUSD"
    kraken_trade_balance_asset: str = "ZUSD"

    ai_provider: str = "openai"
    ai_model: str = "gpt-5-mini"
    ai_enabled: bool = True
    ai_run_once_daily: bool = True
    ai_premarket_time_et: str = "08:40"
    ai_api_url: str = "https://api.openai.com/v1"
    ai_api_key: str | None = None
    stock_universe_source: str = "ai"
    stock_universe_max_size: int = 50

    stock_default_backfill_bars: int = 500
    crypto_default_backfill_bars: int = 720
    stock_feature_timeframes: str = "1h"
    crypto_feature_timeframes: str = "1h"
    feature_lookback_bars: int = 20

    max_account_deployment_pct: float = 0.90
    max_risk_per_trade_pct: float = 0.02
    default_risk_per_trade_pct: float = 0.0125
    long_only_until_equity: float = 2500.0

    default_mode: str = "mixed"
    stock_execution_mode: str = "paper"
    crypto_execution_mode: str = "paper"
    execution_order_type: str = "market"
    execution_time_in_force: str = "day"
    execution_kill_switch_enabled: bool = False

    stock_fee_pct: float = 0.0005
    crypto_fee_pct: float = 0.0013
    stock_slippage_pct: float = 0.0005
    crypto_slippage_pct: float = 0.0015

    stock_soft_stop_pct: float = -0.035
    stock_hard_stop_pct: float = -0.055
    crypto_soft_stop_pct: float = -0.040
    crypto_hard_stop_pct: float = -0.065
    total_account_hard_stop_pct: float = -0.075

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def masked_database_url(self) -> str:
        if "://" not in self.database_url or "@" not in self.database_url:
            return self.database_url

        prefix, remainder = self.database_url.split("://", 1)
        credentials, host_part = remainder.split("@", 1)

        if ":" not in credentials:
            return self.database_url

        username, _password = credentials.split(":", 1)
        return f"{prefix}://{username}:***@{host_part}"

    @property
    def alembic_database_url(self) -> str:
        if self.database_url_alembic:
            return self.database_url_alembic

        if self.database_url.startswith("sqlite"):
            return self.database_url

        if "@postgres:" in self.database_url:
            return self.database_url.replace(
                "@postgres:5432",
                f"@localhost:{self.postgres_host_port}",
            )

        if "@postgres/" in self.database_url:
            return self.database_url.replace(
                "@postgres/",
                f"@localhost:{self.postgres_host_port}/",
            )

        return self.database_url

    @property
    def stock_feature_timeframe_list(self) -> list[str]:
        return [item.strip() for item in self.stock_feature_timeframes.split(",") if item.strip()]

    @property
    def crypto_feature_timeframe_list(self) -> list[str]:
        return [item.strip() for item in self.crypto_feature_timeframes.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
