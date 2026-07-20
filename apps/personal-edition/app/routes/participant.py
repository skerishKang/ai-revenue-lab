"""Participant-facing routes: token entry, dashboard, input submission,
edition reading, feedback, and logout."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Cookie, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app import participant_repository as pt_repo
from app import input_repository as input_repo
from app import edition_repository as ed_repo
from app import feedback_repository as fb_repo
from app.auth import (
    create_participant_session,
    decode_session_token,
    generate_csrf_token,
    get_participant_id_from_session,
    sign_csrf_token,
    sign_session_token,
    verify_csrf_token,
)
from app.db import get_connection
from app.domain.enums import FeedbackDirection
from app.factory import _privacy_headers, _render_template, _set_cookie, _delete_cookie

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/p")

SESSION_COOKIE = "pe_session"
CSRF_COOKIE = "pe_csrf"


def _get_participant(request: Request, session_token: str | None = None):
    token = session_token
    if token is None:
        token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session_data = decode_session_token(token)
    if session_data is None:
        return None
    pid = get_participant_id_from_session(session_data)
    if pid is None:
        return None
    db_conn = get_connection(request.app.state.db_path)
    try:
        participant = pt_repo.get_participant_by_id(db_conn, pid)
        if participant is None:
            return None
        if participant.status != "active" or participant.deleted_at is not None:
            return None
        return participant
    finally:
        db_conn.close()


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


def _with_csrf_cookie(resp, csrf_signed: str):
    _set_cookie(resp, CSRF_COOKIE, csrf_signed)
    return resp


def _inject_csrf_and_set_cookie(
    request: Request, context: dict[str, Any], response: Response
) -> str:
    csrf_token, csrf_signed = _inject_csrf(context)
    _set_cookie(response, CSRF_COOKIE, csrf_signed)
    return csrf_token


def _edition_section_ids(edition) -> list[str]:
    if not edition or not edition.structured_content:
        return []
    try:
        content = json.loads(edition.structured_content)
        return [s["section_id"] for s in content.get("sections", [])]
    except (json.JSONDecodeError, TypeError, KeyError):
        return []


@router.get("/access")
def token_entry_page(request: Request):
    return _render_template(request, "token_entry.html", {"error": None})


@router.post("/access")
def token_entry_submit(
    request: Request,
    response: Response,
    token: str = Form(""),
):
    token = token.strip()
    if not token:
        resp = _render_template(request, "token_entry.html", {
            "error": "Please enter your access token."
        })
        return resp

    conn = get_connection(request.app.state.db_path)
    try:
        participant = pt_repo.get_active_participant_by_token(conn, token)
    finally:
        conn.close()

    if participant is None:
        resp = _render_template(request, "token_entry.html", {
            "error": "Invalid or inactive access token."
        })
        return resp

    session_data = create_participant_session(participant.id)
    signed_token = sign_session_token(session_data)
    resp = RedirectResponse(url=f"/p/{participant.id}", status_code=303)
    _set_cookie(resp, SESSION_COOKIE, signed_token)
    return resp


@router.get("/{participant_id}")
def participant_dashboard(request: Request, participant_id: str):
    participant = _get_participant(request)
    if participant is None or participant.id != participant_id:
        return RedirectResponse(url="/p/access", status_code=303)

    conn_obj = get_connection(request.app.state.db_path)
    try:
        editions = ed_repo.get_editions_by_participant(conn_obj, participant.id)
        published = [
            e for e in editions
            if e.publication_state == "published"
        ]
        published.sort(key=lambda e: e.edition_number, reverse=True)
        inputs = input_repo.get_inputs_by_participant(conn_obj, participant.id)
    finally:
        conn_obj.close()

    context: dict[str, Any] = {
        "participant": participant,
        "published_editions": published,
        "input_count": len(inputs),
    }
    return _render_template(request, "participant_dashboard.html", context)


@router.get("/{participant_id}/input")
def input_form_page(request: Request, participant_id: str):
    participant = _get_participant(request)
    if participant is None or participant.id != participant_id:
        return RedirectResponse(url="/p/access", status_code=303)

    context: dict[str, Any] = {
        "participant": participant,
        "error": None,
        "success": None,
        "csrf_token": "",
        "raw_text": "",
    }
    csrf_token, csrf_signed = _inject_csrf({})
    context["csrf_token"] = csrf_token
    resp = _render_template(request, "input_form.html", context)
    _set_cookie(resp, CSRF_COOKIE, csrf_signed)
    return resp


@router.post("/{participant_id}/input")
def input_form_submit(
    request: Request,
    participant_id: str,
    response: Response,
    raw_text: str = Form(""),
    consent_confirmed: str = Form("0"),
    csrf_token: str = Form(""),
):
    participant = _get_participant(request)
    if participant is None or participant.id != participant_id:
        return RedirectResponse(url="/p/access", status_code=303)

    if not _validate_csrf(request, csrf_token):
        context: dict[str, Any] = {
            "participant": participant,
            "error": "Invalid or expired form token. Please try again.",
            "success": None,
            "csrf_token": "",
            "raw_text": raw_text,
        }
        new_token, new_signed = _inject_csrf({})
        context["csrf_token"] = new_token
        resp = _render_template(request, "input_form.html", context)
        _set_cookie(resp, CSRF_COOKIE, new_signed)
        return resp

    raw_text = raw_text.strip()
    consent = 1 if consent_confirmed == "1" else 0

    if not raw_text:
        context = {
            "participant": participant,
            "error": "Please provide your input text.",
            "success": None,
            "csrf_token": "",
            "raw_text": raw_text,
        }
        new_token, new_signed = _inject_csrf({})
        context["csrf_token"] = new_token
        resp = _render_template(request, "input_form.html", context)
        _set_cookie(resp, CSRF_COOKIE, new_signed)
        return resp

    if consent != 1:
        context = {
            "participant": participant,
            "error": "You must confirm consent before submitting.",
            "success": None,
            "csrf_token": "",
            "raw_text": raw_text,
        }
        new_token, new_signed = _inject_csrf({})
        context["csrf_token"] = new_token
        resp = _render_template(request, "input_form.html", context)
        _set_cookie(resp, CSRF_COOKIE, new_signed)
        return resp

    conn = get_connection(request.app.state.db_path)
    try:
        input_record = input_repo.create_input(
            conn,
            participant_id=participant.id,
            raw_text=raw_text,
            consent_confirmed=consent,
        )
    except Exception:
        logger.exception("input submission failed")
        context = {
            "participant": participant,
            "error": "An error occurred while saving your input. Please try again.",
            "success": None,
            "csrf_token": "",
            "raw_text": raw_text,
        }
        new_token, new_signed = _inject_csrf({})
        context["csrf_token"] = new_token
        resp = _render_template(request, "input_form.html", context)
        _set_cookie(resp, CSRF_COOKIE, new_signed)
        return resp
    finally:
        conn.close()

    context = {
        "participant": participant,
        "error": None,
        "success": "Your input has been submitted successfully.",
        "csrf_token": "",
        "raw_text": "",
    }
    new_token, new_signed = _inject_csrf({})
    context["csrf_token"] = new_token
    resp = _render_template(request, "input_form.html", context)
    _set_cookie(resp, CSRF_COOKIE, new_signed)
    return resp


@router.get("/{participant_id}/history")
def participant_history(request: Request, participant_id: str):
    participant = _get_participant(request)
    if participant is None or participant.id != participant_id:
        return RedirectResponse(url="/p/access", status_code=303)

    conn = get_connection(request.app.state.db_path)
    try:
        editions = ed_repo.get_editions_by_participant(conn, participant.id)
        published = [
            e for e in editions
            if e.publication_state == "published"
        ]
        published.sort(key=lambda e: e.edition_number, reverse=True)
    finally:
        conn.close()

    context: dict[str, Any] = {
        "participant": participant,
        "editions": published,
    }
    return _render_template(request, "participant_history.html", context)


@router.get("/{participant_id}/editions/{edition_number}")
def edition_read_page(request: Request, participant_id: str, edition_number: int):
    participant = _get_participant(request)
    if participant is None or participant.id != participant_id:
        return RedirectResponse(url="/p/access", status_code=303)

    conn = get_connection(request.app.state.db_path)
    try:
        editions = ed_repo.get_editions_by_participant(conn, participant.id)
        target = None
        for e in editions:
            if (
                e.edition_number == edition_number
                and e.publication_state == "published"
                and e.structured_content
            ):
                target = e
                break

        if target is None:
            return _render_template(request, "not_found.html", {
                "participant": participant,
                "message": "Edition not found or not yet published.",
            })

        content = json.loads(target.structured_content)

        prior_feedback_summary = None
        if target.structured_content:
            try:
                parsed = json.loads(target.structured_content)
                af = parsed.get("applied_feedback")
                if af:
                    prior_feedback_summary = {
                        "action": af.get("action", ""),
                        "evidence": af.get("evidence", ""),
                        "affected_section_ids": af.get(
                            "affected_section_ids", []
                        ),
                    }
            except (json.JSONDecodeError, TypeError):
                pass

        feedbacks = fb_repo.get_feedback_by_edition(conn, target.id)
        has_given_feedback = len(feedbacks) > 0

        next_edition = None
        for e in editions:
            if (
                e.prior_edition_id == target.id
                and e.publication_state == "published"
            ):
                next_edition = e
                break

    finally:
        conn.close()

    context: dict[str, Any] = {
        "participant": participant,
        "edition": target,
        "content": content,
        "prior_feedback_summary": prior_feedback_summary,
        "has_given_feedback": has_given_feedback,
        "next_edition_number": (
            next_edition.edition_number if next_edition else None
        ),
    }
    return _render_template(request, "edition_read.html", context)


@router.get("/{participant_id}/editions/{edition_number}/feedback")
def feedback_form_page(request: Request, participant_id: str, edition_number: int):
    participant = _get_participant(request)
    if participant is None or participant.id != participant_id:
        return RedirectResponse(url="/p/access", status_code=303)

    conn = get_connection(request.app.state.db_path)
    try:
        editions = ed_repo.get_editions_by_participant(conn, participant.id)
        target = None
        for e in editions:
            if (
                e.edition_number == edition_number
                and e.publication_state == "published"
            ):
                target = e
                break

        if target is None:
            return _render_template(request, "not_found.html", {
                "participant": participant,
                "message": "Edition not found or not yet published.",
            })

        content = json.loads(target.structured_content) if target.structured_content else {}
        existing = fb_repo.get_feedback_by_edition(conn, target.id)
        already_submitted = len(existing) > 0
    finally:
        conn.close()

    if already_submitted:
        return _render_template(request, "feedback_thanks.html", {
            "participant": participant,
            "edition_number": edition_number,
        })

    context: dict[str, Any] = {
        "participant": participant,
        "edition": target,
        "content": content,
        "error": None,
        "csrf_token": "",
    }
    csrf_token, csrf_signed = _inject_csrf({})
    context["csrf_token"] = csrf_token
    resp = _render_template(request, "feedback_form.html", context)
    _set_cookie(resp, CSRF_COOKIE, csrf_signed)
    return resp


@router.post("/{participant_id}/editions/{edition_number}/feedback")
def feedback_form_submit(
    request: Request,
    participant_id: str,
    edition_number: int,
    response: Response,
    direction_choices: list[str] = Form([]),
    selected_section_id: str = Form(""),
    free_text: str = Form(""),
    csrf_token: str = Form(""),
):
    participant = _get_participant(request)
    if participant is None or participant.id != participant_id:
        return RedirectResponse(url="/p/access", status_code=303)

    if not _validate_csrf(request, csrf_token):
        context: dict[str, Any] = {
            "participant": participant,
            "edition": None,
            "content": {},
            "error": "Invalid or expired form token. Please try again.",
            "csrf_token": "",
        }
        new_token, new_signed = _inject_csrf({})
        context["csrf_token"] = new_token
        resp = _render_template(request, "feedback_form.html", context)
        _set_cookie(resp, CSRF_COOKIE, new_signed)
        return resp

    conn = get_connection(request.app.state.db_path)
    try:
        editions = ed_repo.get_editions_by_participant(conn, participant.id)
        target = None
        for e in editions:
            if (
                e.edition_number == edition_number
                and e.publication_state == "published"
            ):
                target = e
                break

        if target is None:
            return _render_template(request, "not_found.html", {
                "participant": participant,
                "message": "Edition not found or not yet published.",
            })

        existing = fb_repo.get_feedback_by_edition(conn, target.id)
        if len(existing) > 0:
            return _render_template(request, "feedback_thanks.html", {
                "participant": participant,
                "edition_number": edition_number,
            })

        if selected_section_id:
            valid_ids = _edition_section_ids(target)
            if valid_ids and selected_section_id not in valid_ids:
                content = json.loads(target.structured_content) if target.structured_content else {}
                context = {
                    "participant": participant,
                    "edition": target,
                    "content": content,
                    "error": "Selected section is not valid for this edition.",
                    "csrf_token": "",
                }
                new_token, new_signed = _inject_csrf({})
                context["csrf_token"] = new_token
                resp = _render_template(request, "feedback_form.html", context)
                _set_cookie(resp, CSRF_COOKIE, new_signed)
                return resp

        try:
            directions_json = json.dumps(direction_choices) if direction_choices else "[]"
            fb_repo.create_feedback(
                conn,
                participant_id=participant.id,
                edition_id=target.id,
                direction_choices=directions_json,
                selected_section_id=selected_section_id or None,
                free_text=free_text.strip() or None,
            )
        except Exception:
            logger.exception("feedback submission failed")
            content = json.loads(target.structured_content) if target.structured_content else {}
            context = {
                "participant": participant,
                "edition": target,
                "content": content,
                "error": "Feedback submission failed. Please try again.",
                "csrf_token": "",
            }
            new_token, new_signed = _inject_csrf({})
            context["csrf_token"] = new_token
            resp = _render_template(request, "feedback_form.html", context)
            _set_cookie(resp, CSRF_COOKIE, new_signed)
            return resp
    finally:
        conn.close()

    return _render_template(request, "feedback_thanks.html", {
        "participant": participant,
        "edition_number": edition_number,
    })


@router.post("/{participant_id}/logout")
def participant_logout(request: Request, participant_id: str):
    resp = RedirectResponse(url="/p/access", status_code=303)
    _delete_cookie(resp, SESSION_COOKIE)
    _delete_cookie(resp, CSRF_COOKIE)
    return resp
