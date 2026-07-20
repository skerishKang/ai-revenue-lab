"""Application factory for the Personal Edition private web workflow.

Creates and configures a FastAPI application with Jinja2 templates,
session authentication, CSRF protection, and all route wiring.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from app import security
from app.ai.mock import MockProvider
from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import FeedbackDirection
from app.pipeline.service import GenerationService

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

    resolved_db = db_path or settings.database_path
    app.state.db_path = resolved_db

    if provider is not None:
        app.state.provider = provider
    elif settings.ai_provider == "mock":
        app.state.provider = MockProvider()
    else:
        app.state.provider = MockProvider()

    app.state.generation_service = GenerationService(
        provider=app.state.provider,
    )

    jinja_env = _build_jinja_env()
    app.state.jinja_env = jinja_env

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    _register_routes(app)

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

    return app


def _get_db(request: Request):
    conn = get_connection(request.app.state.db_path)
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


def _register_routes(app: FastAPI) -> None:
    from app.routes import participant, admin

    app.include_router(participant.router)
    app.include_router(admin.router)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "ai_provider": settings.ai_provider,
            "ai_model": settings.ai_model,
        }
