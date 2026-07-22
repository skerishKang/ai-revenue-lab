"""Living Fiction configuration.

Environment-backed settings via pydantic-settings. No hardcoded secrets.
The MockProvider is the default and only provider in Phase 1.

Phase 2 adds web session and credential HMAC keys. All secrets are
injected via environment variables — no fallback defaults are provided
for security-sensitive fields.
"""

from pydantic_settings import BaseSettings

_PLACEHOLDER_SECRETS = {
    "changeme",
    "change-me",
    "change_me",
    "secret",
    "password",
    "example",
    "placeholder",
}


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

    def validate_web_secrets(self) -> None:
        """Fail closed when web secrets are missing or (in production) weak.

        Every environment requires all three secrets to be non-empty. In
        production they must additionally be at least 32 characters, mutually
        distinct, and not obvious placeholders — there is no source-code
        fallback for any secret.
        """
        secrets = {
            "LF_ADMIN_SECRET": self.admin_secret,
            "LF_CREDENTIAL_HMAC_KEY": self.credential_hmac_key,
            "LF_SESSION_HMAC_KEY": self.session_hmac_key,
        }
        missing = [name for name, value in secrets.items() if not value]
        if missing:
            raise ValueError(
                "Missing required web secret(s): " + ", ".join(missing)
            )
        if not self.is_production:
            return
        for name, value in secrets.items():
            if len(value) < 32:
                raise ValueError(
                    f"{name} must be at least 32 characters in production"
                )
            if value.strip().lower() in _PLACEHOLDER_SECRETS:
                raise ValueError(
                    f"{name} looks like a placeholder; set a real secret"
                )
        values = list(secrets.values())
        if len(set(values)) != len(values):
            raise ValueError("Web secrets must be distinct from one another")


settings = Settings()
