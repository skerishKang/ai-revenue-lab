"""Product-local configuration for the Korean AI Platform (Business 14).

Environment variables use the ``KAP_`` prefix so they never collide with other
Business workspaces. This product never reads the ambient ``DATABASE_URL`` and
never implicitly connects to another Business database.
"""

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings

# Only SQLite is implemented for Business 14 today. PostgreSQL is a future
# runtime boundary; selecting it must fail closed with a fixed configuration
# error rather than silently falling back to SQLite.
_SQLITE_BACKEND = "sqlite"
_POSTGRESQL_BACKEND = "postgresql"


class Settings(BaseSettings):
    app_env: str = "development"
    app_base_url: str = "http://127.0.0.1:8014"
    demo_mode: bool = True

    db_backend: str = Field(
        default=_SQLITE_BACKEND,
        validation_alias=AliasChoices("KAP_DB_BACKEND"),
    )
    database_path: str = Field(
        default="var/korean-ai-platform.db",
        validation_alias=AliasChoices("KAP_DATABASE_PATH"),
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def _validate_db_backend(self):
        backend = (self.db_backend or "").strip().lower()
        if backend == _POSTGRESQL_BACKEND:
            raise ValueError(
                "KAP_DB_BACKEND=postgresql is not implemented for the Korean "
                "AI Platform. Use KAP_DB_BACKEND=sqlite. There is no silent "
                "fallback to SQLite."
            )
        if backend != _SQLITE_BACKEND:
            raise ValueError(
                "KAP_DB_BACKEND must be 'sqlite' "
                f"(got '{self.db_backend}')."
            )
        self.db_backend = backend
        return self


settings = Settings()
