"""Application factory for the Korean AI Platform demo MVP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from app.config import settings
from app.domain import STATUS_LABELS, VERDICT_LABELS, TaskStatus, Verdict
from app.store import Store

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


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


def create_app(*, store: Store | None = None) -> FastAPI:
    app = FastAPI(title="Korean AI Platform", docs_url=None, redoc_url=None)
    app.state.store = store if store is not None else Store(seed=True)
    app.state.jinja_env = _build_jinja_env()

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    from app import routes

    app.include_router(routes.router)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "app": "korean-ai-platform",
            "demo_mode": settings.demo_mode,
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
