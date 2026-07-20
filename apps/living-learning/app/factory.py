"""Application factory for FastAPI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import apply_migrations
from app.routes import router


_pipeline_instances = {}


def get_connection() -> sqlite3.Connection:
    settings = get_settings()
    conn = sqlite3.connect(settings.database_url)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    var_dir = Path(settings.database_url).parent
    var_dir.mkdir(parents=True, exist_ok=True)

    apply_migrations(settings.database_url)

    yield

    for conn in _pipeline_instances.values():
        if hasattr(conn, 'close'):
            conn.close()
    _pipeline_instances.clear()


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

    apply_migrations(settings.database_url)

    app.include_router(router)

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        settings = request.app.state.settings
        return JSONResponse({
            "status": "ok",
            "provider": settings.provider_type,
            "model": settings.provider_model,
        })

    return app