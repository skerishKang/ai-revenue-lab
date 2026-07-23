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
from app.i18n import lang_switch_href, locale_from_path, locale_prefix, make_t
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

    path = request.url.path
    locale = locale_from_path(path)
    query = str(request.url.query) if request.url.query else ""
    ctx["locale"] = locale
    ctx["lp"] = locale_prefix(locale)
    ctx["t"] = make_t(locale)
    ctx["lang_switch_href"] = lang_switch_href(path, query)
    ctx.setdefault("is_preview", False)
    ctx.setdefault("portal_home_href", settings.portal_home_href)
    ctx.setdefault("portal_account_href", settings.portal_account_href)

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


def _locale_prefix(request: Request) -> str:
    """Return the locale URL prefix for the current request path."""
    if request.url.path.startswith("/en"):
        return "/en"
    return ""


def _register_routes(app: FastAPI) -> None:
    from app.routes import proposals, records, topics, videos

    for prefix in ("", "/en"):
        app.include_router(topics.router, prefix=prefix)
        app.include_router(videos.router, prefix=prefix)
        app.include_router(records.router, prefix=prefix)
        app.include_router(proposals.router, prefix=prefix)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "discovery_provider": app.state.discovery_provider.__class__.__name__,
            "llm_provider": app.state.llm_provider.__class__.__name__,
            "llm_model": settings.llm_model,
        }

    @app.get("/")
    @app.get("/en/")
    def index(request: Request):
        conn = get_connection(request.app.state.db_path)
        try:
            repos = _build_services(conn)
            topic_service = TopicService(
                repos["topic"], repos["rule"],
                request.app.state.llm_provider,
            )
            topics = topic_service.list_topics()

            continue_watching = conn.execute(
                "SELECT r.id as rec_id, r.viewing_state, r.updated_at, "
                "tv.id as tv_id, tv.topic_id, tv.video_id, tv.match_score, "
                "tv.match_reasons, tv.first_matched_at, tv.last_matched_at, "
                "tv.is_excluded, tv.created_at as tv_created, tv.updated_at as tv_updated, "
                "v.id as vid, v.provider, v.provider_video_id, v.canonical_url, "
                "v.title, v.description, v.channel_id, v.channel_title, "
                "v.published_at, v.duration_seconds, v.view_count, v.like_count, "
                "v.thumbnail_url, v.tags, v.created_at as v_created, v.updated_at as v_updated "
                "FROM viewing_records r "
                "JOIN topic_videos tv ON r.topic_video_id = tv.id "
                "JOIN videos v ON tv.video_id = v.id "
                "WHERE r.viewing_state = 'in_progress' "
                "ORDER BY r.updated_at DESC LIMIT 4"
            ).fetchall()

            new_finds = conn.execute(
                "SELECT tv.id as tv_id, tv.topic_id, tv.video_id, tv.match_score, "
                "tv.match_reasons, tv.first_matched_at, tv.last_matched_at, "
                "tv.is_excluded, tv.created_at as tv_created, tv.updated_at as tv_updated, "
                "v.id as vid, v.provider, v.provider_video_id, v.canonical_url, "
                "v.title, v.description, v.channel_id, v.channel_title, "
                "v.published_at, v.duration_seconds, v.view_count, v.like_count, "
                "v.thumbnail_url, v.tags, v.created_at as v_created, v.updated_at as v_updated "
                "FROM topic_videos tv "
                "JOIN videos v ON tv.video_id = v.id "
                "ORDER BY v.created_at DESC LIMIT 4"
            ).fetchall()

            recent_notes = conn.execute(
                "SELECT r.id as rec_id, r.viewing_state, r.free_form_note, "
                "r.tags as rec_tags, r.updated_at, "
                "tv.id as tv_id, tv.topic_id, tv.video_id, "
                "v.id as vid, v.provider, v.provider_video_id, v.canonical_url, "
                "v.title, v.channel_title, v.published_at, v.thumbnail_url "
                "FROM viewing_records r "
                "JOIN topic_videos tv ON r.topic_video_id = tv.id "
                "JOIN videos v ON tv.video_id = v.id "
                "WHERE r.free_form_note != '' AND r.free_form_note IS NOT NULL "
                "ORDER BY r.updated_at DESC LIMIT 3"
            ).fetchall()

            resurfaced = conn.execute(
                "SELECT r.id as rec_id, r.viewing_state, r.free_form_note, "
                "r.tags as rec_tags, r.updated_at, "
                "tv.id as tv_id, tv.topic_id, tv.video_id, "
                "v.id as vid, v.provider, v.provider_video_id, v.canonical_url, "
                "v.title, v.channel_title, v.published_at, v.thumbnail_url "
                "FROM viewing_records r "
                "JOIN topic_videos tv ON r.topic_video_id = tv.id "
                "JOIN videos v ON tv.video_id = v.id "
                "WHERE r.viewing_state = 'revisit' "
                "ORDER BY r.updated_at DESC LIMIT 1"
            ).fetchall()

            return _render_template(
                request, "index.html",
                {
                    "topics": topics,
                    "continue_watching": _rows_to_feed_tuples(continue_watching),
                    "new_finds": _rows_to_feed_tuples(new_finds),
                    "recent_notes": _rows_to_record_tuples(recent_notes),
                    "resurfaced": _rows_to_record_tuples(resurfaced),
                },
            )
        finally:
            conn.close()


def _rows_to_feed_tuples(rows):
    """Convert raw SQL rows to (TopicVideo, DiscoveredVideo, PrivateViewingRecord|None) tuples.

    Preserves viewing records when present (e.g., continue-watching items).
    Returns None for the record when no viewing record exists (e.g., new-finds).
    """
    from app.domain.enums import ViewingState
    from app.domain.models import DiscoveredVideo, PrivateViewingRecord, TopicVideo

    result = []
    for row in rows:
        tv = TopicVideo(
            id=row["tv_id"],
            topic_id=row["topic_id"],
            video_id=row["video_id"],
            first_matched_at=row["first_matched_at"],
            last_matched_at=row["last_matched_at"],
            match_score=row["match_score"],
            match_reasons=json.loads(row["match_reasons"]) if row["match_reasons"] else [],
            is_excluded=bool(row["is_excluded"]),
            created_at=row["tv_created"],
            updated_at=row["tv_updated"],
        )
        video = DiscoveredVideo(
            id=row["vid"],
            provider=row["provider"],
            provider_video_id=row["provider_video_id"],
            canonical_url=row["canonical_url"],
            title=row["title"],
            description=row["description"],
            channel_id=row["channel_id"],
            channel_title=row["channel_title"],
            published_at=row["published_at"],
            duration_seconds=row["duration_seconds"],
            view_count=row["view_count"],
            like_count=row["like_count"],
            thumbnail_url=row["thumbnail_url"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            created_at=row["v_created"],
            updated_at=row["v_updated"],
        )
        # Preserve viewing record if present (continue-watching has rec_id)
        record = None
        if "rec_id" in row.keys() and row["rec_id"]:
            record = PrivateViewingRecord(
                id=row["rec_id"],
                topic_video_id=row["tv_id"],
                viewing_state=ViewingState(row["viewing_state"]),
                free_form_note="",
                tags=[],
                created_at=row["updated_at"],
                updated_at=row["updated_at"],
            )
        result.append((tv, video, record))
    return result


def _rows_to_record_tuples(rows):
    """Convert raw SQL rows to (PrivateViewingRecord, TopicVideo, DiscoveredVideo) tuples."""
    from app.domain.enums import ViewingState
    from app.domain.models import DiscoveredVideo, PrivateViewingRecord, TopicVideo

    result = []
    for row in rows:
        record = PrivateViewingRecord(
            id=row["rec_id"],
            topic_video_id=row["tv_id"],
            viewing_state=ViewingState(row["viewing_state"]),
            free_form_note=row["free_form_note"] if "free_form_note" in row.keys() else "",
            tags=json.loads(row["rec_tags"]) if "rec_tags" in row.keys() and row["rec_tags"] else [],
            created_at=row["updated_at"],
            updated_at=row["updated_at"],
        )
        tv = TopicVideo(
            id=row["tv_id"],
            topic_id=row["topic_id"],
            video_id=row["video_id"],
            first_matched_at=row["updated_at"],
            last_matched_at=row["updated_at"],
            match_score=None,
            match_reasons=[],
            is_excluded=False,
            created_at=row["updated_at"],
            updated_at=row["updated_at"],
        )
        video = DiscoveredVideo(
            id=row["vid"],
            provider=row["provider"] if "provider" in row.keys() else "youtube",
            provider_video_id=row["provider_video_id"] if "provider_video_id" in row.keys() else row["vid"],
            canonical_url=row["canonical_url"] if "canonical_url" in row.keys() else f"https://www.youtube.com/watch?v={row['vid']}",
            title=row["title"],
            description="",
            channel_id="",
            channel_title=row["channel_title"],
            published_at=row["published_at"],
            duration_seconds=None,
            view_count=None,
            like_count=None,
            thumbnail_url=row["thumbnail_url"] if "thumbnail_url" in row.keys() else "",
            tags=[],
            created_at=row["updated_at"],
            updated_at=row["updated_at"],
        )
        result.append((record, tv, video))
    return result
