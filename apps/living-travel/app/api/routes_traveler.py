"""Traveler-facing JSON API routes.

A traveler may only access their own data: the traveler id is derived from the
verified Firebase identity mapping, never from a client-supplied field. Foreign
or non-published resources return a generic 404.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import Principal, get_verified_claims, require_traveler
from app.api.schemas import ClaimRequest, FeedbackRequest, PreferencesUpdate
from app.api.serializers import (
    edition_summary_to_dict,
    edition_to_dict,
    traveler_preferences_to_dict,
)
from app.db import get_connection
from app.deactivation_repository import create_deactivation_request
from app.edition_repository import get_edition_by_id, get_editions_by_traveler
from app.feedback_repository import create_feedback
from app.firebase import TokenClaims
from app.invitation_claim import claim_invitation
from app.traveler_repository import get_traveler_by_id, update_traveler_preferences

router = APIRouter(tags=["traveler"])


@router.post("/invitations/claim")
async def claim(
    body: ClaimRequest,
    claims: TokenClaims = Depends(get_verified_claims),
) -> dict:
    conn = get_connection()
    try:
        result = claim_invitation(
            conn,
            provider=claims.provider,
            subject=claims.subject,
            invitation_code=body.invitation_code,
        )
    finally:
        conn.close()
    if not result.ok:
        raise HTTPException(status_code=400, detail="invitation_claim_failed")
    return {"traveler_id": result.traveler_id}


@router.get("/traveler/preferences")
async def get_preferences(principal: Principal = Depends(require_traveler)) -> dict:
    conn = get_connection()
    try:
        traveler = get_traveler_by_id(conn, principal.traveler_id)  # type: ignore[arg-type]
    finally:
        conn.close()
    if traveler is None:
        raise HTTPException(status_code=404, detail="not_found")
    return traveler_preferences_to_dict(traveler)


@router.put("/traveler/preferences")
async def put_preferences(
    body: PreferencesUpdate,
    principal: Principal = Depends(require_traveler),
) -> dict:
    fields = body.model_dump(exclude_unset=True)
    conn = get_connection()
    try:
        traveler = get_traveler_by_id(conn, principal.traveler_id)  # type: ignore[arg-type]
        if traveler is None:
            raise HTTPException(status_code=404, detail="not_found")
        if fields:
            update_traveler_preferences(
                conn, principal.traveler_id, **fields  # type: ignore[arg-type]
            )
        updated = get_traveler_by_id(conn, principal.traveler_id)  # type: ignore[arg-type]
    finally:
        conn.close()
    return traveler_preferences_to_dict(updated)


@router.get("/traveler/editions")
async def list_editions(principal: Principal = Depends(require_traveler)) -> dict:
    conn = get_connection()
    try:
        editions = get_editions_by_traveler(conn, principal.traveler_id)  # type: ignore[arg-type]
    finally:
        conn.close()
    published = [
        edition_summary_to_dict(ed)
        for ed in editions
        if ed.publication_state == "published"
    ]
    return {"editions": published}


@router.get("/traveler/editions/{edition_id}")
async def get_edition(
    edition_id: str,
    principal: Principal = Depends(require_traveler),
) -> dict:
    conn = get_connection()
    try:
        edition = get_edition_by_id(conn, edition_id)
    finally:
        conn.close()
    if (
        edition is None
        or edition.traveler_id != principal.traveler_id
        or edition.publication_state != "published"
    ):
        raise HTTPException(status_code=404, detail="not_found")
    return edition_to_dict(edition)


@router.post("/traveler/feedback")
async def submit_feedback(
    body: FeedbackRequest,
    principal: Principal = Depends(require_traveler),
) -> dict:
    conn = get_connection()
    try:
        edition = get_edition_by_id(conn, body.edition_id)
        if (
            edition is None
            or edition.traveler_id != principal.traveler_id
            or edition.publication_state != "published"
        ):
            raise HTTPException(status_code=404, detail="not_found")
        record = create_feedback(
            conn,
            traveler_id=principal.traveler_id,  # type: ignore[arg-type]
            edition_id=body.edition_id,
            direction_choices=body.direction_choices,
            selected_section_id=body.selected_section_id,
            free_text=body.free_text,
        )
    finally:
        conn.close()
    return {"id": record.id, "edition_id": record.edition_id}


@router.post("/traveler/deactivation-request")
async def deactivation_request(
    principal: Principal = Depends(require_traveler),
) -> dict:
    conn = get_connection()
    try:
        with conn:
            create_deactivation_request(conn, principal.traveler_id)  # type: ignore[arg-type]
    finally:
        conn.close()
    return {"status": "pending"}
