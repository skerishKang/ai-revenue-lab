"""Common API routes: health and current identity."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import external_identity_repository as eid_repo
from app.api.auth import get_verified_claims
from app.db import get_connection
from app.firebase import TokenClaims

router = APIRouter(tags=["common"])


@router.get("/health")
async def api_health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/me")
async def me(claims: TokenClaims = Depends(get_verified_claims)) -> dict:
    """Return the verified identity and its internal role mapping (if any)."""
    conn = get_connection()
    try:
        identity = eid_repo.get_identity(conn, claims.provider, claims.subject)
    finally:
        conn.close()

    role = "none"
    traveler_id = None
    if identity is not None and not identity.is_revoked:
        if identity.operator_id is not None:
            role = "operator"
        elif identity.traveler_id is not None:
            role = "traveler"
            traveler_id = identity.traveler_id
    return {
        "provider": claims.provider,
        "role": role,
        "traveler_id": traveler_id,
        "revoked": bool(identity.is_revoked) if identity is not None else False,
    }
