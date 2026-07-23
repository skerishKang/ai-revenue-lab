"""Operator-facing JSON API routes.

Operator authorization comes solely from an explicit external_identities mapping
(see app.admin bind-operator). These routes mirror the server-rendered operator
contract: traveler management, invitation tokens, edition generation, and
publication review.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.ai.providers import create_mock_provider, create_second_mock_provider
from app.api.auth import Principal, require_operator
from app.api.schemas import CreateTravelerRequest
from app.api.serializers import (
    edition_summary_to_dict,
    edition_to_dict,
    traveler_to_dict,
)
from app.db import get_connection
from app.edition_repository import (
    get_edition_by_id,
    get_editions_by_traveler,
    update_edition_publication,
)
from app.feedback_repository import get_unapplied_feedback_for_edition
from app.pipeline.errors import PipelineError
from app.pipeline.service import GenerationService
from app.security import (
    create_traveler_token,
    deactivate_traveler_tokens,
)
from app.source_repository import get_sources_by_destination
from app.traveler_repository import (
    activate_traveler,
    create_traveler,
    delete_traveler,
    get_all_travelers_admin,
    get_traveler_by_id,
    get_traveler_by_id_admin,
    is_traveler_active,
)

router = APIRouter(prefix="/operator", tags=["operator"])


def _preferences(traveler) -> dict:
    return {
        "destination": traveler.destination,
        "trip_duration_nights": traveler.trip_duration_nights,
        "trip_context": traveler.trip_context,
        "budget_tendency": traveler.budget_tendency,
        "pace_preference": traveler.pace_preference,
        "interests": traveler.interests,
        "exclusions": traveler.exclusions,
        "tone_preference": traveler.tone_preference,
        "length_preference": traveler.length_preference,
        "preferred_language": traveler.preferred_language,
    }


def _source_items(conn, destination: str) -> list[dict]:
    sources = get_sources_by_destination(conn, destination)
    return [
        {
            "source_id": s.id,
            "source_url": s.source_url,
            "publisher": s.publisher,
            "source_type": s.source_type,
            "original_language": s.original_language,
            "destination": s.destination,
            "locality": s.locality,
            "category": s.category,
            "claims": s.claims if isinstance(s.claims, list) else [],
            "confidence": s.confidence,
            "state": s.state,
            "verification_notes": s.verification_notes,
        }
        for s in sources
    ]


def _failure_category(exc: PipelineError) -> str:
    msg = str(exc).lower()
    if "validation failed" in msg:
        return "validation_error"
    if "no unapplied feedback" in msg:
        return "no_matching_feedback"
    if "not materially different" in msg:
        return "validation_error"
    if "prior edition" in msg and "not found" in msg:
        return "validation_error"
    if "inactive" in msg or "deleted" in msg:
        return "validation_error"
    return "unknown"


@router.get("/travelers")
async def list_travelers(_: Principal = Depends(require_operator)) -> dict:
    conn = get_connection()
    try:
        travelers = get_all_travelers_admin(conn)
    finally:
        conn.close()
    return {"travelers": [traveler_to_dict(t) for t in travelers]}


@router.post("/travelers")
async def create_traveler_route(
    body: CreateTravelerRequest,
    _: Principal = Depends(require_operator),
) -> dict:
    conn = get_connection()
    try:
        record = create_traveler(
            conn,
            display_name=body.display_name,
            destination=body.destination,
            trip_duration_nights=body.trip_duration_nights,
        )
    finally:
        conn.close()
    return traveler_to_dict(record)


@router.get("/travelers/{traveler_id}")
async def traveler_detail(
    traveler_id: str,
    _: Principal = Depends(require_operator),
) -> dict:
    conn = get_connection()
    try:
        traveler = get_traveler_by_id_admin(conn, traveler_id)
        if traveler is None:
            raise HTTPException(status_code=404, detail="not_found")
        editions = get_editions_by_traveler(conn, traveler_id)
    finally:
        conn.close()
    return {
        "traveler": traveler_to_dict(traveler),
        "editions": [edition_summary_to_dict(ed) for ed in editions],
    }


@router.post("/travelers/{traveler_id}/invite")
async def invite(
    traveler_id: str,
    _: Principal = Depends(require_operator),
) -> dict:
    conn = get_connection()
    try:
        if not is_traveler_active(conn, traveler_id):
            raise HTTPException(status_code=404, detail="not_found")
        with conn:
            deactivate_traveler_tokens(conn, traveler_id, commit=False)
            _token_id, raw_token = create_traveler_token(conn, traveler_id, commit=False)
    finally:
        conn.close()
    return {"invitation_code": raw_token}


@router.post("/travelers/{traveler_id}/rotate-invite")
async def rotate_invite(
    traveler_id: str,
    _: Principal = Depends(require_operator),
) -> dict:
    conn = get_connection()
    try:
        if not is_traveler_active(conn, traveler_id):
            raise HTTPException(status_code=404, detail="not_found")
        with conn:
            deactivate_traveler_tokens(conn, traveler_id, commit=False)
            conn.execute(
                "DELETE FROM traveler_sessions WHERE traveler_id = ?", (traveler_id,)
            )
            _token_id, raw_token = create_traveler_token(conn, traveler_id, commit=False)
    finally:
        conn.close()
    return {"invitation_code": raw_token}


@router.post("/travelers/{traveler_id}/activate")
async def activate(
    traveler_id: str,
    _: Principal = Depends(require_operator),
) -> dict:
    conn = get_connection()
    try:
        if not activate_traveler(conn, traveler_id):
            raise HTTPException(status_code=404, detail="not_found")
    finally:
        conn.close()
    return {"status": "active"}


@router.post("/travelers/{traveler_id}/deactivate")
async def deactivate(
    traveler_id: str,
    _: Principal = Depends(require_operator),
) -> dict:
    conn = get_connection()
    try:
        if not is_traveler_active(conn, traveler_id):
            raise HTTPException(status_code=404, detail="not_found")
        with conn:
            delete_traveler(conn, traveler_id, commit=False)
            deactivate_traveler_tokens(conn, traveler_id, commit=False)
            conn.execute(
                "DELETE FROM traveler_sessions WHERE traveler_id = ?", (traveler_id,)
            )
    finally:
        conn.close()
    return {"status": "deleted"}


@router.post("/travelers/{traveler_id}/generate-first")
async def generate_first(
    traveler_id: str,
    _: Principal = Depends(require_operator),
) -> dict:
    conn = get_connection()
    try:
        traveler = get_traveler_by_id(conn, traveler_id)
        if traveler is None:
            raise HTTPException(status_code=404, detail="not_found")
        preferences = _preferences(traveler)
        if preferences.get("preferred_language", "ko") != "ko":
            raise HTTPException(status_code=409, detail="unsupported_fixture")
        provider = create_mock_provider(conn, preferences)
        sources = _source_items(conn, traveler.destination)
        service = GenerationService(conn, provider)
        try:
            service.generate_first_edition(
                traveler_id=traveler_id,
                traveler_preferences=preferences,
                source_items=sources,
            )
        except PipelineError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "generation_failed", "category": _failure_category(exc)},
            )
        editions = get_editions_by_traveler(conn, traveler_id)
    finally:
        conn.close()
    return {"edition": edition_summary_to_dict(editions[-1])}


@router.post("/travelers/{traveler_id}/generate-second")
async def generate_second(
    traveler_id: str,
    _: Principal = Depends(require_operator),
) -> dict:
    conn = get_connection()
    try:
        traveler = get_traveler_by_id(conn, traveler_id)
        if traveler is None:
            raise HTTPException(status_code=404, detail="not_found")
        editions = get_editions_by_traveler(conn, traveler_id)
        prior = None
        for ed in reversed(editions):
            if (
                ed.publication_state == "published"
                and ed.structured_content
                and ed.structured_content != {}
            ):
                prior = ed
                break
        if prior is None:
            raise HTTPException(status_code=409, detail="no_prior_edition")
        preferences = _preferences(traveler)
        if preferences.get("preferred_language", "ko") != "ko":
            raise HTTPException(status_code=409, detail="unsupported_fixture")
        feedback_records = get_unapplied_feedback_for_edition(
            conn, traveler_id, prior.id
        )
        provider = create_second_mock_provider(
            conn, preferences, feedback_records, prior.structured_content
        )
        sources = _source_items(conn, traveler.destination)
        service = GenerationService(conn, provider)
        try:
            service.generate_second_edition(
                traveler_id=traveler_id,
                prior_edition_id=prior.id,
                traveler_preferences=preferences,
                source_items=sources,
            )
        except PipelineError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "generation_failed", "category": _failure_category(exc)},
            )
        editions = get_editions_by_traveler(conn, traveler_id)
    finally:
        conn.close()
    return {"edition": edition_summary_to_dict(editions[-1])}


@router.get("/editions/{edition_id}")
async def edition_preview(
    edition_id: str,
    _: Principal = Depends(require_operator),
) -> dict:
    conn = get_connection()
    try:
        edition = get_edition_by_id(conn, edition_id)
    finally:
        conn.close()
    if edition is None:
        raise HTTPException(status_code=404, detail="not_found")
    return edition_to_dict(edition)


@router.post("/editions/{edition_id}/publish")
async def publish(
    edition_id: str,
    _: Principal = Depends(require_operator),
) -> dict:
    conn = get_connection()
    try:
        edition = get_edition_by_id(conn, edition_id)
        if edition is None:
            raise HTTPException(status_code=404, detail="not_found")
        if edition.generation_status != "pending_review":
            raise HTTPException(status_code=409, detail="not_reviewable")
        update_edition_publication(conn, edition_id, "published")
    finally:
        conn.close()
    return {"publication_state": "published"}


@router.post("/editions/{edition_id}/reject")
async def reject(
    edition_id: str,
    _: Principal = Depends(require_operator),
) -> dict:
    conn = get_connection()
    try:
        edition = get_edition_by_id(conn, edition_id)
        if edition is None:
            raise HTTPException(status_code=404, detail="not_found")
        if edition.generation_status != "pending_review":
            raise HTTPException(status_code=409, detail="not_reviewable")
        update_edition_publication(conn, edition_id, "rejected")
    finally:
        conn.close()
    return {"publication_state": "rejected"}
