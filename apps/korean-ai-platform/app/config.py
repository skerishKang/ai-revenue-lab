from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Korean AI Platform"
    demo_mode: bool = True

    model_config = {"env_prefix": "KAP_"}


settings = Settings()
