"""HTTP route registration for World Feed."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from app.api_serializers import brief_json, feedback_json, reader_json, source_json
from app.db import get_connection
from app.domain.models import (
    FeedbackInput,
    PilotEvidenceInput,
    ReaderProfileInput,
    SourceCard,
)
from app.errors import (
    AlreadyAppliedFeedbackError,
    BriefGenerationError,
    BriefUnchangedError,
    EvidenceValidationError,
    FirstBriefMissingError,
    ForeignFeedbackError,
    IdempotencyConflictError,
    MismatchedPriorBriefError,
    NoEligibleEventsError,
    UsageAccountingError,
)
from app.privacy import ECONOMIC_HYPOTHESIS, export_safe_evidence
from app.repositories.common import InactiveReaderError, NotFoundError

_CLIENT_ERRORS = (
    BriefGenerationError,
    NoEligibleEventsError,
    BriefUnchangedError,
    AlreadyAppliedFeedbackError,
    ForeignFeedbackError,
    MismatchedPriorBriefError,
    FirstBriefMissingError,
    EvidenceValidationError,
    IdempotencyConflictError,
    UsageAccountingError,
    InactiveReaderError,
    NotFoundError,
)


def register_routes(app: FastAPI, actual_provider: str, actual_model: str):
    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "ai_provider": actual_provider,
            "ai_model": actual_model,
            "economic_hypothesis": ECONOMIC_HYPOTHESIS,
        }

    @app.post("/sources")
    def ingest_source(card: SourceCard, request: Request):
        conn = get_connection(request.app.state.db_path)
        try:
            return source_json(request.app.state.service.ingest_source_card(conn, card))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
            return reader_json(request.app.state.service.create_reader(conn, profile))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            conn.close()

    @app.delete("/readers/{reader_id}")
    def delete_reader(reader_id: str, request: Request):
        conn = get_connection(request.app.state.db_path)
        try:
            return request.app.state.service.delete_reader(conn, reader_id)
        finally:
            conn.close()

    @app.post("/readers/{reader_id}/briefs/first")
    def first_brief(reader_id: str, request: Request):
        return _run_brief(request, reader_id, "first")

    @app.post("/feedback")
    def apply_feedback(feedback: FeedbackInput, request: Request):
        conn = get_connection(request.app.state.db_path)
        try:
            return feedback_json(request.app.state.service.apply_feedback(conn, feedback))
        except _CLIENT_ERRORS as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            conn.close()

    @app.post("/readers/{reader_id}/briefs/second")
    def second_brief(reader_id: str, payload: dict, request: Request):
        key = payload.get("feedback_idempotency_key")
        if not key:
            raise HTTPException(
                status_code=400, detail="feedback_idempotency_key is required"
            )
        return _run_brief(request, reader_id, "second", key)

    @app.post("/evidence")
    def record_evidence(evidence: PilotEvidenceInput, request: Request):
        conn = get_connection(request.app.state.db_path)
        try:
            rec = request.app.state.service.record_pilot_evidence(conn, evidence)
            return export_safe_evidence(rec)
        except _CLIENT_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            conn.close()

    @app.get("/readers/{reader_id}/briefs")
    def list_briefs(reader_id: str, request: Request):
        from app.repositories import brief_repository

        conn = get_connection(request.app.state.db_path)
        try:
            rows = brief_repository.list_briefs_for_reader(conn, reader_id)
            return [brief_json(r) for r in rows]
        finally:
            conn.close()

    def _run_brief(request, reader_id, kind, feedback_key=None):
        conn = get_connection(request.app.state.db_path)
        try:
            svc = request.app.state.service
            if kind == "first":
                brief = svc.generate_first_brief(conn, reader_id)
            else:
                brief = svc.generate_second_brief(
                    conn, reader_id, feedback_idempotency_key=feedback_key
                )
            return brief_json(brief)
        except InactiveReaderError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except _CLIENT_ERRORS as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            conn.close()
