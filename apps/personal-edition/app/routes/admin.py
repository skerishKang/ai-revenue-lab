"""Admin/operator routes: authentication, participant overview, generation,
review, editing, publish/reject."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app import participant_repository as pt_repo
from app import input_repository as input_repo
from app import edition_repository as ed_repo
from app import feedback_repository as fb_repo
from app import generation_run_repository as gr_repo
from app.auth import (
    create_admin_session,
    decode_admin_session_token,
    generate_csrf_token,
    is_admin_session,
    sign_csrf_token,
    sign_admin_session_token,
    verify_admin_secret,
    verify_csrf_token,
)
from app.db import get_connection
from app.factory import _privacy_headers, _render_template, _set_cookie, _delete_cookie
from app.pipeline.markup import UnsafeMarkupError, check_payload
from app.pipeline.service import GenerationRequest, GenerationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

SESSION_COOKIE = "pe_admin_session"
CSRF_COOKIE = "pe_admin_csrf"


def _get_admin(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    session_data = decode_admin_session_token(token)
    if session_data is None:
        return False
    return is_admin_session(session_data)


def _inject_csrf(context: dict[str, Any]) -> tuple[str, str]:
    csrf_token = generate_csrf_token()
    signed = sign_csrf_token(csrf_token)
    context["csrf_token"] = csrf_token
    return csrf_token, signed


def _validate_csrf(request: Request, csrf_field: str) -> bool:
    cookie_val = request.cookies.get(CSRF_COOKIE, "")
    if not cookie_val or not csrf_field:
        return False
    return verify_csrf_token(csrf_field, cookie_val)


def _admin_error_response(request, message, edition=None, content=None,
                          participant=None, feedbacks=None, runs=None):
    context: dict[str, Any] = {
        "edition": edition,
        "content": content,
        "participant": participant,
        "feedbacks": feedbacks or [],
        "generation_runs": runs or [],
        "csrf_token": "",
        "error": message,
    }
    resp = _render_template(request, "admin_review.html", context)
    new_token, new_signed = _inject_csrf({})
    context["csrf_token"] = new_token
    resp = _render_template(request, "admin_review.html", context)
    _set_cookie(resp, CSRF_COOKIE, new_signed)
    return resp


def _validate_edition_content(structured_content: str) -> tuple[bool, str]:
    """Validate structured content as EditionContent with markup policy.

    Returns (is_valid, error_message).
    """
    try:
        parsed = json.loads(structured_content)
    except (json.JSONDecodeError, TypeError):
        return False, "Invalid JSON in structured content."

    if not isinstance(parsed, dict):
        return False, "Structured content must be a JSON object."

    required_top = ["content_version", "language", "publication_title",
                    "edition_title", "deck", "opening", "sections",
                    "highlighted_insight"]
    for field in required_top:
        if field not in parsed:
            return False, f"Missing required field: {field}"

    sections = parsed.get("sections")
    if not isinstance(sections, list) or len(sections) < 2:
        return False, "At least two sections are required."

    for i, section in enumerate(sections):
        if not isinstance(section, dict):
            return False, f"Section {i} must be a JSON object."
        for sfield in ["section_id", "title", "paragraphs", "source_segment_ids"]:
            if sfield not in section:
                return False, f"Section {i} missing required field: {sfield}"
        if not isinstance(section["paragraphs"], list) or not section["paragraphs"]:
            return False, f"Section {i} must have at least one paragraph."

    section_ids = [s["section_id"] for s in sections]
    if len(section_ids) != len(set(section_ids)):
        return False, "Duplicate section IDs found."

    try:
        check_payload(parsed)
    except UnsafeMarkupError:
        return False, "Content contains unsafe markup (HTML tags, event handlers, or javascript: URLs)."

    return True, ""


@router.get("/access")
def admin_access_page(request: Request):
    context: dict[str, Any] = {"error": None, "csrf_token": ""}
    resp = _render_template(request, "admin_access.html", context)
    csrf_token, csrf_signed = _inject_csrf({})
    context["csrf_token"] = csrf_token
    resp = _render_template(request, "admin_access.html", context)
    _set_cookie(resp, CSRF_COOKIE, csrf_signed)
    return resp


@router.post("/access")
def admin_access_submit(
    request: Request,
    secret: str = Form(""),
    csrf_token: str = Form(""),
):
    if not _validate_csrf(request, csrf_token):
        context = {"error": "Invalid or expired form token. Please try again.", "csrf_token": ""}
        resp = _render_template(request, "admin_access.html", context)
        new_token, new_signed = _inject_csrf({})
        context["csrf_token"] = new_token
        resp = _render_template(request, "admin_access.html", context)
        _set_cookie(resp, CSRF_COOKIE, new_signed)
        return resp

    secret = secret.strip()
    if not secret or not verify_admin_secret(secret):
        context = {"error": "Invalid admin secret.", "csrf_token": ""}
        resp = _render_template(request, "admin_access.html", context)
        new_token, new_signed = _inject_csrf({})
        context["csrf_token"] = new_token
        resp = _render_template(request, "admin_access.html", context)
        _set_cookie(resp, CSRF_COOKIE, new_signed)
        return resp

    session_data = create_admin_session()
    signed_token = sign_admin_session_token(session_data)
    resp = RedirectResponse(url="/admin/", status_code=303)
    _set_cookie(resp, SESSION_COOKIE, signed_token)
    return resp


@router.get("/")
def admin_dashboard(request: Request):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    conn = get_connection(request.app.state.db_path)
    try:
        participants = conn.execute(
            "SELECT id, display_name, preferred_language, status, created_at "
            "FROM participants WHERE status = 'active' ORDER BY created_at"
        ).fetchall()
        editions = conn.execute(
            "SELECT e.id, e.participant_id, e.edition_number, "
            "e.generation_status, e.publication_state, e.rendered_title, "
            "e.drafted_at, e.published_at, p.display_name "
            "FROM editions e "
            "JOIN participants p ON e.participant_id = p.id "
            "WHERE e.generation_status != 'deleted' "
            "ORDER BY e.drafted_at DESC"
        ).fetchall()
    finally:
        conn.close()

    context: dict[str, Any] = {
        "participants": participants,
        "editions": editions,
        "csrf_token": "",
    }
    resp = _render_template(request, "admin_dashboard.html", context)
    csrf_token, csrf_signed = _inject_csrf({})
    context["csrf_token"] = csrf_token
    resp = _render_template(request, "admin_dashboard.html", context)
    _set_cookie(resp, CSRF_COOKIE, csrf_signed)
    return resp


@router.get("/participants/{participant_id}")
def admin_participant_detail(request: Request, participant_id: str):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    conn = get_connection(request.app.state.db_path)
    try:
        participant = pt_repo.get_participant_by_id(conn, participant_id)
        if participant is None:
            return _render_template(request, "admin_not_found.html", {
                "message": "Participant not found.",
            })

        editions = ed_repo.get_editions_by_participant(conn, participant_id)
        inputs = input_repo.get_inputs_by_participant(conn, participant_id)

        gen_runs = conn.execute(
            "SELECT * FROM generation_runs ORDER BY started_at DESC LIMIT 20"
        ).fetchall()
    finally:
        conn.close()

    context: dict[str, Any] = {
        "participant": participant,
        "editions": editions,
        "inputs": inputs,
        "generation_runs": gen_runs,
        "csrf_token": "",
    }
    resp = _render_template(request, "admin_participant_detail.html", context)
    csrf_token, csrf_signed = _inject_csrf({})
    context["csrf_token"] = csrf_token
    resp = _render_template(request, "admin_participant_detail.html", context)
    _set_cookie(resp, CSRF_COOKIE, csrf_signed)
    return resp


@router.post("/participants/{participant_id}/generate")
def admin_generate(
    request: Request,
    participant_id: str,
    input_id: str = Form(""),
    allow_short_sample: str = Form("0"),
    csrf_token: str = Form(""),
):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    if not _validate_csrf(request, csrf_token):
        return RedirectResponse(
            url=f"/admin/participants/{participant_id}", status_code=303
        )

    conn = get_connection(request.app.state.db_path)
    try:
        participant = pt_repo.get_participant_by_id(conn, participant_id)
        if participant is None:
            return _render_template(request, "admin_not_found.html", {
                "message": "Participant not found.",
            })

        service: GenerationService = request.app.state.generation_service
        gen_request = GenerationRequest(
            participant_id=participant_id,
            input_id=input_id,
            allow_short_sample=(allow_short_sample == "1"),
        )
        result = service.generate_edition(conn, request=gen_request)
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/participants/{participant_id}", status_code=303
    )


@router.get("/review/{edition_id}")
def admin_review_page(request: Request, edition_id: str):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    conn = get_connection(request.app.state.db_path)
    try:
        edition = ed_repo.get_edition_by_id(conn, edition_id)
        if edition is None:
            return _render_template(request, "admin_not_found.html", {
                "message": "Edition not found.",
            })

        content = None
        if edition.structured_content:
            content = json.loads(edition.structured_content)

        participant = pt_repo.get_participant_by_id(
            conn, edition.participant_id
        )

        feedbacks = fb_repo.get_feedback_by_edition(conn, edition_id)

        runs = conn.execute(
            "SELECT * FROM generation_runs ORDER BY started_at DESC"
        ).fetchall()
    finally:
        conn.close()

    context: dict[str, Any] = {
        "edition": edition,
        "content": content,
        "participant": participant,
        "feedbacks": feedbacks,
        "generation_runs": runs,
        "csrf_token": "",
    }
    resp = _render_template(request, "admin_review.html", context)
    csrf_token, csrf_signed = _inject_csrf({})
    context["csrf_token"] = csrf_token
    resp = _render_template(request, "admin_review.html", context)
    _set_cookie(resp, CSRF_COOKIE, csrf_signed)
    return resp


@router.post("/review/{edition_id}/edit")
def admin_review_edit(
    request: Request,
    edition_id: str,
    response: Response,
    structured_content: str = Form(""),
    rendered_title: str = Form(""),
    reviewer_notes: str = Form(""),
    csrf_token: str = Form(""),
):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    if not _validate_csrf(request, csrf_token):
        return RedirectResponse(
            url=f"/admin/review/{edition_id}", status_code=303
        )

    conn = get_connection(request.app.state.db_path)
    try:
        is_valid, error_msg = _validate_edition_content(structured_content)
        if not is_valid:
            edition = ed_repo.get_edition_by_id(conn, edition_id)
            content = None
            if edition and edition.structured_content:
                content = json.loads(edition.structured_content)
            return _admin_error_response(
                request, error_msg,
                edition=edition, content=content,
                participant=(
                    pt_repo.get_participant_by_id(conn, edition.participant_id)
                    if edition else None
                ),
                feedbacks=(
                    fb_repo.get_feedback_by_edition(conn, edition_id)
                    if edition else []
                ),
                runs=conn.execute(
                    "SELECT * FROM generation_runs ORDER BY started_at DESC"
                ).fetchall(),
            )

        ed_repo.update_edition_content(
            conn,
            edition_id,
            structured_content=structured_content,
            rendered_title=rendered_title if rendered_title else None,
            reviewer_notes=reviewer_notes if reviewer_notes else None,
        )
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/review/{edition_id}", status_code=303
    )


@router.post("/review/{edition_id}/publish")
def admin_publish(
    request: Request,
    edition_id: str,
    csrf_token: str = Form(""),
):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    if not _validate_csrf(request, csrf_token):
        return RedirectResponse(
            url=f"/admin/review/{edition_id}", status_code=303
        )

    conn = get_connection(request.app.state.db_path)
    try:
        ed_repo.update_edition_publication(
            conn, edition_id, "published"
        )
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/review/{edition_id}", status_code=303
    )


@router.post("/review/{edition_id}/reject")
def admin_reject(
    request: Request,
    edition_id: str,
    csrf_token: str = Form(""),
):
    if not _get_admin(request):
        return RedirectResponse(url="/admin/access", status_code=303)

    if not _validate_csrf(request, csrf_token):
        return RedirectResponse(
            url=f"/admin/review/{edition_id}", status_code=303
        )

    conn = get_connection(request.app.state.db_path)
    try:
        ed_repo.update_edition_publication(
            conn, edition_id, "rejected"
        )
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/review/{edition_id}", status_code=303
    )


@router.post("/logout")
def admin_logout(request: Request):
    resp = RedirectResponse(url="/admin/access", status_code=303)
    _delete_cookie(resp, SESSION_COOKIE)
    _delete_cookie(resp, CSRF_COOKIE)
    return resp
