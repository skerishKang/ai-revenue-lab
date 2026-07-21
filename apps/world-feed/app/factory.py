"""Application factory for the World Feed Phase 1 MVP."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.ai.mock import MockProvider
from app.api_routes import register_routes
from app.config import SUPPORTED_AI_PROVIDERS, settings
from app.db import apply_migrations, get_connection
from app.service import WorldFeedService

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


class UnsupportedProviderError(RuntimeError):
    pass


@asynccontextmanager
async def _lifespan(app: FastAPI):
    db_dir = os.path.dirname(os.path.abspath(app.state.db_path))
    os.makedirs(db_dir, exist_ok=True)
    conn = get_connection(app.state.db_path)
    try:
        apply_migrations(conn, str(_MIGRATIONS_DIR))
    finally:
        conn.close()
    yield


def create_app(
    *,
    db_path: str | None = None,
    provider=None,
    service: WorldFeedService | None = None,
    app_settings=None,
) -> FastAPI:
    cfg = app_settings or settings
    app = FastAPI(title="World Feed", docs_url=None, redoc_url=None)
    app.state.db_path = db_path or cfg.database_path

    if provider is not None:
        app.state.provider = provider
    elif cfg.ai_provider in SUPPORTED_AI_PROVIDERS:
        app.state.provider = MockProvider(model=cfg.ai_model)
    else:
        raise UnsupportedProviderError(
            f"unsupported AI_PROVIDER: {cfg.ai_provider!r}; "
            f"supported: {sorted(SUPPORTED_AI_PROVIDERS)}"
        )

    app.state.service = service or WorldFeedService(
        provider=app.state.provider, settings=cfg
    )
    actual_provider = getattr(app.state.provider, "provider", cfg.ai_provider)
    actual_model = getattr(app.state.provider, "model", cfg.ai_model)
    app.router.lifespan_context = _lifespan
    register_routes(app, actual_provider, actual_model)
    return app
