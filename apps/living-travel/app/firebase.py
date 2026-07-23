"""Firebase ID token verification with dependency injection.

Firebase only proves *who* a user is (authentication). It never grants Living
Travel authorization by itself. Verification failures raise a generic
``InvalidTokenError`` and never log the raw token, claims, or certificate URLs.

The verifier is injectable so tests and CI run without live Firebase
credentials; ``FirebaseTokenVerifier`` lazily imports ``firebase_admin`` so the
module imports cleanly in SQLite/legacy mode without the SDK installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import get_settings

PROVIDER_FIREBASE = "firebase"


class InvalidTokenError(Exception):
    """Generic, secret-safe token verification failure."""


@dataclass(frozen=True)
class TokenClaims:
    provider: str
    subject: str  # verified uid/sub


class TokenVerifier(Protocol):
    def verify(self, token: str) -> TokenClaims:  # pragma: no cover - protocol
        ...


class FirebaseTokenVerifier:
    """Verifies Firebase ID tokens via the Admin SDK.

    Checks signature, issuer, audience/project, expiration, and uid/sub. When
    ``check_revoked`` is True it also rejects revoked sessions where practical.
    """

    def __init__(self, project_id: str, *, check_revoked: bool = True) -> None:
        self._project_id = project_id
        self._check_revoked = check_revoked
        self._app = None

    def _get_app(self):
        if self._app is None:
            try:
                import firebase_admin
            except ImportError as exc:  # noqa: BLE001
                raise InvalidTokenError("token verification unavailable") from exc
            options = {"projectId": self._project_id}
            try:
                import json
                import os

                sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
                if sa_json:
                    from firebase_admin import credentials

                    cred = credentials.Certificate(json.loads(sa_json))
                    self._app = firebase_admin.initialize_app(cred, options=options)
                else:
                    # Application Default Credentials (GOOGLE_APPLICATION_CREDENTIALS)
                    self._app = firebase_admin.initialize_app(options=options)
            except ValueError:
                self._app = firebase_admin.get_app()
        return self._app

    def verify(self, token: str) -> TokenClaims:
        if not token:
            raise InvalidTokenError("missing token")
        try:
            from firebase_admin import auth
        except ImportError as exc:  # noqa: BLE001
            raise InvalidTokenError("token verification unavailable") from exc
        try:
            decoded = auth.verify_id_token(
                token, app=self._get_app(), check_revoked=self._check_revoked
            )
        except Exception as exc:  # noqa: BLE001 - never leak details
            raise InvalidTokenError("invalid token") from exc
        subject = decoded.get("uid") or decoded.get("sub")
        if not subject:
            raise InvalidTokenError("invalid token")
        return TokenClaims(provider=PROVIDER_FIREBASE, subject=str(subject))


class FakeTokenVerifier:
    """Test double: maps known tokens to claims, else raises InvalidTokenError."""

    def __init__(self, tokens: dict[str, TokenClaims] | None = None) -> None:
        self._tokens = dict(tokens or {})

    def add(self, token: str, claims: TokenClaims) -> None:
        self._tokens[token] = claims

    def verify(self, token: str) -> TokenClaims:
        claims = self._tokens.get(token)
        if claims is None:
            raise InvalidTokenError("invalid token")
        return claims


_verifier: TokenVerifier | None = None


def set_token_verifier(verifier: TokenVerifier | None) -> None:
    global _verifier
    if verifier is not None and get_settings().environment != "testing":
        raise RuntimeError("token verifier injection is restricted to testing")
    _verifier = verifier


def reset_token_verifier() -> None:
    global _verifier
    _verifier = None


def get_token_verifier() -> TokenVerifier:
    """Return the configured verifier, building the Firebase one on demand."""
    global _verifier
    if _verifier is not None:
        return _verifier
    settings = get_settings()
    if settings.auth_mode != "firebase":
        raise InvalidTokenError("token verification disabled")
    if not settings.firebase_project_id:
        raise InvalidTokenError("token verification misconfigured")
    _verifier = FirebaseTokenVerifier(settings.firebase_project_id)
    return _verifier
