"""Authentication and authorization dependencies for the /api/v1 boundary.

Authorization model (never trust the IdP alone):

    verified identity (IdentityVerifier)
    + active external_identities row
    + active product_memberships row with the correct role
    + resource ownership
    => access

All failures collapse to generic ``401 unauthorized`` / ``403 forbidden`` so no
reason, subject, or token detail leaks. The verified ``subject`` is never used
as a learner id; the learner id comes from the product membership.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, status

from app.identity import (
    FIREBASE_ISSUER,
    IdentityPrincipal,
    InvalidTokenError,
    get_identity_verifier,
)
from app.repositories.identity_repository import (
    ROLE_LEARNER,
    ROLE_OPERATOR,
    ROLE_REVIEWER,
    get_external_identity,
    get_memberships_for_identity,
)

PROVIDER_FIREBASE = "firebase"


@dataclass(frozen=True)
class Principal:
    """An authenticated, product-local principal."""

    issuer: str
    subject: str
    email: str | None
    external_identity_id: str
    roles: frozenset = field(default_factory=frozenset)
    learner_id: str | None = None

    @property
    def is_learner(self) -> bool:
        return ROLE_LEARNER in self.roles

    @property
    def is_operator(self) -> bool:
        return ROLE_OPERATOR in self.roles

    @property
    def is_reviewer(self) -> bool:
        return ROLE_REVIEWER in self.roles


def _extract_bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    token = header[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    return token


def get_verified_identity(request: Request) -> IdentityPrincipal:
    token = _extract_bearer(request)
    try:
        return get_identity_verifier().verify_bearer_token(token)
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def _get_conn(request: Request):
    if not hasattr(request.app.state, "get_connection"):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="unavailable")
    return request.app.state.get_connection()


def get_principal(request: Request) -> Principal:
    """Resolve a verified identity into a product-local principal.

    Fail-closed: a verified identity with no active external identity row, or no
    active membership, is rejected. Firebase authentication alone grants nothing.
    """
    identity_principal = get_verified_identity(request)
    conn = _get_conn(request)
    try:
        identity = get_external_identity(
            conn, PROVIDER_FIREBASE, identity_principal.issuer, identity_principal.subject
        )
        if identity is None or not identity.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

        memberships = get_memberships_for_identity(conn, identity.id)
        active = [m for m in memberships if m.is_active]
        if not active:
            # Verified identity but no active product membership => no access.
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
        roles = frozenset(m.role for m in active)
        learner_id = next((m.learner_id for m in active if m.learner_id), None)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return Principal(
        issuer=identity_principal.issuer,
        subject=identity_principal.subject,
        email=identity_principal.email,
        external_identity_id=identity.id,
        roles=roles,
        learner_id=learner_id,
    )


def require_learner(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_learner or not principal.learner_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return principal


def require_operator(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_operator:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return principal


def require_reviewer(principal: Principal = Depends(get_principal)) -> Principal:
    if not (principal.is_reviewer or principal.is_operator):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return principal
