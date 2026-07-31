"""Portal-ready identity boundary for Living Learning.

Firebase (or any external IdP) proves *who* a caller is — authentication only.
Authorization never comes from the IdP: a verified identity must additionally
have an active ``external_identities`` row, an active ``product_memberships``
row with the correct role, and resource ownership before any access is granted.

This module is network-free. The real Firebase verifier lives behind the same
``IdentityVerifier`` protocol and is only wired in production; tests and local
runs use ``FakeIdentityVerifier`` / ``RejectingIdentityVerifier``. No Firebase
SDK is imported here, so the module imports cleanly without any cloud
dependency.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

# The shared identity provider project name (documented contract; no secret).
FIREBASE_ISSUER = "ai-revenue-lab-identity"


class InvalidTokenError(Exception):
    """Generic, secret-safe token verification failure.

    Deliberately carries no detail: raw tokens, subjects, and claims must never
    leak into logs or error responses.
    """


class IdentityPrincipal(BaseModel):
    """A verified identity, decoupled from any product-local identifier.

    The ``subject`` is the IdP's stable user id. It is NEVER used directly as a
    learner id; product-local identity is resolved through ``external_identities``
    and ``product_memberships``.
    """

    issuer: str
    subject: str
    email: str | None = None
    email_verified: bool = False
    claims: dict[str, object] = Field(default_factory=dict)


@runtime_checkable
class IdentityVerifier(Protocol):
    """Verifies a bearer token into an ``IdentityPrincipal``.

    Implementations must raise ``InvalidTokenError`` on any failure and must not
    log the token or its claims.
    """

    def verify_bearer_token(self, token: str) -> IdentityPrincipal:  # pragma: no cover
        ...


class FakeIdentityVerifier:
    """Network-free verifier mapping known tokens to principals.

    Any token not explicitly registered is rejected — an empty
    ``FakeIdentityVerifier()`` rejects everything (fail-closed).
    """

    def __init__(self, tokens: dict[str, IdentityPrincipal] | None = None) -> None:
        self._tokens: dict[str, IdentityPrincipal] = dict(tokens or {})

    def add(self, token: str, principal: IdentityPrincipal) -> None:
        self._tokens[token] = principal

    def verify_bearer_token(self, token: str) -> IdentityPrincipal:
        principal = self._tokens.get(token)
        if principal is None:
            raise InvalidTokenError("invalid token")
        return principal


class RejectingIdentityVerifier:
    """Verifier that rejects every token — the safe default when auth is unset."""

    def verify_bearer_token(self, token: str) -> IdentityPrincipal:
        raise InvalidTokenError("invalid token")


# ---------------------------------------------------------------------------
# Module-level verifier registry (dependency-injection seam).
# Tests inject a FakeIdentityVerifier; production wires the Firebase verifier.
# Fail-closed: until a verifier is configured, every token is rejected.
# ---------------------------------------------------------------------------
_verifier: IdentityVerifier | None = None


def set_identity_verifier(verifier: IdentityVerifier | None) -> None:
    global _verifier
    _verifier = verifier


def reset_identity_verifier() -> None:
    global _verifier
    _verifier = None


def get_identity_verifier() -> IdentityVerifier:
    """Return the configured verifier, or a rejecting one if none is set."""
    if _verifier is None:
        return RejectingIdentityVerifier()
    return _verifier
