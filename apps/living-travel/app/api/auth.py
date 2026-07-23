"""API authentication and authorization dependencies.

Authentication uses a verified Firebase ID token (Bearer). The client-supplied
UID is never trusted; only the verified token ``uid/sub`` is used. Authorization
(traveler/operator, data ownership) comes from the Living Travel
``external_identities`` mapping — never from Firebase account existence.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app import external_identity_repository as eid_repo
from app.db import get_connection
from app.firebase import InvalidTokenError, TokenClaims, get_token_verifier


@dataclass(frozen=True)
class Principal:
    provider: str
    subject: str
    traveler_id: str | None
    operator_id: str | None

    @property
    def is_operator(self) -> bool:
        return self.operator_id is not None

    @property
    def is_traveler(self) -> bool:
        return self.traveler_id is not None


def _extract_bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    token = header[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="unauthorized")
    return token


def get_verified_claims(request: Request) -> TokenClaims:
    """Verify the bearer token and return its claims (no mapping required)."""
    token = _extract_bearer(request)
    try:
        return get_token_verifier().verify(token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="unauthorized")


def get_principal(request: Request) -> Principal:
    """Verify the token and resolve a mapped, non-revoked internal principal."""
    claims = get_verified_claims(request)
    conn = get_connection()
    try:
        identity = eid_repo.get_identity(conn, claims.provider, claims.subject)
    finally:
        conn.close()
    if identity is None or identity.is_revoked:
        raise HTTPException(status_code=401, detail="unauthorized")
    return Principal(
        provider=claims.provider,
        subject=claims.subject,
        traveler_id=identity.traveler_id,
        operator_id=identity.operator_id,
    )


def require_traveler(
    principal: Principal = Depends(get_principal),
) -> Principal:
    if not principal.is_traveler:
        raise HTTPException(status_code=403, detail="forbidden")
    from app.traveler_repository import is_traveler_active

    conn = get_connection()
    try:
        if not is_traveler_active(conn, principal.traveler_id):  # type: ignore[arg-type]
            raise HTTPException(status_code=401, detail="unauthorized")
    finally:
        conn.close()
    return principal


def require_operator(
    principal: Principal = Depends(get_principal),
) -> Principal:
    if not principal.is_operator:
        raise HTTPException(status_code=403, detail="forbidden")
    return principal
