"""Traveler web routes for Living Travel Phase 2."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import TravelerContext, get_traveler, verify_csrf
from app.security import constant_time_compare
from app.db import get_connection
from app.edition_repository import get_edition_by_id, get_editions_by_traveler
from app.feedback_repository import create_feedback, get_feedback_by_edition
from app.security import (
    create_traveler_session,
    invalidate_traveler_session,
    validate_traveler_token,
    validate_traveler_session,
    generate_csrf_token,
)
from app.traveler_repository import get_traveler_by_id, update_traveler_preferences
from app.web.templates import render_template

router = APIRouter(prefix="/traveler", tags=["traveler"])


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
        return HTMLResponse(render_template("traveler_enter.html", {"csrf_token": generate_csrf_token(), "error": "Invalid CSRF token"}))
    conn = get_connection()
    try:
        traveler_id = validate_traveler_token(conn, token.strip())
        if not traveler_id:
            return HTMLResponse(render_template("traveler_enter.html", {"csrf_token": generate_csrf_token(), "error": "Invalid or deactivated token"}))
        session_id, raw_token, csrf = create_traveler_session(conn, traveler_id)
    finally:
        conn.close()
    resp = RedirectResponse(url="/traveler/", status_code=303)
    resp.set_cookie("lt_traveler_session", raw_token, httponly=True, samesite="strict", max_age=86400)
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
    conn = get_connection()
    try:
        traveler = get_traveler_by_id(conn, traveler_ctx.traveler_id)
        if not traveler or traveler.status != "active":
            return HTMLResponse(render_template("404.html", {}), status_code=404)
        editions = get_editions_by_traveler(conn, traveler_ctx.traveler_id)
        published = [e for e in editions if e.publication_state == "published"]
        latest = published[-1] if published else None
        return HTMLResponse(render_template("traveler_dashboard.html", {
            "traveler": traveler,
            "latest_edition": latest,
            "published_count": len(published),
            "csrf_token": traveler_ctx.csrf_token,
        }))
    finally:
        conn.close()


@router.post("/preferences")
async def update_preferences(
    request: Request,
    destination: str = Form(None),
    trip_duration_nights: int = Form(None),
    interests: str = Form(""),
    csrf_token: str = Form(...),
    traveler_ctx: TravelerContext = __import__("fastapi").Depends(get_traveler),
):
    verify_csrf(request, csrf_token, traveler_ctx)
    conn = get_connection()
    try:
        interest_list = [i.strip() for i in interests.split(",") if i.strip()] if interests else None
        update_traveler_preferences(
            conn, traveler_ctx.traveler_id,
            destination=destination if destination else None,
            trip_duration_nights=trip_duration_nights,
            interests=interest_list,
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
            "mode": "history",
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
        return HTMLResponse(render_template("traveler_edition.html", {
            "edition": edition,
            "feedback": feedback_list,
            "mode": "single",
            "csrf_token": traveler_ctx.csrf_token,
        }))
    finally:
        conn.close()


@router.post("/editions/{edition_id}/feedback")
async def submit_feedback(
    edition_id: str,
    request: Request,
    choices: str = Form(""),
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
        choice_list = [c.strip() for c in choices.split(",") if c.strip()] if choices else []
        create_feedback(
            conn,
            traveler_id=traveler_ctx.traveler_id,
            edition_id=edition_id,
            choices=choice_list,
            free_text=free_text[:500] if free_text else "",
        )
    finally:
        conn.close()
    return RedirectResponse(url=f"/traveler/editions/{edition_id}", status_code=303)
