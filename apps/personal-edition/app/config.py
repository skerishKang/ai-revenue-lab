from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    app_base_url: str = "http://127.0.0.1:8000"
    ai_provider: str = "mock"
    ai_model: str = "mock-personal-edition-v1"
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_timeout_seconds: int = Field(default=120, gt=0)
    prompt_version: str = "personal-edition-v1"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
