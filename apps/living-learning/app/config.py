"""Application configuration with environment-backed settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "living-learning"
    database_url: str = "file::memory:"
    environment: str = "development"

    model_config = {"env_prefix": "LL_", "env_file": ".env", "extra": "ignore"}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None