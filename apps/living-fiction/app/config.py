"""Living Fiction configuration.

Environment-backed settings via pydantic-settings. No hardcoded secrets.
The MockProvider is the default and only provider in Phase 1.

Phase 2 adds web session and credential HMAC keys. All secrets are
injected via environment variables — no fallback defaults are provided
for security-sensitive fields.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    env: str = "development"
    app_name: str = "living-fiction"
    database_path: str = "var/living-fiction.db"
    ai_provider: str = "mock"
    ai_model: str = "mock-living-fiction-v1"
    prompt_version: str = "living-fiction-v1"
    max_retries: int = 2

    # Phase 2 web security settings — no fallback defaults.
    admin_secret: str = ""
    credential_hmac_key: str = ""
    session_hmac_key: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "env_prefix": "LF_",
    }

    @property
    def is_production(self) -> bool:
        return self.env == "production"


settings = Settings()
