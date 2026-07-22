"""Authentication dependencies for Living Travel web routes.

Provides FastAPI dependencies for operator and traveler auth.
All auth uses constant-time comparison and one-way token hashes.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, HTTPException, Request

from app.db import get_connection
from app.security import (
    validate_operator_session,
    validate_traveler_session,
    constant_time_compare,
)


@dataclass(frozen=True)
class OperatorContext:
    session_id: str
    csrf_token: str


@dataclass(frozen=True)
class TravelerContext:
    session_id: str
    traveler_id: str
    csrf_token: str


def _get_cookie(request: Request, name: str) -> str:
    val = request.cookies.get(name, "")
    return val if val else ""


def get_operator(request: Request) -> OperatorContext:
    """FastAPI dependency: extract and validate operator session.

    Raises 307 redirect to /operator/login if not authenticated.
    """
    raw_token = _get_cookie(request, "lt_operator_session")
    conn = get_connection()
    try:
        session = validate_operator_session(conn, raw_token)
    finally:
        conn.close()
    if session is None:
        raise HTTPException(
            status_code=307,
            headers={"Location": "/operator/login"},
        )
    return OperatorContext(
        session_id=session["session_id"],
        csrf_token=session["csrf_token"],
    )


def get_traveler(request: Request) -> TravelerContext:
    """FastAPI dependency: extract and validate traveler session.

    Raises 307 redirect to /traveler/enter if not authenticated.
    """
    raw_token = _get_cookie(request, "lt_traveler_session")
    conn = get_connection()
    try:
        session = validate_traveler_session(conn, raw_token)
    finally:
        conn.close()
    if session is None:
        raise HTTPException(
            status_code=307,
            headers={"Location": "/traveler/enter"},
        )
    return TravelerContext(
        session_id=session["session_id"],
        traveler_id=session["traveler_id"],
        csrf_token=session["csrf_token"],
    )


def verify_csrf(request: Request, csrf_token: str, session: OperatorContext | TravelerContext) -> None:
    """Verify CSRF token from form matches the session CSRF token.

    Raises 403 if tokens don't match.
    """
    if not csrf_token or not session.csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if not constant_time_compare(csrf_token, session.csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
