"""Application configuration with environment-backed settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "living-travel"
    database_url: str = "file::memory:"
    environment: str = "development"
    operator_secret: str = "changeme"

    model_config = {"env_prefix": "LT_", "env_file": ".env", "extra": "ignore"}

    def model_post_init(self, __context) -> None:
        """Validate operator_secret is not a placeholder."""
        _PLACEHOLDERS = {"changeme", "change-me", "secret", "password", ""}
        if self.environment != "testing":
            if not self.operator_secret or self.operator_secret.lower() in _PLACEHOLDERS:
                raise ValueError(
                    "LT_OPERATOR_SECRET must be set to a secure value. "                     "The default placeholder is not allowed in non-testing environments."
                )
            if len(self.operator_secret) < 16:
                raise ValueError(
                    "LT_OPERATOR_SECRET must be at least 16 characters."
                )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
