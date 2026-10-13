"""Canonical caller identity, tenant scope and cost authority for the STT Worker.

This module is the implementation of the paid-route gate that #4643 left open.
It builds exactly one value — :class:`voice_stt_contract.CallerAuthorization` —
and it builds it only from the **canonical Control Plane**, never from request
content and never from a binding's own verdict.

Reuse, not a second authority
-----------------------------
The same two private Control Plane Service Bindings the Engine already uses are
reused unchanged, so voice spending is admitted by the same authority as Engine
spending instead of a voice-local ledger or a second entitlement system:

``CONTROL_PLANE_IDENTITY``
    ``resolve_auth_session`` — the canonical login truth. Mirrors
    ``apps/padiem-ai-engine/app/auth_session_scope_authority.py``.

``CONTROL_PLANE_ENGINE_ADMISSION``
    ``fetch_entitlement_snapshot`` and ``reserve_usage`` — the canonical
    entitlement + usage-reservation pair. Mirrors
    ``apps/padiem-ai-engine/app/control_plane_trust_client.py`` and
    ``app/tenant_auth.py``.

What the caller sends, and what it does not
------------------------------------------
A calling product Worker sends two **opaque clues**: the product it acts for and
the end user's canonical auth-session id. Neither is an identity. They only
select which Control Plane session to resolve; the authenticated subject, its
tenant, its entitlement and its cost reservation are all read back from the
Control Plane. This is the canonical ``#2157``/``#2158`` "opaque server-resolved
clue" pattern the Engine already uses, and it fails closed when the Control Plane
cannot confirm them.

Nothing the caller controls can move the cost: the number of reserved metering
units is computed by this Worker from the audio length it already validated
(:func:`voice_stt_contract.cost_units_for_audio`), and the reservation itself is
made by the Control Plane. There is deliberately **no** client-supplied spend cap,
plan, entitlement or account field — a verdict shaped like ``{"allowed": True}``
with a self-declared cost allowance has nowhere to enter.

Residual boundary, stated rather than hidden
--------------------------------------------
A Service Binding carries no built-in caller identity, so the *product* label
still comes from the attached caller. That is acceptable only because the binding
is deployment-owned (it may be attached to reviewed product Workers) and because
a caller that claims another product can at most spend **its own** Control Plane
tenant's reservation — the session, the tenant, the entitlement and the
reservation are all verified against the Control Plane, never against the claim.
Deploying this Worker therefore requires CENTRAL to review which Workers hold the
binding; the source contract does not and cannot enforce it.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import voice_stt_contract as contract

#: Opaque clues a calling product Worker may present. Both are re-verified by the
#: Control Plane; neither is an identity or an authorization.
CALLER_PRODUCT_HEADER = "x-padiem-product-id"
CALLER_SESSION_HEADER = "x-padiem-auth-session-id"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_MAX_OPAQUE_CHARS = 256

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
_GRANT_KEYS = frozenset({"key", "allowed", "limit"})
_RESERVATION_KEYS = frozenset({"reservation_ref", "admitted", "expires_at", "reserved_at"})
_SNAPSHOT_KEYS = frozenset(
    {"snapshot_id", "product_id", "subject", "revision", "issued_at", "expires_at", "grants"}
)
_SESSION_STATES = frozenset({"active", "revoked", "expired"})

#: Only an authenticated canonical *user* may spend. An anonymous or
#: app-account subject is never eligible for a paid provider call, matching the
#: Control Plane entitlement producer's own rule.
_SUBJECT_TYPE_USER = "user"

_MAX_GRANTS = 64


# ---------------------------------------------------------------------------
# Bounded failures — every one is a registered contract code
# ---------------------------------------------------------------------------


def _unauthenticated() -> contract.VoiceSttError:
    return contract.VoiceSttError("voice_stt_unauthenticated", 401)


def _forbidden() -> contract.VoiceSttError:
    return contract.VoiceSttError("voice_stt_forbidden", 403)


def _cost_denied() -> contract.VoiceSttError:
    return contract.VoiceSttError("voice_stt_cost_denied", 403)


def _authority_unavailable() -> contract.VoiceSttError:
    return contract.VoiceSttError("voice_stt_authority_unavailable", 503)


def _tenant_unavailable() -> contract.VoiceSttError:
    return contract.VoiceSttError("voice_stt_tenant_unavailable", 503)


# ---------------------------------------------------------------------------
# Caller clues
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallerClues:
    """What the attached caller presented. Verified, never trusted."""

    product_id: str
    session_id: str


def _bounded_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise _unauthenticated()
    return value


_ROUTE_RE = re.compile(r"^/[A-Za-z0-9._:@/-]{0,190}$")


def _route_path(value: Any) -> str:
    """Validate one exact internal route path.

    The route is Worker-owned rather than caller-owned, but it still has to be a
    bounded safe path: it is what an authorization is bound to, so a malformed
    route must never produce an authorization that admits anything.
    """
    if not isinstance(value, str) or not _ROUTE_RE.fullmatch(value):
        raise _authority_unavailable()
    return value


def _opaque(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise _authority_unavailable()
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_OPAQUE_CHARS:
        raise _authority_unavailable()
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise _authority_unavailable()
    return normalized


def _closed(payload: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise _authority_unavailable()
    if frozenset(payload) != expected:
        raise _authority_unavailable()
    return dict(payload)


def _timestamp(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise _authority_unavailable() from None
    else:
        raise _authority_unavailable()
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _authority_unavailable()
    return parsed


def parse_caller_clues(headers: Any) -> CallerClues:
    """Read the two opaque clues, failing closed before any body is consumed.

    Missing, malformed or non-string clues are unauthenticated. This runs before
    the bounded body read so a request without identity never gets its payload
    buffered, while the Control Plane round trip still happens after the payload
    is validated — the metering units depend on the validated audio length.
    """
    if headers is None or not hasattr(headers, "get"):
        raise _unauthenticated()
    raw_product = headers.get(CALLER_PRODUCT_HEADER)
    raw_session = headers.get(CALLER_SESSION_HEADER)
    if raw_product is None or raw_session is None:
        raise _unauthenticated()
    return CallerClues(
        product_id=_bounded_id(raw_product, "product_id"),
        session_id=_bounded_id(raw_session, "session_id"),
    )


# ---------------------------------------------------------------------------
# Identity / admission ports
# ---------------------------------------------------------------------------


class IdentitySessionPort(Protocol):
    def resolve_auth_session(self, *, session_id: str) -> Any: ...


class AdmissionPort(Protocol):
    def fetch_entitlement_snapshot(
        self, *, product_id: str, subject: Mapping[str, str]
    ) -> Any: ...

    def reserve_usage(self, *, reservation: Mapping[str, Any]) -> Any: ...


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _unwrap(result: Any, key: str, *, refusal: Any) -> dict[str, Any]:
    """Unwrap one ``{"ok": True, <key>: ...}`` authority response, or fail closed.

    A ``{"ok": False, ...}`` verdict is a real answer from the authority, not a
    transport fault, so it maps to the caller's bounded *refusal* rather than to
    an outage. It is still never an allow.
    """
    if not isinstance(result, Mapping):
        raise _authority_unavailable()
    if result.get("ok") is False:
        raise refusal()
    if result.get("ok") is not True:
        raise _authority_unavailable()
    if frozenset(result) != frozenset({"ok", key}):
        raise _authority_unavailable()
    payload = result[key]
    if not isinstance(payload, Mapping):
        raise _authority_unavailable()
    return dict(payload)


class CloudflareIdentitySessionClient:
    """Adapter over the private Control Plane identity Service Binding."""

    def __init__(self, binding: Any) -> None:
        if not callable(getattr(binding, "resolve_auth_session", None)):
            raise _authority_unavailable()
        self._binding = binding

    async def resolve_auth_session(self, *, session_id: str) -> Any:
        try:
            result = await _maybe_await(self._binding.resolve_auth_session({"session_id": session_id}))
        except contract.VoiceSttError:
            raise
        except Exception:
            raise _authority_unavailable() from None
        if not isinstance(result, Mapping):
            raise _authority_unavailable()
        if result.get("ok") is False:
            return None
        return _unwrap(result, "session", refusal=_unauthenticated)


class CloudflareAdmissionClient:
    """Adapter over the private Control Plane entitlement + usage authority."""

    def __init__(self, binding: Any) -> None:
        for name in ("fetch_entitlement_snapshot", "reserve_usage"):
            if not callable(getattr(binding, name, None)):
                raise _authority_unavailable()
        self._binding = binding

    async def fetch_entitlement_snapshot(
        self, *, product_id: str, subject: Mapping[str, str]
    ) -> Any:
        try:
            result = await _maybe_await(
                self._binding.fetch_entitlement_snapshot(
                    {"product_id": product_id, "subject": dict(subject)}
                )
            )
        except contract.VoiceSttError:
            raise
        except Exception:
            raise _authority_unavailable() from None
        return _unwrap(result, "snapshot", refusal=_forbidden)

    async def reserve_usage(self, *, reservation: Mapping[str, Any]) -> Any:
        try:
            result = await _maybe_await(
                self._binding.reserve_usage({"reservation": dict(reservation)})
            )
        except contract.VoiceSttError:
            raise
        except Exception:
            raise _authority_unavailable() from None
        return _unwrap(result, "reservation", refusal=_cost_denied)


# ---------------------------------------------------------------------------
# The authority
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallerIdentity:
    """The authenticated actor and its canonical tenant, both server-derived."""

    product_id: str
    tenant_id: str
    subject_id: str

    def subject_ref(self) -> dict[str, str]:
        return {"subject_type": _SUBJECT_TYPE_USER, "subject_id": self.subject_id}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CallerAuthority:
    """Verify one paid voice call against the canonical Control Plane.

    Order is deliberate and each step can only deny: session, then entitlement,
    then cost reservation. Nothing is read from the request beyond the two opaque
    clues, and the metering unit count comes from the Worker's own validated audio
    length, so a caller can neither understate the cost nor skip a step.
    """

    def __init__(
        self,
        *,
        identity: IdentitySessionPort,
        admission: AdmissionPort,
        clock: Any | None = None,
    ) -> None:
        if not callable(getattr(identity, "resolve_auth_session", None)):
            raise _authority_unavailable()
        if not callable(getattr(admission, "fetch_entitlement_snapshot", None)):
            raise _authority_unavailable()
        if not callable(getattr(admission, "reserve_usage", None)):
            raise _authority_unavailable()
        self._identity = identity
        self._admission = admission
        self._clock = clock if clock is not None else _utc_now

    async def resolve_identity(self, clues: CallerClues) -> CallerIdentity:
        """Turn an opaque session clue into an authenticated actor + tenant."""
        now = self._now()
        try:
            payload = await self._identity.resolve_auth_session(session_id=clues.session_id)
        except contract.VoiceSttError:
            raise
        except Exception:
            raise _authority_unavailable() from None
        if payload is None:
            raise _unauthenticated()
        return self._identity_from_session(payload, clues=clues, now=now)

    def _identity_from_session(
        self, payload: Any, *, clues: CallerClues, now: datetime
    ) -> CallerIdentity:
        expected = _SESSION_KEYS if "tenant_id" not in payload else _SESSION_KEYS | {"tenant_id"}
        session = _closed(payload, expected, "auth session")
        session_id = _opaque(session["session_id"], "session_id")
        if session_id != clues.session_id:
            raise _forbidden()
        product_id = _bounded_id(session["product_id"], "product_id")
        if product_id != clues.product_id:
            raise _forbidden()
        revision = session["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise _authority_unavailable()
        issued_at = _timestamp(session["issued_at"], "issued_at")
        expires_at = _timestamp(session["expires_at"], "expires_at")
        if expires_at <= issued_at:
            raise _authority_unavailable()
        state = session["state"]
        if isinstance(state, str):
            state = state.strip().lower()
        if state not in _SESSION_STATES:
            raise _authority_unavailable()
        if state != "active" or now >= expires_at:
            raise _unauthenticated()

        subject = _closed(session["subject"], _SUBJECT_KEYS, "session subject")
        if subject["subject_type"] != _SUBJECT_TYPE_USER:
            raise _forbidden()
        subject_id = _opaque(subject["subject_id"], "subject_id")

        # #2159 locked semantics, mirrored: no default, no alias, no fallback.
        tenant_id = session.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise _tenant_unavailable()
        tenant_id = tenant_id.strip()
        if tenant_id == product_id or tenant_id == subject_id:
            raise _tenant_unavailable()
        return CallerIdentity(
            product_id=product_id, tenant_id=tenant_id, subject_id=subject_id
        )

    async def authorize(
        self,
        *,
        clues: CallerClues,
        capability: str,
        route: str,
        estimated_units: int,
    ) -> contract.CallerAuthorization:
        """Return the one authorization a paid route may consume, or raise."""
        capability = _bounded_id(capability, "capability")
        route = _route_path(route)
        if (
            isinstance(estimated_units, bool)
            or not isinstance(estimated_units, int)
            or not 1 <= estimated_units <= contract.MAX_RESERVATION_UNITS
        ):
            raise _cost_denied()

        identity = await self.resolve_identity(clues)
        granted_at = self._now()
        snapshot = self._snapshot(
            await self._admission.fetch_entitlement_snapshot(
                product_id=identity.product_id,
                subject=identity.subject_ref(),
            ),
            identity=identity,
            now=granted_at,
        )
        if not self._grant_allows(snapshot, capability=capability, estimated_units=estimated_units):
            raise _cost_denied()

        reservation = self._reservation_payload(
            identity=identity,
            capability=capability,
            route=route,
            estimated_units=estimated_units,
            now=granted_at,
        )
        reservation_ref = await self._admit_reservation(
            reservation, estimated_units=estimated_units
        )

        authorization = contract.CallerAuthorization(
            actor=identity.subject_id,
            tenant=identity.tenant_id,
            route=route,
            capability=capability,
            reservation_id=reservation_ref,
            estimated_units=estimated_units,
            policy_revision=snapshot["revision"],
        )
        if not authorization.admits(route):
            # Defence in depth: an authority response that would produce an
            # incomplete authorization denies instead of reaching a Secret.
            raise _authority_unavailable()
        return authorization

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise _authority_unavailable()
        return now

    def _snapshot(self, payload: Any, *, identity: CallerIdentity, now: datetime) -> dict[str, Any]:
        snapshot = _closed(payload, _SNAPSHOT_KEYS, "entitlement snapshot")
        snapshot_id = _opaque(snapshot["snapshot_id"], "snapshot_id")
        product_id = _bounded_id(snapshot["product_id"], "snapshot_id")
        if product_id != identity.product_id:
            raise _forbidden()
        subject = _closed(snapshot["subject"], _SUBJECT_KEYS, "snapshot subject")
        if (
            subject["subject_type"] != _SUBJECT_TYPE_USER
            or _opaque(subject["subject_id"], "subject_id") != identity.subject_id
        ):
            raise _forbidden()
        revision = _opaque(snapshot["revision"], "revision")
        issued_at = _timestamp(snapshot["issued_at"], "issued_at")
        expires_at = _timestamp(snapshot["expires_at"], "expires_at")
        if expires_at <= issued_at:
            raise _authority_unavailable()
        if issued_at > now:
            raise _forbidden()
        if expires_at <= now:
            raise _cost_denied()

        raw_grants = snapshot["grants"]
        if not isinstance(raw_grants, (list, tuple)):
            raise _authority_unavailable()
        if len(raw_grants) > _MAX_GRANTS:
            raise _authority_unavailable()
        grants: dict[str, dict[str, Any]] = {}
        for item in raw_grants:
            grant = _closed(item, _GRANT_KEYS, "entitlement grant")
            key = _bounded_id(grant["key"], "grant key")
            if key in grants:
                raise _authority_unavailable()
            allowed = grant["allowed"]
            if not isinstance(allowed, bool):
                raise _authority_unavailable()
            limit = grant["limit"]
            if limit is not None and (
                isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
            ):
                raise _authority_unavailable()
            if limit is not None and not allowed:
                raise _authority_unavailable()
            grants[key] = {"allowed": allowed, "limit": limit}
        return {"snapshot_id": snapshot_id, "revision": revision, "grants": grants}

    def _grant_allows(
        self, snapshot: dict[str, Any], *, capability: str, estimated_units: int
    ) -> bool:
        grant = snapshot["grants"].get(capability)
        if grant is None or not grant["allowed"]:
            return False
        limit = grant["limit"]
        return limit is None or estimated_units <= limit

    def _reservation_payload(
        self,
        *,
        identity: CallerIdentity,
        capability: str,
        route: str,
        estimated_units: int,
        now: datetime,
    ) -> dict[str, Any]:
        # Control Plane deliberately reuses a prior reservation for an identical
        # idempotency key. This nonce is generated once per paid HTTP dispatch:
        # two independent utterances or live-token requests of the same size
        # MUST have distinct reservations. The browser supplies no nonce/cost.
        request_nonce = uuid4().hex
        material = "|".join(
            (
                "voice-stt-reserve-v1",
                request_nonce,
                identity.product_id,
                identity.tenant_id,
                identity.subject_id,
                capability,
                route,
                str(estimated_units),
            )
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return {
            "idempotency_key": f"vstt-{digest[:40]}",
            "billing_semantic_id": capability,
            "product_id": identity.product_id,
            "subject": identity.subject_ref(),
            "request_fingerprint": digest,
            "trace_id": None,
            "estimated_units": estimated_units,
            "occurred_at": now.isoformat(),
        }

    async def _admit_reservation(
        self, reservation: dict[str, Any], *, estimated_units: int
    ) -> str:
        payload = await self._admission.reserve_usage(reservation=reservation)
        # Control Plane stamps reserved_at DURING this await. Observe the clock
        # after the authority RPC, not before, or a valid reservation appears to
        # come from the future and is spuriously rejected.
        observed_at = self._now()
        decision = _closed(payload, _RESERVATION_KEYS, "usage reservation")
        reservation_ref = _opaque(decision["reservation_ref"], "reservation_ref")
        admitted = decision["admitted"]
        if not isinstance(admitted, bool):
            raise _authority_unavailable()
        reserved_at = _timestamp(decision["reserved_at"], "reserved_at")
        expires_at = _timestamp(decision["expires_at"], "expires_at")
        if expires_at <= reserved_at:
            raise _authority_unavailable()
        if reserved_at > observed_at:
            raise _authority_unavailable()
        if not admitted or expires_at <= observed_at:
            raise _cost_denied()
        if estimated_units < 1 or estimated_units > contract.MAX_RESERVATION_UNITS:
            raise _cost_denied()
        return reservation_ref


def caller_authority_for_env(env: Any) -> CallerAuthority:
    """Compose the authority from the two canonical private Service Bindings.

    Both bindings must expose exactly the reviewed RPCs. Anything else — absent,
    a plain object, a duck-typed alias, an object that only *looks* like the
    authority — fails closed, because a guard that cannot be verified is not a
    guard. The Worker's shipped configuration attaches neither binding.
    """
    identity = getattr(env, contract.VOICE_STT_IDENTITY_BINDING, None)
    admission = getattr(env, contract.VOICE_STT_ADMISSION_BINDING, None)
    if identity is None or admission is None:
        raise contract.VoiceSttError("caller_guard_unavailable", 503)
    try:
        return CallerAuthority(
            identity=CloudflareIdentitySessionClient(identity),
            admission=CloudflareAdmissionClient(admission),
        )
    except contract.VoiceSttError:
        # A binding that is present but does not expose the reviewed RPCs is not
        # a weaker authority — it is no authority, so it is reported as an
        # unavailable guard rather than as a transient outage.
        raise contract.VoiceSttError("caller_guard_unavailable", 503) from None


VOICE_STT_CALLER_AUTHORITY_REUSES_CONTROL_PLANE = True
VOICE_STT_CALLER_AUTHORITY_ACCEPTS_CLIENT_COST_SCOPE = False
VOICE_STT_CALLER_AUTHORITY_BOUND_TO_PRODUCTION = False
