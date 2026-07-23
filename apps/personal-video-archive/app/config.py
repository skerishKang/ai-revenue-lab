"""Configuration for Personal Video Archive."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

_VALID_DISCOVERY_PROVIDERS = frozenset({"fake"})
_VALID_LLM_PROVIDERS = frozenset({"fake"})


class Settings(BaseSettings):
    app_env: str = "development"
    app_base_url: str = "http://127.0.0.1:8000"
    database_path: str = "var/personal-video-archive.db"

    discovery_provider: str = "fake"
    llm_provider: str = "fake"
    llm_model: str = "fake-pva-v1"

    # No real API key is accepted in Phase 1.
    youtube_api_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
