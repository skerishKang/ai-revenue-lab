"""Application factory for FastAPI."""

from fastapi import FastAPI

from app.config import Settings
from app.db import apply_migrations
from app.routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    from app.config import get_settings

    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Living Learning",
        version="0.1.0",
        description="Recurring 10-minute learning sessions for Korean adult AI/Python beginners",
    )

    apply_migrations(settings.database_url)

    app.include_router(router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app