"""Application factory for Living Fiction.

Creates and configures a FastAPI application with /health endpoint,
SQLite migrations, and the MockProvider.

/health reports the ACTUAL instantiated provider, model, and canonical cost
class rather than configuration labels or enum repr strings. Unsupported
provider configuration fails closed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.ai.base import AIProvider
from app.ai.mock import MockProvider
from app.config import settings
from app.db import apply_migrations, get_connection


def _canonical_cost_class(provider: Any) -> str:
    """Return the provider's stable external cost-class value."""
    value = getattr(provider, "cost_class", None)
    if value is None:
        return "unknown"
    canonical = getattr(value, "value", value)
    return str(canonical)


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
        if not isinstance(provider, AIProvider):
            raise RuntimeError(
                f"unsupported provider configuration: {type(provider).__name__} "
                "does not implement AIProvider protocol. Failing closed."
            )
        app.state.provider = provider
    else:
        if settings.ai_provider != "mock":
            raise RuntimeError(
                f"unsupported provider configuration: '{settings.ai_provider}'. "
                "Only 'mock' is supported in Phase 1. Failing closed."
            )
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
        prov = app.state.provider
        provider_name = getattr(prov, "provider_name", None) or type(prov).__name__
        model_name = getattr(prov, "model", None) or "unknown"
        return {
            "status": "ok",
            "ai_provider": provider_name,
            "ai_model": model_name,
            "cost_class": _canonical_cost_class(prov),
            "provider_type": type(prov).__name__,
        }

    return app
