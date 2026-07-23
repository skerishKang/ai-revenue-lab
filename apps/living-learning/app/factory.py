"""Application factory for FastAPI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.ai import MockProvider
from app.ai.base import AIProvider
from app.config import get_settings
from app.db import apply_migrations
from app.routes import router




def get_connection_factory(database_url: str):
    def get_connection() -> sqlite3.Connection:
        conn = sqlite3.connect(database_url, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    return get_connection


def create_provider(settings) -> AIProvider:
    provider_type = getattr(settings, 'provider_type', 'mock')
    provider_model = getattr(settings, 'provider_model', 'mock-fixture')
    if provider_type == 'mock':
        return MockProvider(model=provider_model)
    raise ValueError(f"Unsupported provider type: {provider_type}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings

    var_dir = Path(settings.database_url).parent
    var_dir.mkdir(parents=True, exist_ok=True)

    apply_migrations(settings.database_url)

    yield


def create_app(settings=None) -> FastAPI:
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Living Learning",
        version="0.1.0",
        description="Recurring 10-minute learning sessions for Korean adult AI/Python beginners",
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.get_connection = get_connection_factory(settings.database_url)

    app.state.provider = create_provider(settings)

    apply_migrations(settings.database_url)

    app.include_router(router)

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        settings = request.app.state.settings
        provider = getattr(request.app.state, 'provider', None)
        model = "unknown"
        provider_type = "unknown"

        if provider is None:
            return JSONResponse({
                "status": "error",
                "message": "Provider not instantiated"
            }, status_code=503)

        try:
            model = getattr(provider, 'model', 'unknown')
        except Exception:
            model = "error"
        try:
            provider_type = getattr(provider, 'provider_type', 'unknown')
        except Exception:
            provider_type = "error"

        return JSONResponse({
            "status": "ok",
            "provider": provider_type,
            "model": model,
        })

    return app