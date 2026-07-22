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
from app.config import settings
from app.db import apply_migrations, get_connection
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
    Unsupported provider names fail closed.

    When *provider* is ``None`` the configured ``settings.ai_provider`` is
    used so the factory always reflects the deployment configuration rather
    than silently defaulting to MockProvider.

    An injected object must satisfy the :class:`AIProvider` protocol
    (``provider_name``, ``model``, ``cost_class`` attributes); arbitrary
    objects are rejected at startup.
    """
    if provider is None:
        provider = settings.ai_provider
    if isinstance(provider, str):
        if provider == "mock":
            return MockProvider()
        raise RuntimeError(f"unsupported provider: {provider}")
    for attr in ("provider_name", "model", "cost_class"):
        if not hasattr(provider, attr):
            raise RuntimeError(
                f"injected provider missing required attribute: {attr}"
            )
    return provider


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

    # Resolve DB path once so startup migrations and per-request connections
    # always target the same database file.
    resolved_db = db_path or settings.database_path
    app.state.db_path = resolved_db

    # Run migrations at startup
    migrations_dir = str(Path(__file__).resolve().parent.parent / "migrations")
    conn = get_connection(resolved_db)
    try:
        apply_migrations(conn, migrations_dir)
    finally:
        conn.close()

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
