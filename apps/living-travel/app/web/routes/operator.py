"""Operator web routes for Living Travel Phase 2.

All state-changing routes require CSRF validation.
Operator auth uses a shared secret (LT_OPERATOR_SECRET).
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import OperatorContext, get_operator, verify_csrf
from app.security import constant_time_compare
from app.db import get_connection
from app.edition_repository import (
    create_edition,
    get_edition_by_id,
    get_editions_by_traveler,
    update_edition_content,
    update_edition_generation_status,
    update_edition_publication,
)
from app.feedback_repository import (
    get_unapplied_feedback_for_traveler,
    get_unapplied_feedback_for_edition,
)
from app.generation_run_repository import count_generation_runs_by_edition
from app.pilot_evidence_repository import get_pilot_evidence_by_traveler
from app.pipeline.service import GenerationService
from app.pipeline.errors import PipelineError
from app.ai.providers import create_mock_provider, create_second_mock_provider
from app.security import (
    create_operator_session,
    create_traveler_token,
    deactivate_traveler_tokens,
    invalidate_operator_session,
    invalidate_traveler_session,
    rotate_traveler_token,
    generate_csrf_token,
    get_login_rate_limiter,
    validate_operator_session,
)
from app.source_repository import get_sources_by_destination
from app.traveler_repository import (
    activate_traveler,
    create_traveler,
    delete_traveler,
    get_all_travelers,
    get_traveler_by_id,
    is_traveler_active,
)
from app.web.templates import render_template

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/operator", tags=["operator"])


def _build_source_items(conn, destination: str) -> list[dict]:
    """Build source item dicts from source records."""
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


def _build_traveler_preferences(traveler) -> dict:
    """Build preferences dict from TravelerRecord for the generation service."""
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


def _get_rate_limit_key(request: Request) -> str:
    """Get rate limit key from request.client, with fallback bucket."""
    if request.client and request.client.host:
        return request.client.host
    return "__fallback__"


def _set_csrf_cookie(resp, csrf: str):
    """Set CSRF cookie on a response."""
    resp.set_cookie("lt_csrf", csrf, httponly=True, samesite="strict", max_age=3600)
    return resp


def _login_page_response(error: str) -> HTMLResponse:
    """Build login page with new CSRF token and cookie."""
    csrf = generate_csrf_token()
    resp = HTMLResponse(
        render_template("operator_login.html", {"csrf_token": csrf, "error": error})
    )
    _set_csrf_cookie(resp, csrf)
    return resp


# --- Auth ---

@router.get("/login")
async def operator_login_page(request: Request):
    """Show operator login page with CSRF token."""
    csrf = generate_csrf_token()
    resp = HTMLResponse(
        render_template("operator_login.html", {"csrf_token": csrf, "error": ""})
    )
    resp.set_cookie("lt_csrf", csrf, httponly=True, samesite="strict", max_age=3600)
    return resp


@router.post("/login")
async def operator_login_submit(
    request: Request,
    secret: str = Form(...),
    csrf_token: str = Form(...),
    lt_csrf: Optional[str] = Cookie(None),
):
    """Authenticate operator with shared secret. Rate-limited."""
    from app.config import get_settings
    settings = get_settings()

    rate_limiter = get_login_rate_limiter()
    rate_key = _get_rate_limit_key(request)

    if rate_limiter.is_locked(rate_key):
        return _login_page_response("Too many failed attempts. Please try again later.")

    if not lt_csrf or not csrf_token or not constant_time_compare(csrf_token, lt_csrf):
        return _login_page_response("Invalid CSRF token")

    if not settings.operator_secret or not constant_time_compare(secret, settings.operator_secret):
        rate_limiter.record_failure(rate_key)
        return _login_page_response("Invalid secret")

    rate_limiter.record_success(rate_key)

    conn = get_connection()
    try:
        session_id, raw_token, csrf = create_operator_session(conn)
    finally:
        conn.close()

    resp = RedirectResponse(url="/operator/", status_code=303)
    resp.set_cookie("lt_operator_session", raw_token, httponly=True, samesite="strict", max_age=28800)
    return resp


@router.post("/logout")
async def operator_logout(
    request: Request,
    csrf_token: str = Form(...),
    operator: OperatorContext = __import__("fastapi").Depends(get_operator),
):
    """Logout operator by invalidating session. Requires CSRF."""
    verify_csrf(request, csrf_token, operator)
    conn = get_connection()
    try:
        invalidate_operator_session(conn, operator.session_id)
    finally:
        conn.close()

    resp = RedirectResponse(url="/operator/login", status_code=303)
    resp.delete_cookie("lt_operator_session")
    return resp


# --- Dashboard ---

@router.get("/")
async def operator_dashboard(request: Request, operator: OperatorContext = __import__("fastapi").Depends(get_operator)):
    """Operator dashboard showing all travelers."""
    conn = get_connection()
    try:
        travelers = get_all_travelers(conn)
        traveler_data = []
        for t in travelers:
            editions = get_editions_by_traveler(conn, t.id)
            traveler_data.append({
                "traveler": t,
                "edition_count": len(editions),
                "latest_edition": editions[-1] if editions else None,
            })
        return HTMLResponse(
            render_template("operator_dashboard.html", {
                "travelers": traveler_data,
                "csrf_token": operator.csrf_token,
            })
        )
    finally:
        conn.close()


# --- Traveler Management ---

@router.post("/travelers/create")
async def create_traveler_submit(
    request: Request,
    display_name: str = Form(...),
    destination: str = Form(...),
    trip_duration_nights: int = Form(2),
    csrf_token: str = Form(...),
    operator: OperatorContext = __import__("fastapi").Depends(get_operator),
):
    """Create a new synthetic traveler."""
    verify_csrf(request, csrf_token, operator)
    conn = get_connection()
    try:
        create_traveler(
            conn,
            display_name=display_name,
            destination=destination,
            trip_duration_nights=trip_duration_nights,
        )
    finally:
        conn.close()
    return RedirectResponse(url="/operator/", status_code=303)


@router.get("/travelers/{traveler_id}")
async def traveler_detail(
    traveler_id: str,
    request: Request,
    operator: OperatorContext = __import__("fastapi").Depends(get_operator),
):
    """View traveler details, editions, tokens with conditional action UI."""
    conn = get_connection()
    try:
        traveler = get_traveler_by_id(conn, traveler_id)
        if not traveler:
            return HTMLResponse(render_template("404.html", {}), status_code=404)

        editions = get_editions_by_traveler(conn, traveler_id)
        pilot_evidence = get_pilot_evidence_by_traveler(conn, traveler_id)

        edition_data = []
        for ed in editions:
            run_count = count_generation_runs_by_edition(conn, ed.id)
            edition_data.append({
                "edition": ed,
                "run_count": run_count,
            })

        is_active = traveler.status == "active"

        has_pending_review = any(
            ed.generation_status == "pending_review" for ed in editions
        )
        has_generation_failed = any(
            ed.generation_status == "generation_failed" for ed in editions
        )
        published_editions = [ed for ed in editions if ed.publication_state == "published"]
        has_published = len(published_editions) > 0

        unapplied_fb = get_unapplied_feedback_for_traveler(conn, traveler_id)
        has_unapplied_feedback = len(unapplied_fb) > 0

        last_failure_category = ""
        if has_generation_failed:
            for ed in reversed(editions):
                if ed.generation_status == "generation_failed":
                    runs = conn.execute(
                        "SELECT error_category FROM generation_runs WHERE edition_id = ? AND error_category != '' ORDER BY created_at DESC LIMIT 1",
                        (ed.id,),
                    ).fetchone()
                    if runs:
                        last_failure_category = runs["error_category"]
                    break

        failure_category = request.query_params.get("failure", "")
        if failure_category:
            last_failure_category = failure_category

        return HTMLResponse(
            render_template("operator_traveler_detail.html", {
                "traveler": traveler,
                "editions": edition_data,
                "pilot_evidence": pilot_evidence,
                "csrf_token": operator.csrf_token,
                "is_active": is_active,
                "is_inactive": not is_active,
                "has_pending_review": has_pending_review,
                "has_generation_failed": has_generation_failed,
                "has_published": has_published,
                "has_unapplied_feedback": has_unapplied_feedback,
                "has_no_editions": len(editions) == 0,
                "generation_failure": last_failure_category,
                "failure_category": last_failure_category,
            })
        )
    finally:
        conn.close()


@router.post("/travelers/{traveler_id}/deactivate")
async def deactivate_traveler_route(
    traveler_id: str,
    request: Request,
    csrf_token: str = Form(...),
    operator: OperatorContext = __import__("fastapi").Depends(get_operator),
):
    """Deactivate (soft-delete) a traveler and invalidate all tokens/sessions."""
    verify_csrf(request, csrf_token, operator)
    conn = get_connection()
    try:
        if not is_traveler_active(conn, traveler_id):
            return HTMLResponse(render_template("404.html", {}), status_code=404)
        delete_traveler(conn, traveler_id, commit=False)
        deactivate_traveler_tokens(conn, traveler_id, commit=False)
        conn.execute(
            "DELETE FROM traveler_sessions WHERE traveler_id = ?", (traveler_id,)
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/operator/", status_code=303)


@router.post("/travelers/{traveler_id}/activate")
async def activate_traveler_route(
    traveler_id: str,
    request: Request,
    csrf_token: str = Form(...),
    operator: OperatorContext = __import__("fastapi").Depends(get_operator),
):
    """Re-activate a previously deactivated traveler."""
    verify_csrf(request, csrf_token, operator)
    conn = get_connection()
    try:
        activate_traveler(conn, traveler_id)
    finally:
        conn.close()
    return RedirectResponse(url=f"/operator/travelers/{traveler_id}", status_code=303)


# --- Invitation Token ---

@router.post("/travelers/{traveler_id}/invite")
async def create_invitation(
    traveler_id: str,
    request: Request,
    csrf_token: str = Form(...),
    operator: OperatorContext = __import__("fastapi").Depends(get_operator),
):
    """Generate a new invitation token for a traveler. Invalidates any existing active token."""
    verify_csrf(request, csrf_token, operator)
    conn = get_connection()
    try:
        if not is_traveler_active(conn, traveler_id):
            return HTMLResponse(render_template("404.html", {}), status_code=404)
        deactivate_traveler_tokens(conn, traveler_id, commit=False)
        token_id, raw_token = create_traveler_token(conn, traveler_id, commit=False)
        conn.commit()
    finally:
        conn.close()

    return HTMLResponse(
        render_template("operator_token_display.html", {
            "traveler_id": traveler_id,
            "raw_token": raw_token,
            "message": "Save this token. It will not be shown again.",
        })
    )


@router.post("/travelers/{traveler_id}/rotate-invite")
async def rotate_invitation(
    traveler_id: str,
    request: Request,
    csrf_token: str = Form(...),
    operator: OperatorContext = __import__("fastapi").Depends(get_operator),
):
    """Rotate invitation token: invalidate old tokens, generate new one, invalidate sessions."""
    verify_csrf(request, csrf_token, operator)
    conn = get_connection()
    try:
        if not is_traveler_active(conn, traveler_id):
            return HTMLResponse(render_template("404.html", {}), status_code=404)
        deactivate_traveler_tokens(conn, traveler_id, commit=False)
        conn.execute(
            "DELETE FROM traveler_sessions WHERE traveler_id = ?", (traveler_id,)
        )
        token_id, raw_token = create_traveler_token(conn, traveler_id, commit=False)
        conn.commit()
    finally:
        conn.close()

    return HTMLResponse(
        render_template("operator_token_display.html", {
            "traveler_id": traveler_id,
            "raw_token": raw_token,
            "message": "Previous token and sessions have been invalidated. Save this new token.",
        })
    )


# --- Edition Generation ---

@router.post("/travelers/{traveler_id}/generate-first")
async def generate_first_edition(
    traveler_id: str,
    request: Request,
    csrf_token: str = Form(...),
    operator: OperatorContext = __import__("fastapi").Depends(get_operator),
):
    """Generate the first edition for a traveler using the pipeline service."""
    verify_csrf(request, csrf_token, operator)
    conn = get_connection()
    failure_category = ""
    try:
        traveler = get_traveler_by_id(conn, traveler_id)
        if not traveler or traveler.status != "active":
            return HTMLResponse(render_template("404.html", {}), status_code=404)

        preferences = _build_traveler_preferences(traveler)

        provider = create_mock_provider(conn, preferences)
        source_items = _build_source_items(conn, traveler.destination)
        service = GenerationService(conn, provider)
        try:
            service.generate_first_edition(
                traveler_id=traveler_id,
                traveler_preferences=preferences,
                source_items=source_items,
            )
        except PipelineError as exc:
            failure_category = _extract_failure_category(exc)
            logger.warning("PipelineError in generate-first: %s", exc)
        except Exception:
            failure_category = "unexpected_error"
            logger.exception("Unexpected error in generate-first")
            raise
    finally:
        conn.close()
    redirect_url = f"/operator/travelers/{traveler_id}"
    if failure_category:
        redirect_url += f"?failure={failure_category}"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/travelers/{traveler_id}/generate-second")
async def generate_second_edition(
    traveler_id: str,
    request: Request,
    csrf_token: str = Form(...),
    operator: OperatorContext = __import__("fastapi").Depends(get_operator),
):
    """Generate second edition using the latest published edition as prior."""
    verify_csrf(request, csrf_token, operator)
    conn = get_connection()
    failure_category = ""
    try:
        traveler = get_traveler_by_id(conn, traveler_id)
        if not traveler or traveler.status != "active":
            return HTMLResponse(render_template("404.html", {}), status_code=404)

        editions = get_editions_by_traveler(conn, traveler_id)
        prior = None
        for ed in reversed(editions):
            if ed.publication_state == "published" and ed.structured_content and ed.structured_content != {}:
                prior = ed
                break
        if prior is None:
            return RedirectResponse(url=f"/operator/travelers/{traveler_id}", status_code=303)

        preferences = _build_traveler_preferences(traveler)
        feedback_records = get_unapplied_feedback_for_edition(
            conn, traveler_id, prior.id
        )

        provider = create_second_mock_provider(
            conn, preferences, feedback_records, prior.structured_content
        )
        source_items = _build_source_items(conn, traveler.destination)
        service = GenerationService(conn, provider)
        try:
            service.generate_second_edition(
                traveler_id=traveler_id,
                prior_edition_id=prior.id,
                traveler_preferences=preferences,
                source_items=source_items,
            )
        except PipelineError as exc:
            failure_category = _extract_failure_category(exc)
            logger.warning("PipelineError in generate-second: %s", exc)
        except Exception:
            failure_category = "unexpected_error"
            logger.exception("Unexpected error in generate-second")
            raise
    finally:
        conn.close()
    redirect_url = f"/operator/travelers/{traveler_id}"
    if failure_category:
        redirect_url += f"?failure={failure_category}"
    return RedirectResponse(url=redirect_url, status_code=303)


def _extract_failure_category(exc: PipelineError) -> str:
    """Extract an allow-listed failure category from a PipelineError."""
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


# --- Edition Publication ---

@router.post("/editions/{edition_id}/publish")
async def publish_edition(
    edition_id: str,
    request: Request,
    csrf_token: str = Form(...),
    operator: OperatorContext = __import__("fastapi").Depends(get_operator),
):
    """Explicitly publish a pending_review edition. Requires CSRF.
    Only publication_state changes; generation_status stays pending_review."""
    verify_csrf(request, csrf_token, operator)
    conn = get_connection()
    try:
        edition = get_edition_by_id(conn, edition_id)
        if not edition:
            return HTMLResponse(render_template("404.html", {}), status_code=404)
        if edition.generation_status != "pending_review":
            return RedirectResponse(url=f"/operator/travelers/{edition.traveler_id}", status_code=303)
        update_edition_publication(conn, edition_id, "published")
        traveler_id = edition.traveler_id
    finally:
        conn.close()
    return RedirectResponse(url=f"/operator/travelers/{traveler_id}", status_code=303)


@router.post("/editions/{edition_id}/reject")
async def reject_edition(
    edition_id: str,
    request: Request,
    csrf_token: str = Form(...),
    operator: OperatorContext = __import__("fastapi").Depends(get_operator),
):
    """Explicitly reject a pending_review edition. Requires CSRF.
    Only publication_state changes; generation_status stays pending_review."""
    verify_csrf(request, csrf_token, operator)
    conn = get_connection()
    try:
        edition = get_edition_by_id(conn, edition_id)
        if not edition:
            return HTMLResponse(render_template("404.html", {}), status_code=404)
        if edition.generation_status != "pending_review":
            return RedirectResponse(url=f"/operator/travelers/{edition.traveler_id}", status_code=303)
        update_edition_publication(conn, edition_id, "rejected")
        traveler_id = edition.traveler_id
    finally:
        conn.close()
    return RedirectResponse(url=f"/operator/travelers/{traveler_id}", status_code=303)
