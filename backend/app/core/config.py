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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
