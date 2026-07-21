"""Living Fiction configuration.

Environment-backed settings via pydantic-settings. No hardcoded secrets.
The MockProvider is the default and only provider in Phase 1.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "living-fiction"
    database_path: str = "var/living-fiction.db"
    ai_provider: str = "mock"
    ai_model: str = "mock-living-fiction-v1"
    prompt_version: str = "living-fiction-v1"
    max_retries: int = 2

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
