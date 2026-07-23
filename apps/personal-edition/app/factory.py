"""Application factory for the Personal Edition private web workflow.

Creates and configures a FastAPI application with Jinja2 templates,
session authentication, CSRF protection, and all route wiring.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from starlette.middleware.base import BaseHTTPMiddleware

from app import security
from app.ai.mock import MockProvider
from app.config import settings
from app.db import apply_migrations, get_connection
from app.db_runtime import postgres_runtime_connection, sqlite_runtime_connection
from app.domain.enums import FeedbackDirection
from app.pipeline.service import GenerationService


def _build_provider():
    if settings.ai_provider == "mock":
        return MockProvider(model=settings.ai_model)
    if settings.ai_provider == "external":
        from app.ai.external import ExternalProvider
        from app.domain.enums import CostClass
        cost_class = CostClass(settings.ai_cost_class)
        return ExternalProvider(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            timeout_seconds=settings.ai_timeout_seconds,
            cost_class=cost_class,
            response_format_mode=settings.ai_response_format_mode,
        )
    raise ValueError(f"Unknown AI_PROVIDER: {settings.ai_provider}")

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _build_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["feedback_directions"] = [
        (d.value, d.value.replace("_", " ").title())
        for d in FeedbackDirection
    ]

    def _tojson(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    env.filters["tojson"] = _tojson
    return env


def create_app(
    *,
    db_path: str | None = None,
    provider: Any | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters allow test-time overrides for database and provider injection.
    """
    app = FastAPI(title="Personal Edition", docs_url=None, redoc_url=None)

    db_backend = settings.db_backend
    resolved_db = db_path

    if db_backend == "postgresql":
        if resolved_db is not None:
            raise ValueError(
                "db_path override is not supported for PostgreSQL backend"
            )
        database_url = settings.database_url
        if not database_url:
            raise ValueError(
                "PE_DATABASE_URL must be set when DB_BACKEND=postgresql"
            )
        app.state.db_backend = "postgresql"
        app.state.database_url = database_url
        app.state.open_runtime_connection = lambda: postgres_runtime_connection(
            database_url
        ).open()
    else:
        if not resolved_db:
            resolved_db = settings.database_path
        app.state.db_backend = "sqlite"
        app.state.db_path = resolved_db
        app.state.open_runtime_connection = lambda: sqlite_runtime_connection(
            resolved_db
        )

    if provider is not None:
        app.state.provider = provider
    else:
        app.state.provider = _build_provider()

    app.state.generation_service = GenerationService(
        provider=app.state.provider,
    )

    jinja_env = _build_jinja_env()
    app.state.jinja_env = jinja_env

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    app.add_middleware(_PrivacyHeadersMiddleware)

    _register_routes(app)

    @app.on_event("startup")
    def _on_startup() -> None:
        if app.state.db_backend == "postgresql":
            _startup_postgresql(app)
        else:
            _startup_sqlite(resolved_db)

    return app


def _startup_sqlite(db_path: str) -> None:
    """SQLite startup: create directory and apply migrations."""
    db_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(db_dir, exist_ok=True)
    conn = get_connection(db_path)
    try:
        migrations_dir = str(
            Path(__file__).resolve().parent.parent / "migrations"
        )
        apply_migrations(conn, migrations_dir)
    finally:
        conn.close()


def _startup_postgresql(app: FastAPI) -> None:
    """PostgreSQL startup: validate schema and apply migrations.

    Fail-closed: if the database is unreachable or schema validation
    fails, the application refuses to start.
    """
    from app.db_postgres import PG_MIGRATIONS_DIR, get_pg_connection

    database_url = app.state.database_url
    conn = get_pg_connection(database_url)
    try:
        apply_migrations(conn, PG_MIGRATIONS_DIR)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class _PrivacyHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/p") or path.startswith("/admin"):
            for key, value in _privacy_headers().items():
                response.headers[key] = value
        return response


def _get_db(request: Request):
    conn = request.app.state.open_runtime_connection()
    try:
        yield conn
    finally:
        conn.close()


def _get_generation_service(request: Request) -> GenerationService:
    return request.app.state.generation_service


def _render_template(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
) -> HTMLResponse:
    jinja_env = request.app.state.jinja_env
    template = jinja_env.get_template(template_name)
    ctx = context or {}
    ctx["request"] = request
    html = template.render(ctx)
    return HTMLResponse(
        content=html,
        headers={
            **_privacy_headers(),
        },
    )


def _privacy_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, private, "
                         "max-age=0, s-maxage=0",
        "Pragma": "no-cache",
        "Expires": "0",
        "Surrogate-Control": "no-store",
        "X-Robots-Tag": "noindex, nofollow",
    }


def _set_cookie(
    response: Response,
    name: str,
    value: str,
) -> None:
    """Set a cookie using validated application settings."""
    response.set_cookie(
        name,
        value,
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        max_age=settings.session_max_age_seconds,
        path="/",
    )


def _delete_cookie(response: Response, name: str) -> None:
    """Delete a cookie with matching path and security attributes."""
    response.delete_cookie(
        name,
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        path="/",
    )


def _register_routes(app: FastAPI) -> None:
    from app.routes import participant, admin

    app.include_router(participant.router)
    app.include_router(admin.router)

    @app.get("/health")
    def health():
        provider_instance = app.state.provider
        actual_provider = getattr(provider_instance, "provider", provider_instance.__class__.__name__.lower())
        actual_model = getattr(provider_instance, "model", settings.ai_model)
        return {
            "status": "ok",
            "ai_provider": settings.ai_provider,
            "ai_model": settings.ai_model,
            "actual_provider": actual_provider,
            "actual_model": actual_model,
        }
