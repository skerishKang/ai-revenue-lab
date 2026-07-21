"""Application factory for FastAPI."""

from fastapi import FastAPI

from app.config import Settings
from app.db import apply_migrations


def create_app(settings: Settings | None = None) -> FastAPI:
    from app.config import get_settings

    if settings is None:
        settings = get_settings()

    app = FastAPI(title="Living Travel", version="0.1.0")

    apply_migrations(settings.database_url)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
