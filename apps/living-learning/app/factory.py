"""Application factory for FastAPI.

Supports two database backends selected explicitly by configuration:
  * sqlite (local/test): file connection per request, migrations applied at
    startup.
  * postgresql (production): a bounded scale-to-zero pool; the runtime verifies
    the schema is current (read-only) and NEVER applies migrations (those run
    via the operator command ``python -m app.production.migrate``).

Startup configuration is fail-closed: an unsupported backend, a missing runtime
URL, or a non-current schema aborts startup rather than serving a broken app.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import sqlite3

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.ai.base import AIProvider
from app.api import portal_router
from app.config import Settings, get_settings
from app.db import apply_migrations
from app.routes import router

PORTAL_CONTRACT_VERSION = "v1"

# Private path prefixes whose responses must not be cached or indexed.
_PRIVATE_PREFIXES = ("/api/v1/",)


def get_sqlite_connection_factory(database_url: str):
    def get_connection() -> sqlite3.Connection:
        conn = sqlite3.connect(database_url, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    return get_connection


def get_postgres_connection_factory(settings: Settings):
    """Build a scale-to-zero PostgreSQL pool and return a per-request factory."""
    from app.production.database import PostgresPool

    pool = PostgresPool(settings.database_url, min_size=0, max_size=5)
    pool.open()

    def get_connection():
        return pool.acquire()

    get_connection._pool = pool  # type: ignore[attr-defined]
    return get_connection


def create_provider(settings) -> AIProvider:
    from app.production.config import resolve_provider

    return resolve_provider(settings)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Mark private API responses as no-store/noindex.

    Bearer-token-only JSON API: never cacheable, never indexed. No secret is
    emitted; these are transport-level privacy headers.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(_PRIVATE_PREFIXES):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    if settings.database_backend == "sqlite":
        if settings.database_url != ":memory:":
            var_dir = Path(settings.database_url).parent
            var_dir.mkdir(parents=True, exist_ok=True)
        apply_migrations(settings.database_url)
    # postgresql: schema is verified at create_app time (read-only); the runtime
    # never applies migrations.
    yield
    # Close the postgres pool on shutdown if present.
    factory = getattr(app.state, "get_connection", None)
    pool = getattr(factory, "_pool", None)
    if pool is not None:
        try:
            pool.close()
        except Exception:
            pass


def _wire_identity_verifier(settings: Settings) -> None:
    """Wire the configured identity verifier.

    Only the ``firebase`` backend wires a concrete verifier here. For ``fake``
    mode the verifier is left untouched: tests inject a ``FakeIdentityVerifier``
    explicitly, and if none is set the registry's fail-closed default
    (``RejectingIdentityVerifier``) rejects every token.
    """
    if (settings.identity_provider or "fake").strip().lower() != "firebase":
        return
    from app.identity import set_identity_verifier
    from app.production.config import resolve_verifier

    set_identity_verifier(resolve_verifier(settings))


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

    # Fail-closed backend selection.
    if settings.database_backend == "postgresql":
        app.state.get_connection = get_postgres_connection_factory(settings)
        # Verify the schema is current (read-only); never migrate at runtime.
        from app.production.database import connect_postgres
        from app.production.migrate import verify_schema_current

        check_conn = connect_postgres(settings.effective_migration_url, autocommit=True)
        try:
            verify_schema_current(check_conn)
        finally:
            check_conn.close()
    else:
        app.state.get_connection = get_sqlite_connection_factory(settings.database_url)
        apply_migrations(settings.database_url)

    app.state.provider = create_provider(settings)

    # Wire the identity verifier (fail-closed). Tests may override via
    # set_identity_verifier after create_app.
    _wire_identity_verifier(settings)

    # Restrictive CORS: exact-origin allowlist only, never wildcard with
    # credentials. Bearer tokens (no cookies) => allow_credentials=False.
    if settings.allowed_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origin_list,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
        )

    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(router)
    app.include_router(portal_router)

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        provider = getattr(request.app.state, "provider", None)
        if provider is None:
            return JSONResponse({"status": "error"}, status_code=503)
        app_settings: Settings = request.app.state.settings
        return JSONResponse(
            {
                "status": "ok",
                "database_backend": app_settings.database_backend,
                "identity_provider": getattr(app_settings, "identity_provider", "fake"),
                "ai_provider": getattr(provider, "provider_type", "unknown"),
                "ai_model": getattr(provider, "model", "unknown"),
                "portal_contract_version": PORTAL_CONTRACT_VERSION,
                "deployment_environment": app_settings.deployment_environment,
                # Backward-compatible aliases for existing isolation tests.
                "provider": getattr(provider, "provider_type", "unknown"),
                "model": getattr(provider, "model", "unknown"),
            }
        )

    return app
