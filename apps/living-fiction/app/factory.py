"""Application factory for Living Fiction.

Creates and configures a FastAPI application with /health endpoint,
SQLite migrations, and the MockProvider.

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
from app.web import register_web_routes


def _canonical_cost_class(provider: Any) -> str:
    """Return the provider's stable external cost-class value."""
    value = getattr(provider, "cost_class", None)
    if value is None:
        return "unknown"
    canonical = getattr(value, "value", value)
    return str(canonical)


def _resolve_provider(provider: str | AIProvider | None) -> AIProvider:
    """Resolve the AI provider from a name string or instance.

    Phase 1 supports only the free, local, deterministic MockProvider.
    Phase 3A adds OpenAI-compatible providers (``opencode_go``,
    ``openai_compat``). Unsupported provider names fail closed.

    When *provider* is ``None`` the configured ``settings.ai_provider`` is
    used so the factory always reflects the deployment configuration rather
    than silently defaulting to MockProvider.

    An injected object must satisfy the :class:`AIProvider` protocol
    (``provider_name``, ``model``, ``cost_class`` attributes and a callable
    ``generate_structured``); arbitrary or partially-implemented objects are
    rejected at startup rather than failing later at generation time.
    """
    if provider is None:
        provider = settings.ai_provider
    if isinstance(provider, str):
        handled = provider.strip().lower()
        if handled == "mock":
            return MockProvider()
        if handled in ("opencode_go", "openai_compat"):
            settings.validate_ai_provider()
            if handled == "opencode_go":
                base_url = "https://opencode.ai/zen/go/v1"
            else:
                base_url = settings.ai_base_url
            return OpenAICompatibleProvider(
                api_key=settings.ai_api_key,
                model=settings.ai_model,
                provider_name=handled,
                base_url=base_url,
            )
        raise RuntimeError(f"unsupported provider: {provider}")
    for attr in ("provider_name", "model", "cost_class"):
        if not hasattr(provider, attr):
            raise RuntimeError(
                f"injected provider missing required attribute: {attr}"
            )
    if not callable(getattr(provider, "generate_structured", None)):
        raise RuntimeError(
            "injected provider missing callable generate_structured"
        )
    return provider


def _verify_postgres_schema(engine: Any, migrations_dir: str) -> None:
    """Fail closed unless the PostgreSQL schema is already current.

    The runtime role never applies migrations; it only verifies that every
    on-disk migration is fully applied. Extracted as a module-level seam so
    tests that exercise production startup without a live database can
    substitute a no-op while still exercising backend selection and origin /
    secret validation.
    """
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
    """Application factory.

    Args:
        db_path: Override database path (defaults to settings.database_path).
        provider: AI provider instance or provider name string.
            If None, creates MockProvider (free, local, deterministic).
            If a string, must be "mock" (only supported provider in Phase 1).
            If an AIProvider instance, used directly.
        enable_web: Register the Phase 2 web routes. Defaults to True so a
            production app fails closed rather than silently degrading to a
            ``/health``-only server. DB-only unit tests that need an app without
            the web surface pass ``enable_web=False`` explicitly.

    Raises:
        RuntimeError: If an unsupported provider string is given, or if web
            routes are enabled and the web security secrets are missing/weak or
            route registration fails. These are never swallowed — a missing
            secret or a broken web surface must fail startup, not hide behind a
            live ``/health``.
    """
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        description="Private literary archive with reader-responsive branching",
    )

    # Validate the explicit backend selection first, failing closed on an
    # unknown backend, production+sqlite, or a postgres backend with no runtime
    # URL. Error messages never include the configured URL.
    settings.validate_database()

    # Resolve DB path once so startup migrations and per-request connections
    # always target the same database file.
    resolved_db = db_path or settings.database_path
    app.state.db_path = resolved_db

    # Build the backend-neutral connection engine and store it for the
    # per-request get_db dependency.
    engine = build_engine(settings, resolved_db)
    app.state.db_engine = engine

    app_root = Path(__file__).resolve().parent.parent
    if engine.backend == "sqlite":
        # Local/default backend: apply SQLite migrations at startup (the
        # existing behaviour).
        conn = engine.acquire()
        try:
            apply_migrations(conn, str(app_root / "migrations"))
        finally:
            engine.release(conn)
    else:
        # Production postgres backend: the schema must ALREADY be current. The
        # runtime role never applies migrations; a missing or divergent schema
        # fails startup closed rather than silently serving a broken database.
        _verify_postgres_schema(engine, str(app_root / "migrations_postgres"))

    # Resolve provider
    resolved_provider = _resolve_provider(provider)
    app.state.provider = resolved_provider

    if enable_web:
        # Fail closed: missing/weak secrets, import errors, and route
        # registration runtime errors all propagate. There is no silent
        # degraded mode where /health lives but the product routes vanish.
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
