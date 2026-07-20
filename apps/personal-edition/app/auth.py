"""Session-based authentication for participant and admin access.

Uses itsdangerous for signed cookies to avoid server-side session storage.
Raw tokens are never stored in sessions — only participant_id or admin role.

Purpose-separated salts prevent cross-context token reuse:
- participant sessions use salt "participant-session"
- admin sessions use salt "admin-session"
- CSRF tokens use salt "csrf-token"
"""

from __future__ import annotations

import secrets
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

_PARTICIPANT_SESSION_KEY = "participant_id"
_ADMIN_SESSION_KEY = "is_admin"

_SESSION_SALT = "participant-session"
_ADMIN_SESSION_SALT = "admin-session"
_CSRF_SALT = "csrf-token"


def _get_session_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=_SESSION_SALT)


def _get_admin_session_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=_ADMIN_SESSION_SALT)


def _get_csrf_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=_CSRF_SALT)


def create_participant_session(participant_id: str) -> dict[str, Any]:
    return {_PARTICIPANT_SESSION_KEY: participant_id}


def create_admin_session() -> dict[str, Any]:
    return {_ADMIN_SESSION_KEY: True}


def decode_session_token(token: str) -> dict[str, Any] | None:
    """Decode a signed participant session token. Returns None on invalid/expired."""
    try:
        serializer = _get_session_serializer()
        data = serializer.loads(
            token,
            max_age=settings.session_max_age_seconds,
        )
        if not isinstance(data, dict):
            return None
        return data
    except (BadSignature, SignatureExpired, ValueError):
        return None


def decode_admin_session_token(token: str) -> dict[str, Any] | None:
    """Decode a signed admin session token. Returns None on invalid/expired."""
    try:
        serializer = _get_admin_session_serializer()
        data = serializer.loads(
            token,
            max_age=settings.session_max_age_seconds,
        )
        if not isinstance(data, dict):
            return None
        return data
    except (BadSignature, SignatureExpired, ValueError):
        return None


def sign_session_token(data: dict[str, Any]) -> str:
    """Sign participant session data into a URL-safe token."""
    serializer = _get_session_serializer()
    return serializer.dumps(data)


def sign_admin_session_token(data: dict[str, Any]) -> str:
    """Sign admin session data into a URL-safe token."""
    serializer = _get_admin_session_serializer()
    return serializer.dumps(data)


def get_participant_id_from_session(session_data: dict[str, Any]) -> str | None:
    """Extract participant_id from decoded session data."""
    if not isinstance(session_data, dict):
        return None
    pid = session_data.get(_PARTICIPANT_SESSION_KEY)
    if isinstance(pid, str) and pid:
        return pid
    return None


def is_admin_session(session_data: dict[str, Any]) -> bool:
    """Check if session data represents an admin session."""
    if not isinstance(session_data, dict):
        return False
    return session_data.get(_ADMIN_SESSION_KEY) is True


def verify_admin_secret(candidate: str) -> bool:
    """Constant-time comparison of admin secret."""
    return secrets.compare_digest(candidate, settings.admin_secret)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def sign_csrf_token(csrf_token: str) -> str:
    serializer = _get_csrf_serializer()
    return serializer.dumps(csrf_token)


def verify_csrf_token(csrf_token: str, signed_token: str) -> bool:
    """Verify a CSRF token against its signed counterpart."""
    try:
        serializer = _get_csrf_serializer()
        expected = serializer.loads(
            signed_token,
            max_age=settings.session_max_age_seconds,
        )
        if not isinstance(expected, str):
            return False
        return secrets.compare_digest(csrf_token, expected)
    except (BadSignature, SignatureExpired, ValueError):
        return False
