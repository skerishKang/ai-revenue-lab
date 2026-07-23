"""Application factory for Personal Video Archive."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db import apply_migrations, get_connection
from app.providers import LanguageModelProvider, VideoDiscoveryProvider
from app.providers.fake_language_model import FakeLanguageModelProvider
from app.providers.fake_video_discovery import FakeVideoDiscoveryProvider
from app.repositories import (
    ProposalRepository,
    QuotaLedgerRepository,
    QueryRuleRepository,
    SyncRunRepository,
    TopicRepository,
    TopicVideoRepository,
    VideoRepository,
    ViewingRecordRepository,
)
from app.services import (
    DiscoveryService,
    ProposalService,
    RecordService,
    TopicService,
)


def _build_discovery_provider() -> VideoDiscoveryProvider:
    if settings.discovery_provider == "fake":
        return FakeVideoDiscoveryProvider()
    raise ValueError(f"Unknown DISCOVERY_PROVIDER: {settings.discovery_provider}")


def _build_llm_provider() -> LanguageModelProvider:
    if settings.llm_provider == "fake":
        return FakeLanguageModelProvider(model=settings.llm_model)
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")


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

    env.filters["tojson"] = _tojson

    def _fromjson(value: str) -> Any:
        return json.loads(value) if isinstance(value, str) else value

    env.filters["fromjson"] = _fromjson

    def _format_thousands(value: Any) -> str:
        try:
            return f"{int(value):,}"
        except (ValueError, TypeError):
            return str(value)

    env.filters["format_thousands"] = _format_thousands

    def _state_label(value: Any) -> Any:
        # Render a viewing state as its user-facing value. Accepts either a
        # ViewingState enum (returns ``.value``) or a plain string (returned
        # unchanged) so the shared template is safe for both input shapes.
        return getattr(value, "value", value)

    env.filters["state_label"] = _state_label

    return env


def _get_db(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _get_discovery_service(request: Request) -> DiscoveryService:
    return request.app.state.discovery_service


def _get_record_service(request: Request) -> RecordService:
    return request.app.state.record_service


def _get_proposal_service(request: Request) -> ProposalService:
    return request.app.state.proposal_service


def _render_template(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    jinja_env = request.app.state.jinja_env
    template = jinja_env.get_template(template_name)
    ctx = context or {}
    ctx["request"] = request
    html = template.render(ctx)
    return HTMLResponse(
        content=html,
        status_code=status_code,
        headers=_privacy_headers(),
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


class _PrivacyHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in _privacy_headers().items():
            response.headers[key] = value
        return response


def create_app(
    *,
    db_path: str | None = None,
    discovery_provider: VideoDiscoveryProvider | None = None,
    llm_provider: LanguageModelProvider | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Personal Video Archive",
        docs_url=None,
        redoc_url=None,
    )

    resolved_db = db_path or settings.database_path
    app.state.db_path = resolved_db
    app.state.discovery_provider = discovery_provider or _build_discovery_provider()
    app.state.llm_provider = llm_provider or _build_llm_provider()

    # Build repositories and services
    def _make_repos(conn):
        return {
            "topic": TopicRepository(conn),
            "rule": QueryRuleRepository(conn),
            "video": VideoRepository(conn),
            "topic_video": TopicVideoRepository(conn),
            "record": ViewingRecordRepository(conn),
            "sync": SyncRunRepository(conn),
            "quota": QuotaLedgerRepository(conn),
            "proposal": ProposalRepository(conn),
        }

    app.state._make_repos = _make_repos  # type: ignore[attr-defined]

    jinja_env = _build_jinja_env()
    app.state.jinja_env = jinja_env

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    app.add_middleware(_PrivacyHeadersMiddleware)

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


def _build_services(conn):
    """Build service layer from a database connection."""
    repos = {
        "topic": TopicRepository(conn),
        "rule": QueryRuleRepository(conn),
        "video": VideoRepository(conn),
        "topic_video": TopicVideoRepository(conn),
        "record": ViewingRecordRepository(conn),
        "sync": SyncRunRepository(conn),
        "quota": QuotaLedgerRepository(conn),
        "proposal": ProposalRepository(conn),
    }
    return repos


def _register_routes(app: FastAPI) -> None:
    from app.routes import proposals, records, topics, videos

    app.include_router(topics.router)
    app.include_router(videos.router)
    app.include_router(records.router)
    app.include_router(proposals.router)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "discovery_provider": app.state.discovery_provider.__class__.__name__,
            "llm_provider": app.state.llm_provider.__class__.__name__,
            "llm_model": settings.llm_model,
        }

    @app.get("/")
    def index(request: Request):
        conn = get_connection(request.app.state.db_path)
        try:
            repos = _build_services(conn)
            topic_service = TopicService(
                repos["topic"], repos["rule"],
                request.app.state.llm_provider,
            )
            topics = topic_service.list_topics()
            return _render_template(request, "index.html", {"topics": topics})
        finally:
            conn.close()
