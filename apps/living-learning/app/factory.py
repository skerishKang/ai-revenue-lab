"""Application factory for FastAPI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import sqlite3

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.ai import MockProvider
from app.ai.base import AIProvider
from app.api import portal_router
from app.config import get_settings
from app.db import apply_migrations
from app.routes import router

PORTAL_CONTRACT_VERSION = "v1"

# Private path prefixes whose responses must not be cached or indexed.
_PRIVATE_PREFIXES = ("/api/v1/",)


def get_connection_factory(database_url: str):
    def get_connection() -> sqlite3.Connection:
        conn = sqlite3.connect(database_url, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    return get_connection


def create_provider(settings) -> AIProvider:
    provider_type = getattr(settings, "provider_type", "mock")
    provider_model = getattr(settings, "provider_model", "mock-fixture")
    if provider_type == "mock":
        return MockProvider(model=provider_model)
    raise ValueError(f"Unsupported provider type: {provider_type}")


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
    settings = app.state.settings
    if settings.database_url != ":memory:":
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
        app_settings = request.app.state.settings
        return JSONResponse(
            {
                "status": "ok",
                "database_backend": "sqlite",
                "identity_provider": getattr(app_settings, "identity_provider", "fake"),
                "ai_provider": getattr(provider, "provider_type", "unknown"),
                "ai_model": getattr(provider, "model", "unknown"),
                "portal_contract_version": PORTAL_CONTRACT_VERSION,
                # Backward-compatible aliases for existing isolation tests.
                "provider": getattr(provider, "provider_type", "unknown"),
                "model": getattr(provider, "model", "unknown"),
            }
        )

    return app
