from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Telegram
    BOT_TOKEN: str
    OWNER_TELEGRAM_ID: int

    # Postgres
    POSTGRES_DB: str = "garage_ledger"
    POSTGRES_USER: str = "garage"
    POSTGRES_PASSWORD: str = "garage_password"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    # App
    APP_ENV: str = "prod"
    TZ: str = "Europe/Moscow"
    LOG_LEVEL: str = "INFO"

    DEFAULT_INCOME_CATEGORIES: str = "Услуги,Продажи"
    DEFAULT_EXPENSE_CATEGORIES: str = "Расходники,Аренда,Зарплата"

    @property
    def database_url_async(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def database_url_sync(self) -> str:
        # Alembic uses sync URL
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
