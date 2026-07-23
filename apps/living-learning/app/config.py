"""Application configuration with environment-backed settings."""

import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "living-learning"
    database_url: str = "var/living-learning.db"
    environment: str = "development"
    provider_model: str = "mock/mock-fixture"
    provider_type: str = "mock"
    # Portal-ready boundary configuration.
    identity_provider: str = "fake"
    # Comma-separated exact origins. Empty => no CORS middleware (fail-closed).
    allowed_origins: str = ""

    model_config = {"env_prefix": "LL_", "env_file": ".env", "extra": "ignore"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.database_url and not self.database_url.startswith(":"):
            db_path = Path(self.database_url)
            if not db_path.is_absolute():
                base_dir = Path(__file__).resolve().parent.parent.parent
                self.database_url = str(base_dir / db_path)

    @property
    def allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None