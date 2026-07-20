from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

_DEFAULT_SECRETS = frozenset({
    "dev-secret-key-change-in-production",
    "dev-admin-secret-change-in-production",
})


class Settings(BaseSettings):
    app_env: str = "development"
    app_base_url: str = "http://127.0.0.1:8000"
    database_path: str = "var/personal-edition.db"
    ai_provider: str = "mock"
    ai_model: str = "mock-personal-edition-v1"
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_timeout_seconds: int = Field(default=120, gt=0)
    prompt_version: str = "personal-edition-v1"
    secret_key: str = "dev-secret-key-change-in-production"
    admin_secret: str = "dev-admin-secret-change-in-production"
    session_max_age_seconds: int = Field(default=3600 * 8, gt=0)
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def _validate_production_secrets(self):
        if self.app_env == "production":
            if self.secret_key in _DEFAULT_SECRETS or len(self.secret_key) < 32:
                raise ValueError(
                    "SECRET_KEY must be set to a strong, unique value "
                    "in production (APP_ENV=production)"
                )
            if self.admin_secret in _DEFAULT_SECRETS or len(self.admin_secret) < 16:
                raise ValueError(
                    "ADMIN_SECRET must be set to a strong, unique value "
                    "in production (APP_ENV=production)"
                )
            if not self.cookie_secure:
                raise ValueError(
                    "COOKIE_SECURE must be true in production "
                    "(APP_ENV=production)"
                )
        return self


settings = Settings()
