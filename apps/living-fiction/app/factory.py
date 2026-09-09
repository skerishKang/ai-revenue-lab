"""Application factory for Living Fiction.

Creates and configures a FastAPI application with /health endpoint,
SQLite migrations, and the configured AI provider.

/health reports the ACTUAL instantiated provider, model, and canonical cost
class rather than configuration labels or enum repr strings. Unsupported
provider configuration fails closed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.ai.base import AIProvider
from app.ai.mock import MockProvider
from app.ai.openai_compat import OpenAICompatibleProvider
from app.config import settings
from app.database.engine import build_engine
from app.database.migrate_postgres import verify_schema_current
from app.db import apply_migrations
from app.public_reader import register_public_reader_entry
from app.web import register_web_routes


def _canonical_cost_class(provider: Any) -> str:
    """Return the provider's stable external cost-class value."""
    value = getattr(provider, "cost_class", None)
    if value is None:
        return "unknown"
    canonical = getattr(value, "value", value)
    return str(canonical)


def _resolve_provider(provider: str | AIProvider | None) -> AIProvider:
    """Resolve the AI provider from a name string or instance."""
    if provider is None:
        provider = settings.ai_provider
    if isinstance(provider, str):
        handled = provider.strip().lower()
        if handled == "mock":
            return MockProvider()
        if handled in ("opencode_go", "openai_compat"):
            settings.validate_ai_provider()
            base_url = "https://opencode.ai/zen/go/v1" if handled == "opencode_go" else settings.ai_base_url
            return OpenAICompatibleProvider(
                api_key=settings.ai_api_key,
                model=settings.ai_model,
                provider_name=handled,
                base_url=base_url,
            )
        raise RuntimeError(f"unsupported provider: {provider}")
    for attr in ("provider_name", "model", "cost_class"):
        if not hasattr(provider, attr):
            raise RuntimeError(f"injected provider missing required attribute: {attr}")
    if not callable(getattr(provider, "generate_structured", None)):
        raise RuntimeError("injected provider missing callable generate_structured")
    return provider


def _verify_postgres_schema(engine: Any, migrations_dir: str) -> None:
    conn = engine.acquire()
    try:
        verify_schema_current(conn, migrations_dir)
    finally:
        engine.release(conn)


def create_app(
    *,
    db_path: str | None = None,
    provider: str | AIProvider | None = None,
    enable_web: bool = True,
) -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        description="Public living-fiction reader with reader-responsive branching",
    )

    settings.validate_database()

    resolved_db = db_path or settings.database_path
    app.state.db_path = resolved_db

    engine = build_engine(settings, resolved_db)
    app.state.db_engine = engine

    app_root = Path(__file__).resolve().parent.parent
    if engine.backend == "sqlite":
        conn = engine.acquire()
        try:
            apply_migrations(conn, str(app_root / "migrations"))
        finally:
            engine.release(conn)
    else:
        _verify_postgres_schema(engine, str(app_root / "migrations_postgres"))

    resolved_provider = _resolve_provider(provider)
    app.state.provider = resolved_provider

    if enable_web:
        register_public_reader_entry(app)
        register_web_routes(app)

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "ai_provider": resolved_provider.provider_name,
            "ai_model": resolved_provider.model,
            "cost_class": _canonical_cost_class(resolved_provider),
            "provider_type": type(resolved_provider).__name__,
        }

    return app
