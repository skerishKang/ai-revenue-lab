"""Traveler web routes for Living Travel Phase 2."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import TravelerContext, get_traveler, verify_csrf
from app.db import get_connection
from app.edition_repository import get_edition_by_id, get_editions_by_traveler
from app.feedback_repository import create_feedback, get_feedback_by_edition
from app.pipeline.markup import check_unsafe_markup
from app.security import constant_time_compare
from app.security import (
    create_traveler_session,
    generate_csrf_token,
    invalidate_traveler_session,
    validate_traveler_token,
)
from app.traveler_repository import get_traveler_by_id, update_traveler_preferences
from app.web.templates import render_template

router = APIRouter(prefix="/traveler", tags=["traveler"])

_VALID_CONTEXTS = {"solo", "couple", "family", "group"}
_VALID_BUDGETS = {"budget", "moderate", "premium"}
_VALID_PACES = {"relaxed", "comfortable", "energetic"}
_VALID_TONES = {"calm", "energetic", "luxury"}
_VALID_LENGTHS = {"short", "medium", "long"}
_VALID_LANGUAGES = {"ko", "en", "ja", "zh"}

_MAX_DESTINATION_LENGTH = 120
_MAX_LIST_ITEMS = 12
_MAX_LIST_ITEM_LENGTH = 80
_MIN_NIGHTS = 1
_MAX_NIGHTS = 30
_PREFERENCE_ERROR = "Invalid preference submission. Review every field and try again."


def _set_csrf_cookie(resp, csrf: str):
    resp.set_cookie("lt_csrf", csrf, httponly=True, samesite="strict", max_age=3600)
    return resp


def _enter_page_response(error: str) -> HTMLResponse:
    csrf = generate_csrf_token()
    resp = HTMLResponse(render_template("traveler_enter.html", {"csrf_token": csrf, "error": error}))
    _set_csrf_cookie(resp, csrf)
    return resp


def _split_bounded_list(raw: str) -> list[str] | None:
    values = [value.strip() for value in raw.split(",") if value.strip()]
    if len(values) > _MAX_LIST_ITEMS:
        return None
    if any(len(value) > _MAX_LIST_ITEM_LENGTH for value in values):
        return None
    return values


def _has_unsafe_text(values: list[str]) -> bool:
    return any(check_unsafe_markup(value) for value in values)


def _validate_preferences(
    *,
    destination: str,
    trip_duration_nights: int,
    interests: str,
    trip_context: str,
    budget_tendency: str,
    pace_preference: str,
    exclusions: str,
    tone_preference: str,
    length_preference: str,
    preferred_language: str,
) -> dict | None:
    clean_destination = destination.strip()
    interest_list = _split_bounded_list(interests)
    exclusion_list = _split_bounded_list(exclusions)

    if not clean_destination or len(clean_destination) > _MAX_DESTINATION_LENGTH:
        return None
    if not _MIN_NIGHTS <= trip_duration_nights <= _MAX_NIGHTS:
        return None
    if interest_list is None or exclusion_list is None:
        return None
    if trip_context not in _VALID_CONTEXTS:
        return None
    if budget_tendency not in _VALID_BUDGETS:
        return None
    if pace_preference not in _VALID_PACES:
        return None
    if tone_preference not in _VALID_TONES:
        return None
    if length_preference not in _VALID_LENGTHS:
        return None
    if preferred_language not in _VALID_LANGUAGES:
        return None

    free_text_values = [clean_destination, *interest_list, *exclusion_list]
    if _has_unsafe_text(free_text_values):
        return None

    return {
        "destination": clean_destination,
        "trip_duration_nights": trip_duration_nights,
        "interests": interest_list,
        "trip_context": trip_context,
        "budget_tendency": budget_tendency,
        "pace_preference": pace_preference,
        "exclusions": exclusion_list,
        "tone_preference": tone_preference,
        "length_preference": length_preference,
        "preferred_language": preferred_language,
    }


def _dashboard_response(
    traveler_ctx: TravelerContext,
    *,
    error: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    conn = get_connection()
    try:
        traveler = get_traveler_by_id(conn, traveler_ctx.traveler_id)
        if not traveler or traveler.status != "active":
            return HTMLResponse(
                render_template("404.html", {}),
                status_code=404,
                headers={"Cache-Control": "no-store"},
            )

        editions = get_editions_by_traveler(conn, traveler_ctx.traveler_id)
        published = [edition for edition in editions if edition.publication_state == "published"]
        latest = published[-1] if published else None
        pending_deactivation = conn.execute(
            "SELECT id FROM deactivation_requests "
            "WHERE traveler_id = ? AND status = 'pending' LIMIT 1",
            (traveler_ctx.traveler_id,),
        ).fetchone()

        return HTMLResponse(
            render_template(
                "traveler_dashboard.html",
                {
                    "traveler": traveler,
                    "latest_edition": latest,
                    "published_count": len(published),
                    "csrf_token": traveler_ctx.csrf_token,
                    "error": error,
                    "interest_text": ", ".join(traveler.interests or []),
                    "exclusion_text": ", ".join(traveler.exclusions or []),
                    "has_deactivation_request": pending_deactivation is not None,
                },
            ),
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )
    finally:
        conn.close()


@router.get("/enter")
async def traveler_enter_page(request: Request):
    csrf = generate_csrf_token()
    resp = HTMLResponse(render_template("traveler_enter.html", {"csrf_token": csrf, "error": ""}))
    resp.set_cookie("lt_csrf", csrf, httponly=True, samesite="strict", max_age=3600)
    return resp


@router.post("/enter")
async def traveler_enter_submit(
    request: Request,
    token: str = Form(...),
    csrf_token: str = Form(...),
    lt_csrf: Optional[str] = Cookie(None),
):
    if not lt_csrf or not csrf_token or not constant_time_compare(csrf_token, lt_csrf):
        return _enter_page_response("Invalid CSRF token")
    conn = get_connection()
    try:
        traveler_id = validate_traveler_token(conn, token.strip())
        if not traveler_id:
            return _enter_page_response("Invalid or deactivated token")
        _session_id, raw_token, csrf = create_traveler_session(conn, traveler_id)
    finally:
        conn.close()
    resp = RedirectResponse(url="/traveler/", status_code=303)
    resp.set_cookie("lt_traveler_session", raw_token, httponly=True, samesite="strict", max_age=86400)
    resp.set_cookie("lt_csrf", csrf, httponly=True, samesite="strict", max_age=3600)
    return resp


@router.post("/logout")
async def traveler_logout(
    request: Request,
    csrf_token: str = Form(...),
    traveler_ctx: TravelerContext = __import__("fastapi").Depends(get_traveler),
):
    """Logout traveler by invalidating session. Requires CSRF."""
    verify_csrf(request, csrf_token, traveler_ctx)
    conn = get_connection()
    try:
        invalidate_traveler_session(conn, traveler_ctx.session_id)
    finally:
        conn.close()

    resp = RedirectResponse(url="/traveler/enter", status_code=303)
    resp.delete_cookie("lt_traveler_session")
    return resp


@router.get("/")
async def traveler_dashboard(
    request: Request,
    traveler_ctx: TravelerContext = __import__("fastapi").Depends(get_traveler),
):
    return _dashboard_response(traveler_ctx)


@router.post("/preferences")
async def update_preferences(
    request: Request,
    destination: str = Form(""),
    trip_duration_nights: int = Form(2),
    interests: str = Form(""),
    trip_context: str = Form("solo"),
    budget_tendency: str = Form("moderate"),
    pace_preference: str = Form("comfortable"),
    exclusions: str = Form(""),
    tone_preference: str = Form("calm"),
    length_preference: str = Form("medium"),
    preferred_language: str = Form("ko"),
    csrf_token: str = Form(...),
    traveler_ctx: TravelerContext = __import__("fastapi").Depends(get_traveler),
):
    verify_csrf(request, csrf_token, traveler_ctx)

    validated = _validate_preferences(
        destination=destination,
        trip_duration_nights=trip_duration_nights,
        interests=interests,
        trip_context=trip_context,
        budget_tendency=budget_tendency,
        pace_preference=pace_preference,
        exclusions=exclusions,
        tone_preference=tone_preference,
        length_preference=length_preference,
        preferred_language=preferred_language,
    )
    if validated is None:
        return _dashboard_response(
            traveler_ctx,
            error=_PREFERENCE_ERROR,
            status_code=422,
        )

    conn = get_connection()
    try:
        update_traveler_preferences(
            conn,
            traveler_ctx.traveler_id,
            **validated,
        )
    finally:
        conn.close()
    return RedirectResponse(url="/traveler/", status_code=303)


@router.post("/deactivation-request")
async def deactivation_request(
    request: Request,
    csrf_token: str = Form(...),
    traveler_ctx: TravelerContext = __import__("fastapi").Depends(get_traveler),
):
    """Create at most one durable pending deactivation request per traveler."""
    verify_csrf(request, csrf_token, traveler_ctx)

    from datetime import datetime, timezone
    from app.security import generate_high_entropy_token

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    request_id = "dr_" + generate_high_entropy_token(8)

    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO deactivation_requests "
                "(id, traveler_id, status, created_at, updated_at) "
                "VALUES (?, ?, 'pending', ?, ?)",
                (request_id, traveler_ctx.traveler_id, now, now),
            )
    finally:
        conn.close()

    return RedirectResponse(url="/traveler/", status_code=303)


@router.get("/editions")
async def edition_history(
    request: Request,
    traveler_ctx: TravelerContext = __import__("fastapi").Depends(get_traveler),
):
    conn = get_connection()
    try:
        editions = get_editions_by_traveler(conn, traveler_ctx.traveler_id)
        published = [e for e in editions if e.publication_state == "published"]
        return HTMLResponse(render_template("traveler_edition.html", {
            "traveler_id": traveler_ctx.traveler_id,
            "editions": published,
            "is_history": True,
            "is_single": False,
            "csrf_token": traveler_ctx.csrf_token,
        }))
    finally:
        conn.close()


@router.get("/editions/{edition_id}")
async def edition_view(
    edition_id: str,
    request: Request,
    traveler_ctx: TravelerContext = __import__("fastapi").Depends(get_traveler),
):
    conn = get_connection()
    try:
        edition = get_edition_by_id(conn, edition_id)
        if not edition or edition.traveler_id != traveler_ctx.traveler_id:
            return HTMLResponse(render_template("404.html", {}), status_code=404)
        if edition.publication_state != "published":
            return HTMLResponse(render_template("404.html", {}), status_code=404)
        feedback_list = get_feedback_by_edition(conn, edition_id)
        sc = edition.structured_content or {}
        return HTMLResponse(render_template("traveler_edition.html", {
            "edition": edition,
            "feedback": feedback_list,
            "is_history": False,
            "is_single": True,
            "sc": sc,
            "csrf_token": traveler_ctx.csrf_token,
        }))
    finally:
        conn.close()


@router.post("/editions/{edition_id}/feedback")
async def submit_feedback(
    edition_id: str,
    request: Request,
    choices: list[str] = Form(default=[]),
    free_text: str = Form(""),
    csrf_token: str = Form(...),
    traveler_ctx: TravelerContext = __import__("fastapi").Depends(get_traveler),
):
    verify_csrf(request, csrf_token, traveler_ctx)
    conn = get_connection()
    try:
        edition = get_edition_by_id(conn, edition_id)
        if not edition or edition.traveler_id != traveler_ctx.traveler_id:
            return HTMLResponse(render_template("404.html", {}), status_code=404)
        if edition.publication_state != "published":
            return RedirectResponse(url="/traveler/", status_code=303)
        existing = get_feedback_by_edition(conn, edition_id)
        already_submitted = any(f.traveler_id == traveler_ctx.traveler_id for f in existing)
        if already_submitted:
            return RedirectResponse(url=f"/traveler/editions/{edition_id}", status_code=303)
        choice_list = [c.strip() for c in choices if c.strip()] if choices else []
        create_feedback(
            conn,
            traveler_id=traveler_ctx.traveler_id,
            edition_id=edition_id,
            direction_choices=choice_list,
            free_text=free_text[:500] if free_text else "",
        )
    finally:
        conn.close()
    return RedirectResponse(url=f"/traveler/editions/{edition_id}", status_code=303)
