from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed configuration for the World Feed MVP.

    Variables are read with the ``WORLD_FEED_`` prefix (for example
    ``WORLD_FEED_DATABASE_PATH``). A ``.env`` file in the app directory is
    also honoured.
    """

    model_config = SettingsConfigDict(
        env_prefix="WORLD_FEED_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_base_url: str = "http://127.0.0.1:8000"
    database_path: str = "var/world-feed.db"
    ai_provider: str = "mock"
    ai_model: str = "mock-world-feed-v1"
    ai_max_retries: int = Field(default=3, ge=0, le=10)
    prompt_version: str = "world-feed-v1"
    default_brief_size: int = Field(default=5, ge=1, le=12)


settings = Settings()
