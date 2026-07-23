"""Application factory for the Korean AI Platform demo MVP.

Supports three injection modes:
- ``create_app(store=...)`` — explicit in-memory Store (test/demo seam);
- ``create_app(db_path=...)`` — explicit temporary SQLite path (tests);
- ``create_app()`` — configured product-local SQLite path (normal run).

Importing this module never opens a database. For the SQLite backends the
migration + seed run inside the FastAPI lifespan (startup), so a plain import
creates no DB file.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from app.config import settings
from app.domain import STATUS_LABELS, VERDICT_LABELS, TaskStatus, Verdict
from app.services import BaseTaskService, InMemoryTaskService, SqliteTaskService
from app.store import Store

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_APP_ROOT = Path(__file__).resolve().parent.parent


def _build_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    def _tojson(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _krw(value: float | int) -> str:
        return f"{value:,.0f}원"

    def _status_label(value: str) -> str:
        try:
            return STATUS_LABELS[TaskStatus(value)]
        except ValueError:
            return value

    def _verdict_label(value: str) -> str:
        try:
            return VERDICT_LABELS[Verdict(value)]
        except ValueError:
            return value

    env.filters["tojson"] = _tojson
    env.filters["krw"] = _krw
    env.globals["status_label"] = _status_label
    env.globals["verdict_label"] = _verdict_label
    env.globals["demo_mode"] = settings.demo_mode
    return env


def _resolve_db_path(db_path: str | None) -> str:
    """Resolve a DB path relative to the Business 14 workspace root."""
    raw = db_path if db_path is not None else settings.database_path
    path = Path(raw)
    if not path.is_absolute():
        path = _APP_ROOT / path
    return str(path)


def _build_service(
    store: Store | None, db_path: str | None
) -> tuple[BaseTaskService, bool]:
    if store is not None:
        return InMemoryTaskService(store), False
    return SqliteTaskService(_resolve_db_path(db_path)), True


def create_app(
    *,
    store: Store | None = None,
    db_path: str | None = None,
) -> FastAPI:
    service, needs_init = _build_service(store, db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if needs_init and isinstance(service, SqliteTaskService):
            service.initialize()
        yield

    app = FastAPI(
        title="Korean AI Platform",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.service = service
    app.state.persistence_kind = service.persistence_kind
    app.state.persistence_label = service.persistence_label
    # Backward-compatible in-memory test seam: existing tests inspect
    # ``app.state.store`` directly. Only present for the injected Store path.
    if store is not None:
        app.state.store = store

    jinja_env = _build_jinja_env()
    jinja_env.globals["persistence_label"] = service.persistence_label
    app.state.jinja_env = jinja_env

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    from app import routes

    app.include_router(routes.router)

    @app.get("/health")
    def health() -> dict[str, Any]:
        if service.persistence_kind == "sqlite":
            backend, persistence = "sqlite", "product_local"
        else:
            backend, persistence = "memory", "in_memory"
        return {
            "status": "ok",
            "app": "korean-ai-platform",
            "demo_mode": settings.demo_mode,
            "database_backend": backend,
            "persistence": persistence,
        }

    return app


def render_template(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    jinja_env = request.app.state.jinja_env
    template = jinja_env.get_template(template_name)
    ctx = dict(context or {})
    ctx["request"] = request
    return HTMLResponse(template.render(ctx), status_code=status_code)
