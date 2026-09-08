"""Per-request CP auth-session scope authority seam for #2168 S3b.

The caller-static ``TrustedCallerScopeAuthority.scope_for_caller`` protocol
(#2157) cannot express per-request tenant/subject scope. This module adds the
smallest Engine-only injectable seam that mints the bounded
``TrustedCallerScope`` triple ``(app_id, tenant_id, subject_id)`` for one
authenticated request:

* ``app_id`` comes only from the authenticated Engine caller/app authority;
* ``auth_session_id`` is an opaque server-resolved clue for one request — the
  seam never accepts raw tenant or subject assertions from request content;
* ``subject_id`` and ``tenant_id`` come only from the canonical Control Plane
  auth-session resolution boundary reached through the injected
  ``ControlPlaneAuthSessionClient`` port. The Engine stores no session truth
  and derives no identity locally; the port mirrors the canonical
  ``resolve_auth_session`` RPC and its public-dict wire shape;
* ``tenant_id`` is the optional #2159 fact: it must be present, distinct from
  ``product_id`` and the subject id, and never defaults or aliases. While the
  CP has no tenant producer the seam fails closed with a 503;
* missing/unresolvable/inactive sessions, malformed payloads and cross-app
  session bindings all fail closed with bounded safe messages that never
  reflect session internals to the wire.

Source wiring only: no factory, D1 binding, admission/upload, manifest or
Production composition is introduced here, and no existing fail-closed caller
changes behaviour.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import inspect
import re
from typing import Any, Protocol

from app.document_context_service import (
    DocumentAuthorityError,
    TrustedCallerScope,
)

# Mirrors the canonical CP auth-session public-dict contract (#2159):
# closed key set, with ``tenant_id`` present only when the session carries
# the optional tenancy fact.
_SESSION_KEYS = frozenset(
    {
        "session_id",
        "product_id",
        "subject",
        "issued_at",
        "expires_at",
        "state",
        "revision",
    }
)
_SUBJECT_KEYS = frozenset({"subject_type", "subject_id"})
_SUBJECT_TYPES = frozenset({"anonymous", "user", "account"})
_SESSION_STATES = frozenset({"active", "revoked", "expired"})

# Bounded safe identifier grammar shared with the Engine trust boundary.
_BOUNDED_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_MAX_OPAQUE_CHARS = 256


class ControlPlaneAuthSessionClient(Protocol):
    """Injected client for the canonical CP auth-session resolution RPC.

    Implementations call the Control Plane-owned ``resolve_auth_session``
    boundary and return its public-dict view (or ``None`` when the session
    does not exist). The Engine never interprets or persists session state
    beyond deriving this one request's scope.
    """

    def resolve_auth_session(self, *, session_id: str) -> Any: ...


def _unavailable(message: str) -> DocumentAuthorityError:
    return DocumentAuthorityError(
        "auth_session_unavailable", message, status_code=503
    )


def _inactive() -> DocumentAuthorityError:
    return DocumentAuthorityError(
        "auth_session_inactive",
        "Control Plane auth session is not active.",
        status_code=403,
    )


def _mismatch() -> DocumentAuthorityError:
    return DocumentAuthorityError(
        "auth_scope_mismatch",
        "Control Plane auth session does not match this request.",
        status_code=403,
    )


def _tenant_unavailable(
    message: str = "Canonical tenant scope is unavailable for this session.",
) -> DocumentAuthorityError:
    return DocumentAuthorityError("tenant_unavailable", message, status_code=503)


def _bounded_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _BOUNDED_ID_RE.fullmatch(value):
        raise _unavailable(f"{name} must be a bounded safe identifier.")
    return value


def _opaque(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise _unavailable(f"{name} must be a string.")
    if not value or len(value) > _MAX_OPAQUE_CHARS or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    ):
        raise _unavailable(f"{name} must be a bounded opaque identifier.")
    return value


def _closed(payload: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise _unavailable(f"{label} payload is invalid.")
    if frozenset(payload.keys()) != expected:
        raise _unavailable(f"{label} schema mismatch.")
    return dict(payload)


def _timestamp(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise _unavailable(f"{name} must be valid ISO-8601 text.") from exc
    else:
        raise _unavailable(f"{name} must be a timestamp.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _unavailable(f"{name} must be timezone-aware.")
    return parsed


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuthSessionScopeAuthority:
    """Deployment-owned per-request scope authority over the CP session port.

    ``scope_for_request`` accepts only the authenticated caller's bound
    ``app_id`` and an opaque ``auth_session_id`` clue. Every returned scope
    field is derived from the resolved Control Plane session; request content
    can never assert tenant or subject, and an absent tenant never defaults.
    """

    def __init__(
        self,
        *,
        session_client: ControlPlaneAuthSessionClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(getattr(session_client, "resolve_auth_session", None)):
            raise ValueError("session_client must expose resolve_auth_session")
        self._session_client = session_client
        self._clock = clock if clock is not None else _utc_now

    async def scope_for_request(
        self, *, app_id: str, auth_session_id: str
    ) -> TrustedCallerScope:
        app_id = _bounded_id(app_id, "app_id")
        auth_session_id = _bounded_id(auth_session_id, "auth_session_id")

        try:
            payload = await _maybe_await(
                self._session_client.resolve_auth_session(
                    session_id=auth_session_id
                )
            )
        except DocumentAuthorityError:
            raise
        except Exception:
            # The CP client is the trusted boundary; transport or upstream
            # failures never reflect session internals to the wire.
            raise _unavailable(
                "Control Plane auth session resolution failed."
            ) from None
        if payload is None:
            raise _unavailable("Control Plane auth session was not found.")
        if not isinstance(payload, Mapping):
            raise _unavailable("auth session payload is invalid.")

        session = _closed(
            payload,
            _SESSION_KEYS
            if "tenant_id" not in payload
            else _SESSION_KEYS | {"tenant_id"},
            "auth session",
        )
        session_id = _bounded_id(session["session_id"], "session_id")
        product_id = _bounded_id(session["product_id"], "product_id")
        state = session["state"]
        if not isinstance(state, str) or state not in _SESSION_STATES:
            raise _unavailable("auth session state is invalid.")
        revision = session["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise _unavailable("auth session revision is invalid.")
        issued_at = _timestamp(session["issued_at"], "issued_at")
        expires_at = _timestamp(session["expires_at"], "expires_at")
        if expires_at <= issued_at:
            raise _unavailable("auth session expiry is not after issuance.")

        subject = _closed(session["subject"], _SUBJECT_KEYS, "auth session subject")
        subject_type = subject["subject_type"]
        if subject_type not in _SUBJECT_TYPES:
            raise _unavailable("auth session subject_type is invalid.")
        subject_id = _opaque(subject["subject_id"], "auth session subject_id")

        if session_id != auth_session_id:
            raise _mismatch()
        if product_id != app_id:
            raise _mismatch()
        now = self._clock()
        if state != "active" or now >= expires_at:
            raise _inactive()

        if "tenant_id" not in session or session["tenant_id"] is None:
            # #2159 locked semantics: no default, no alias, no fallback.
            raise _tenant_unavailable()
        tenant_id = _bounded_id(session["tenant_id"], "tenant_id")
        if tenant_id == product_id or tenant_id == subject_id:
            raise _tenant_unavailable("Canonical tenant must be distinct.")

        return TrustedCallerScope(
            app_id=app_id, subject_id=subject_id, tenant_id=tenant_id
        )
