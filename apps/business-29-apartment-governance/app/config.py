"""Application configuration.

Local development and tests use SQLite. The schema and queries are kept
PostgreSQL-compatible; Neon PostgreSQL is NOT provisioned or connected here.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Env prefix: B29_ → B29_DATABASE_URL etc.
    model_config = SettingsConfigDict(env_prefix="B29_", extra="ignore")

    database_url: str = "sqlite:///./business29.db"


settings = Settings()
