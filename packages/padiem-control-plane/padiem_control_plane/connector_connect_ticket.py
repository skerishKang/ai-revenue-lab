"""Short-lived server-trusted connector onboarding tickets.

The browser is never authoritative for actor/account/workspace identity. A
trusted Control Plane caller first resolves an active canonical auth session,
then issues this bounded ticket for one reviewed connector/scope set. Product
connector ingress may verify the signature and exact claims, but the ticket is
not a replacement for the canonical auth-session authority.

The encoded ticket is a credential: never log it, persist it as public model
context, or put it in a query string. Only safe projections are exposed here.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
from typing import Any

from .auth_sessions import AuthSessionSnapshot
from .contracts import ControlPlaneContractError


CONNECT_TICKET_VERSION = "v1"
CONNECT_TICKET_AUDIENCE = "padiem-claw-google-oauth"
MAX_CONNECT_TICKET_TTL_SECONDS = 300
MAX_CLOCK_SKEW_SECONDS = 30
MAX_CANONICAL_SUBJECT_ID_CHARS = 256
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_REVIEWED_SCOPES: dict[str, tuple[str, ...]] = {
    "gmail": (GMAIL_READONLY_SCOPE,),
    "google-drive": (GOOGLE_DRIVE_READONLY_SCOPE,),
}
_REQUIRED_WIRE_KEYS = frozenset(
    {
        "version",
        "audience",
        "ticket_id",
        "session_id",
        "product_id",
        "subject_type",
        "subject_id",
        "connector_id",
        "actor_ref",
        "account_ref",
        "workspace_ref",
        "scopes",
        "issued_at",
        "expires_at",
    }
)


def _safe_ref(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise ControlPlaneContractError("invalid_connect_ticket", f"{name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise ControlPlaneContractError(
            "invalid_connect_ticket",
            f"{name} must be a bounded safe reference",
        )
    return normalized


def _canonical_subject_id(value: str) -> str:
    """Mirror CanonicalSubjectRef's bounded opaque-id semantics.

    Canonical subjects may legitimately contain Unicode or spaces. Tightening
    them to the connector's ASCII safe-ref grammar would create a second,
    incompatible identity authority at the connector boundary.
    """

    if not isinstance(value, str):
        raise ControlPlaneContractError(
            "invalid_connect_ticket",
            "subject_id must be a string",
        )
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_CANONICAL_SUBJECT_ID_CHARS
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        raise ControlPlaneContractError(
            "invalid_connect_ticket",
            "subject_id must be a bounded non-empty opaque identifier",
        )
    return normalized


def _aware(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_connect_ticket",
            f"{name} must be timezone-aware",
        )
    return value.astimezone(timezone.utc)


def _epoch_datetime(name: str, value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ControlPlaneContractError(
            "invalid_connect_ticket",
            f"{name} must be a non-negative integer epoch timestamp",
        )
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise ControlPlaneContractError(
            "invalid_connect_ticket",
            f"{name} is outside the supported timestamp range",
        ) from exc


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 16_384:
        raise ControlPlaneContractError("invalid_connect_ticket", "ticket segment is invalid")
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ControlPlaneContractError("invalid_connect_ticket", "ticket segment is invalid") from exc


def _reviewed_scopes(connector_id: str, scopes: tuple[str, ...]) -> tuple[str, ...]:
    connector_id = _safe_ref("connector_id", connector_id)
    if not isinstance(scopes, tuple) or not scopes or any(not isinstance(scope, str) for scope in scopes):
        raise ControlPlaneContractError("invalid_connect_ticket", "scopes must be a non-empty tuple")
    if len(set(scopes)) != len(scopes):
        raise ControlPlaneContractError("invalid_connect_ticket", "scopes must be unique")
    expected = _REVIEWED_SCOPES.get(connector_id)
    if expected is None or set(scopes) != set(expected):
        raise ControlPlaneContractError(
            "unreviewed_connect_scope",
            "connector ticket scopes must exactly match the reviewed readonly set",
        )
    return expected


@dataclass(frozen=True, slots=True)
class ConnectorConnectTicketClaims:
    ticket_id: str
    session_id: str
    product_id: str
    subject_type: str
    subject_id: str
    connector_id: str
    actor_ref: str
    account_ref: str
    workspace_ref: str
    scopes: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    audience: str = CONNECT_TICKET_AUDIENCE
    version: str = CONNECT_TICKET_VERSION

    def __post_init__(self) -> None:
        for name in (
            "ticket_id",
            "session_id",
            "product_id",
            "subject_type",
            "connector_id",
            "actor_ref",
            "account_ref",
            "workspace_ref",
        ):
            object.__setattr__(self, name, _safe_ref(name, getattr(self, name)))
        object.__setattr__(self, "subject_id", _canonical_subject_id(self.subject_id))
        if self.version != CONNECT_TICKET_VERSION:
            raise ControlPlaneContractError("invalid_connect_ticket", "unsupported ticket version")
        if self.audience != CONNECT_TICKET_AUDIENCE:
            raise ControlPlaneContractError("invalid_connect_ticket", "unexpected ticket audience")
        object.__setattr__(
            self,
            "scopes",
            _reviewed_scopes(self.connector_id, self.scopes),
        )
        issued_at = _aware("issued_at", self.issued_at)
        expires_at = _aware("expires_at", self.expires_at)
        if not issued_at < expires_at <= issued_at + timedelta(seconds=MAX_CONNECT_TICKET_TTL_SECONDS):
            raise ControlPlaneContractError(
                "invalid_connect_ticket",
                "ticket expiry exceeds the trusted bound",
            )
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)

    def to_wire_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "audience": self.audience,
            "ticket_id": self.ticket_id,
            "session_id": self.session_id,
            "product_id": self.product_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "connector_id": self.connector_id,
            "actor_ref": self.actor_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "scopes": list(self.scopes),
            "issued_at": int(self.issued_at.timestamp()),
            "expires_at": int(self.expires_at.timestamp()),
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "session_id": self.session_id,
            "product_id": self.product_id,
            "connector_id": self.connector_id,
            "actor_ref": self.actor_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "scopes": list(self.scopes),
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "audience": self.audience,
            "raw_ticket": False,
            "raw_signature": False,
            "raw_secret": False,
        }


class ConnectorConnectTicketAuthority:
    """HMAC authority for short-lived connector tickets.

    Replay consumption is intentionally delegated to the ingress durable store;
    signature verification alone must never be presented as replay prevention.
    """

    def __init__(self, *, signing_key: bytes) -> None:
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise ControlPlaneContractError(
                "invalid_connect_ticket_authority",
                "signing_key must contain at least 32 bytes",
            )
        self._signing_key = signing_key

    def issue(
        self,
        *,
        auth_session: AuthSessionSnapshot,
        ticket_id: str,
        connector_id: str,
        actor_ref: str,
        account_ref: str,
        workspace_ref: str,
        scopes: tuple[str, ...],
        now: datetime,
        ttl_seconds: int = MAX_CONNECT_TICKET_TTL_SECONDS,
    ) -> str:
        now = _aware("now", now)
        if not isinstance(auth_session, AuthSessionSnapshot):
            raise ControlPlaneContractError(
                "invalid_connect_ticket",
                "auth_session must be an AuthSessionSnapshot",
            )
        if not auth_session.is_active(now=now):
            raise ControlPlaneContractError(
                "inactive_auth_session",
                "connector tickets require an active canonical auth session",
            )
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or not 1 <= ttl_seconds <= MAX_CONNECT_TICKET_TTL_SECONDS
        ):
            raise ControlPlaneContractError(
                "invalid_connect_ticket",
                "ttl_seconds is outside the trusted bound",
            )
        subject_public = auth_session.subject.to_public_dict()
        claims = ConnectorConnectTicketClaims(
            ticket_id=ticket_id,
            session_id=auth_session.session_id,
            product_id=auth_session.product_id,
            subject_type=subject_public["subject_type"],
            subject_id=subject_public["subject_id"],
            connector_id=connector_id,
            actor_ref=actor_ref,
            account_ref=account_ref,
            workspace_ref=workspace_ref,
            scopes=scopes,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        payload = json.dumps(
            claims.to_wire_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        encoded_payload = _b64url_encode(payload)
        signing_input = f"{CONNECT_TICKET_VERSION}.{encoded_payload}".encode("ascii")
        signature = hmac.new(self._signing_key, signing_input, hashlib.sha256).digest()
        return f"{CONNECT_TICKET_VERSION}.{encoded_payload}.{_b64url_encode(signature)}"

    def verify(
        self,
        *,
        token: str,
        now: datetime,
        expected_connector_id: str | None = None,
        auth_session: AuthSessionSnapshot | None = None,
    ) -> ConnectorConnectTicketClaims:
        now = _aware("now", now)
        if not isinstance(token, str) or len(token) > 24_576:
            raise ControlPlaneContractError("invalid_connect_ticket", "connector ticket is invalid")
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != CONNECT_TICKET_VERSION:
            raise ControlPlaneContractError("invalid_connect_ticket", "connector ticket is invalid")
        _, encoded_payload, encoded_signature = parts
        signature = _b64url_decode(encoded_signature)
        signing_input = f"{CONNECT_TICKET_VERSION}.{encoded_payload}".encode("ascii")
        expected_signature = hmac.new(self._signing_key, signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ControlPlaneContractError("invalid_connect_ticket", "connector ticket signature is invalid")
        try:
            wire = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ControlPlaneContractError("invalid_connect_ticket", "connector ticket payload is invalid") from exc
        if not isinstance(wire, dict) or set(wire) != _REQUIRED_WIRE_KEYS:
            raise ControlPlaneContractError("invalid_connect_ticket", "connector ticket payload is not closed")
        try:
            scopes = tuple(wire["scopes"])
        except TypeError as exc:
            raise ControlPlaneContractError("invalid_connect_ticket", "connector ticket scopes are invalid") from exc
        claims = ConnectorConnectTicketClaims(
            ticket_id=wire["ticket_id"],
            session_id=wire["session_id"],
            product_id=wire["product_id"],
            subject_type=wire["subject_type"],
            subject_id=wire["subject_id"],
            connector_id=wire["connector_id"],
            actor_ref=wire["actor_ref"],
            account_ref=wire["account_ref"],
            workspace_ref=wire["workspace_ref"],
            scopes=scopes,
            issued_at=_epoch_datetime("issued_at", wire["issued_at"]),
            expires_at=_epoch_datetime("expires_at", wire["expires_at"]),
            audience=wire["audience"],
            version=wire["version"],
        )
        if claims.issued_at > now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
            raise ControlPlaneContractError("invalid_connect_ticket", "connector ticket is not yet valid")
        if now >= claims.expires_at:
            raise ControlPlaneContractError("expired_connect_ticket", "connector ticket has expired")
        if (
            expected_connector_id is not None
            and claims.connector_id != _safe_ref("expected_connector_id", expected_connector_id)
        ):
            raise ControlPlaneContractError(
                "connector_ticket_mismatch",
                "connector ticket targets another connector",
            )
        if auth_session is not None:
            if not isinstance(auth_session, AuthSessionSnapshot) or not auth_session.is_active(now=now):
                raise ControlPlaneContractError(
                    "inactive_auth_session",
                    "canonical auth session is not active",
                )
            subject = auth_session.subject.to_public_dict()
            if (
                claims.session_id != auth_session.session_id
                or claims.product_id != auth_session.product_id
                or claims.subject_type != subject["subject_type"]
                or claims.subject_id != subject["subject_id"]
            ):
                raise ControlPlaneContractError(
                    "connector_ticket_session_mismatch",
                    "ticket does not match the canonical auth session",
                )
        return claims


TRUSTED_CONNECT_TICKET_CONTRACT = True
SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY = False
CONNECT_TICKET_MAX_TTL_SECONDS = MAX_CONNECT_TICKET_TTL_SECONDS
CONNECT_TICKET_REPLAY_STORE_REQUIRED = True
RAW_CONNECT_TICKET_PUBLIC = False
