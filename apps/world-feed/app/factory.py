"""Application factory for the World Feed Phase 1 MVP.

The app is fully independent: FastAPI + SQLite, network-free MockProvider,
environment-backed settings, versioned migrations, and a small JSON API that
exposes the synthetic source -> microbrief loop. Every generated brief stays
``pending_review``; nothing is published automatically.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from app.ai.mock import MockProvider
from app.config import SUPPORTED_AI_PROVIDERS, settings
from app.db import apply_migrations, get_connection
from app.domain.models import (
    FeedbackInput,
    PilotEvidenceInput,
    ReaderProfileInput,
    SourceCard,
)
from app.service import (
    BriefGenerationError,
    NoEligibleEventsError,
    WorldFeedService,
)

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


class UnsupportedProviderError(RuntimeError):
    pass


@asynccontextmanager
async def _lifespan(app: FastAPI):
    db_dir = os.path.dirname(os.path.abspath(app.state.db_path))
    os.makedirs(db_dir, exist_ok=True)
    conn = get_connection(app.state.db_path)
    try:
        apply_migrations(conn, str(_MIGRATIONS_DIR))
    finally:
        conn.close()
    yield


def create_app(
    *,
    db_path: str | None = None,
    provider=None,
    service: WorldFeedService | None = None,
    app_settings=None,
) -> FastAPI:
    cfg = app_settings or settings
    app = FastAPI(title="World Feed", docs_url=None, redoc_url=None)
    resolved_db = db_path or cfg.database_path
    app.state.db_path = resolved_db

    if provider is not None:
        app.state.provider = provider
    elif cfg.ai_provider in SUPPORTED_AI_PROVIDERS:
        app.state.provider = MockProvider(model=cfg.ai_model)
    else:
        raise UnsupportedProviderError(
            f"unsupported AI_PROVIDER: {cfg.ai_provider!r}; "
            f"supported: {sorted(SUPPORTED_AI_PROVIDERS)}"
        )

    app.state.service = service or WorldFeedService(
        provider=app.state.provider, settings=cfg
    )

    actual_provider = getattr(app.state.provider, "provider", cfg.ai_provider)
    actual_model = getattr(app.state.provider, "model", cfg.ai_model)

    app.router.lifespan_context = _lifespan

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "ai_provider": actual_provider,
            "ai_model": actual_model,
        }

    @app.post("/sources")
    def ingest_source(card: SourceCard, request: Request):
        conn = get_connection(request.app.state.db_path)
        try:
            rec = request.app.state.service.ingest_source_card(conn, card)
            return _source_json(rec)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            conn.close()

    @app.post("/sources/resolve")
    def resolve_events(request: Request):
        conn = get_connection(request.app.state.db_path)
        try:
            n = request.app.state.service.resolve_canonical_events(conn)
            return {"canonical_events": n}
        finally:
            conn.close()

    @app.post("/readers")
    def create_reader(profile: ReaderProfileInput, request: Request):
        conn = get_connection(request.app.state.db_path)
        try:
            rec = request.app.state.service.create_reader(conn, profile)
            return _reader_json(rec)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            conn.close()

    @app.post("/readers/{reader_id}/briefs/first")
    def first_brief(reader_id: str, request: Request):
        conn = get_connection(request.app.state.db_path)
        try:
            brief = request.app.state.service.generate_first_brief(conn, reader_id)
            return _brief_json(brief)
        except (BriefGenerationError, NoEligibleEventsError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        finally:
            conn.close()

    @app.post("/feedback")
    def apply_feedback(feedback: FeedbackInput, request: Request):
        conn = get_connection(request.app.state.db_path)
        try:
            rec = request.app.state.service.apply_feedback(conn, feedback)
            return _feedback_json(rec)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            conn.close()

    @app.post("/readers/{reader_id}/briefs/second")
    def second_brief(reader_id: str, payload: dict, request: Request):
        key = payload.get("feedback_idempotency_key")
        if not key:
            raise HTTPException(
                status_code=400,
                detail="feedback_idempotency_key is required",
            )
        conn = get_connection(request.app.state.db_path)
        try:
            brief = request.app.state.service.generate_second_brief(
                conn,
                reader_id,
                feedback_idempotency_key=key,
            )
            return _brief_json(brief)
        except (BriefGenerationError, NoEligibleEventsError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        finally:
            conn.close()

    @app.post("/evidence")
    def record_evidence(evidence: PilotEvidenceInput, request: Request):
        conn = get_connection(request.app.state.db_path)
        try:
            rec = request.app.state.service.record_pilot_evidence(conn, evidence)
            return _evidence_json(rec)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            conn.close()

    @app.get("/readers/{reader_id}/briefs")
    def list_briefs(reader_id: str, request: Request):
        from app.repositories import brief_repository

        conn = get_connection(request.app.state.db_path)
        try:
            rows = brief_repository.list_briefs_for_reader(conn, reader_id)
            return [_brief_json(r) for r in rows]
        finally:
            conn.close()

    return app


# ---- JSON serializers ----------------------------------------------------


def _source_json(rec):
    return {
        "source_id": rec.source_id,
        "canonical_key": rec.canonical_key,
        "source_state": rec.source_state,
        "country": rec.country,
    }


def _reader_json(rec):
    return {
        "reader_id": rec.reader_id,
        "display_name": rec.display_name,
        "language": rec.language,
        "active": rec.active,
    }


def _feedback_json(rec):
    return {
        "id": rec.id,
        "reader_id": rec.reader_id,
        "action": rec.action,
        "idempotency_key": rec.idempotency_key,
        "applied_to_brief_id": rec.applied_to_brief_id,
    }


def _evidence_json(rec):
    return {
        "id": rec.id,
        "evidence_type": rec.evidence_type,
        "anonymous_token": rec.anonymous_token,
    }


def _brief_json(rec):
    return {
        "id": rec.id,
        "brief_number": rec.brief_number,
        "reader_id": rec.reader_id,
        "sequence": rec.sequence,
        "status": rec.status,
        "title": rec.title,
        "selected_event_ids": rec.selected_event_ids,
        "feedback_id": rec.feedback_id,
        "validation_status": rec.validation_status,
    }
