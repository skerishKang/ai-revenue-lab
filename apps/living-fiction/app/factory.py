"""Application factory for Living Fiction.

Creates and configures a FastAPI application with /health endpoint,
SQLite migrations, and the MockProvider.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.ai.mock import MockProvider
from app.config import settings
from app.db import apply_migrations, get_connection


def create_app(
    *,
    db_path: str | None = None,
    provider: Any | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Living Fiction",
        docs_url=None,
        redoc_url=None,
    )

    resolved_db = db_path or settings.database_path
    app.state.db_path = resolved_db

    if provider is not None:
        app.state.provider = provider
    else:
        app.state.provider = MockProvider()

    @app.on_event("startup")
    def _on_startup() -> None:
        db_dir = os.path.dirname(os.path.abspath(resolved_db))
        os.makedirs(db_dir, exist_ok=True)
        conn = get_connection(resolved_db)
        try:
            migrations_dir = str(
                Path(__file__).resolve().parent.parent / "migrations"
            )
            apply_migrations(conn, migrations_dir)
        finally:
            conn.close()

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "ai_provider": settings.ai_provider,
            "ai_model": settings.ai_model,
        }

    return app
