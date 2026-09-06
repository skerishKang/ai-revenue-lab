"""Control Plane tenant/entitlement admission adapter for Engine execution (#1751 E7).

This module integrates the Engine's trusted execution-admission seam with the
Control Plane's canonical entitlement and usage contracts. The Engine remains
the enforcement point and the Control Plane remains the canonical authority:

- Tenant identification is server-owned. The request app id maps to the
  Control Plane product and the server-derived subject maps to a canonical
  subject reference. Client plan/entitlement/credit/allow assertions are never
  inputs to this module.
- Entitlement verification resolves a server-trusted Control Plane entitlement
  snapshot and consumes only the machine grant for the requested capability.
  Absence of a grant never implies allow.
- Usage admission performs one bounded pre-dispatch usage reservation through
  the Control Plane client before an allowed decision is issued, and exposes a
  post-dispatch usage-receipt seam built only from server-side execution
  evidence. The Engine keeps no billing ledger of its own.
- Every transport failure, malformed authority response, expired snapshot,
  product/subject mismatch, or denied reservation fails closed.

The Control Plane client is injected as a Protocol so the Engine never imports
``padiem_control_plane`` directly; payloads follow the Control Plane public
dict shapes (``to_public_dict``/``to_policy_dict`` projections). Live HTTP
transport wiring stays a separate composition slice; until then the default
Worker composition passes no client and the gate fails closed exactly as
before (CONTROL_PLANE_LIVE_ADAPTER wiring stays opt-in).
"""

from __future__ import annotations

import hashlib
import inspect
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.execution_admission import (
    ExecutionAdmissionError,
    ExecutionAdmissionRequest,
    TrustedExecutionAdmission,
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

SUBJECT_TYPE_USER = "user"
SUBJECT_TYPE_ACCOUNT = "account"

USAGE_OUTCOMES = frozenset({"succeeded", "failed", "cancelled"})
BILLING_DISPOSITIONS = frozenset({"billable", "non_billable"})

DEFAULT_MAX_ADMISSION_TTL = timedelta(minutes=5)
MAX_RESERVATION_UNITS = 1_000_000

_SNAPSHOT_KEYS = frozenset(
    {"snapshot_id", "product_id", "subject", "revision", "issued_at", "expires_at", "grants"}
)
_SUBJECT_KEYS = frozenset({"subject_type", "subject_id"})
_GRANT_KEYS = frozenset({"key", "allowed", "limit"})
_RESERVATION_KEYS = frozenset({"reservation_ref", "admitted", "expires_at"})
_RECEIPT_ACK_KEYS = frozenset({"accepted", "event_id"})


class ControlPlaneTrustClient(Protocol):
    """Injected Control Plane authority surface used by the Engine adapter.

    Each method may be synchronous or return an awaitable. Implementations own
    transport, authentication, and timeouts; this module never trusts anything
    the client returns without validation.
    """

    def fetch_entitlement_snapshot(
        self, *, product_id: str, subject: Mapping[str, str]
    ) -> Any: ...

    def reserve_usage(self, *, reservation: Mapping[str, Any]) -> Any: ...

    def record_usage(self, *, usage_event: Mapping[str, Any]) -> Any: ...


@dataclass(frozen=True, slots=True)
class TenantIdentity:
    """Server-derived tenant scope for one admission or usage submission."""

    product_id: str
    subject_type: str
    subject_id: str

    def subject_ref(self) -> dict[str, str]:
        return {"subject_type": self.subject_type, "subject_id": self.subject_id}


def identify_tenant(request: ExecutionAdmissionRequest) -> TenantIdentity:
    """Derive the canonical tenant scope from server-owned request fields only.

    A present subject maps to a user subject; an app-level request maps to the
    account subject for that product. Nothing client-asserted participates.
    """

    if request.subject_id is not None:
        return TenantIdentity(
            product_id=request.app_id,
            subject_type=SUBJECT_TYPE_USER,
            subject_id=request.subject_id,
        )
    return TenantIdentity(
        product_id=request.app_id,
        subject_type=SUBJECT_TYPE_ACCOUNT,
        subject_id=request.app_id,
    )


class EntitlementSnapshotView:
    """Validated read-only view of one Control Plane entitlement snapshot."""

    __slots__ = ("expires_at", "grants", "issued_at", "product_id", "revision", "snapshot_id", "subject")

    def __init__(
        self,
        *,
        snapshot_id: str,
        product_id: str,
        subject: Mapping[str, str],
        revision: str,
        issued_at: datetime,
        expires_at: datetime,
        grants: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self.snapshot_id = snapshot_id
        self.product_id = product_id
        self.subject = dict(subject)
        self.revision = revision
        self.issued_at = issued_at
        self.expires_at = expires_at
        self.grants = dict(grants)


def parse_entitlement_snapshot(
    payload: Any,
    *,
    expected: TenantIdentity,
    now: datetime,
) -> EntitlementSnapshotView:
    """Validate one Control Plane snapshot projection and bind it to the tenant.

    The payload shape mirrors ``EntitlementSnapshot.to_policy_dict()``. Any
    structural violation fails closed as an unavailable authority; product or
    subject mismatch fails closed as an explicit mismatch so cross-tenant
    evidence can never authorize this request.
    """

    snapshot = _closed(payload, _SNAPSHOT_KEYS, "entitlement snapshot")
    snapshot_id = _identifier(snapshot["snapshot_id"], "snapshot_id")
    product_id = _identifier(snapshot["product_id"], "product_id")
    revision = _identifier(snapshot["revision"], "revision")
    subject = _closed(snapshot["subject"], _SUBJECT_KEYS, "snapshot subject")
    subject_type = subject["subject_type"]
    if subject_type not in {SUBJECT_TYPE_USER, SUBJECT_TYPE_ACCOUNT, "anonymous"}:
        raise _unavailable("entitlement snapshot subject_type is invalid.")
    subject_id = _opaque(subject["subject_id"], "snapshot subject_id")
    issued_at = _timestamp(snapshot["issued_at"], "issued_at")
    expires_at = _timestamp(snapshot["expires_at"], "expires_at")
    if expires_at <= issued_at:
        raise _unavailable("entitlement snapshot expiry is not after issuance.")

    grants_raw = snapshot["grants"]
    if not isinstance(grants_raw, Sequence) or isinstance(grants_raw, (str, bytes)):
        raise _unavailable("entitlement snapshot grants must be a sequence.")
    if len(grants_raw) > 64:
        raise _unavailable("entitlement snapshot grant count exceeds the bounded limit.")
    grants: dict[str, dict[str, Any]] = {}
    for item in grants_raw:
        grant = _closed(item, _GRANT_KEYS, "entitlement grant")
        key = _identifier(grant["key"], "entitlement key")
        if key in grants:
            raise _unavailable("entitlement snapshot grants must be unique.")
        allowed = grant["allowed"]
        if not isinstance(allowed, bool):
            raise _unavailable("entitlement grant allowed must be a boolean.")
        limit = grant["limit"]
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
            raise _unavailable("entitlement grant limit must be a positive integer or null.")
        if limit is not None and not allowed:
            raise _unavailable("a denied entitlement cannot carry a positive limit.")
        grants[key] = {"key": key, "allowed": allowed, "limit": limit}

    if product_id != expected.product_id:
        raise ExecutionAdmissionError(
            "entitlement_app_mismatch",
            "Control Plane entitlement snapshot belongs to a different tenant.",
        )
    if subject_type != expected.subject_type or subject_id != expected.subject_id:
        raise ExecutionAdmissionError(
            "entitlement_subject_mismatch",
            "Control Plane entitlement snapshot belongs to a different subject.",
        )
    if issued_at > now:
        raise ExecutionAdmissionError("invalid_admission", "Control Plane entitlement snapshot is from the future.")
    if expires_at <= now:
        raise ExecutionAdmissionError("entitlement_expired", "Control Plane entitlement snapshot is expired.")
    return EntitlementSnapshotView(
        snapshot_id=snapshot_id,
        product_id=product_id,
        subject={"subject_type": subject_type, "subject_id": subject_id},
        revision=revision,
        issued_at=issued_at,
        expires_at=expires_at,
        grants=grants,
    )


@dataclass(frozen=True, slots=True)
class UsageReservation:
    """Bounded pre-dispatch usage reservation request for one admitted capability."""

    idempotency_key: str
    billing_semantic_id: str
    product_id: str
    subject: Mapping[str, str]
    request_fingerprint: str | None
    trace_id: str | None
    estimated_units: int
    occurred_at: datetime

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "billing_semantic_id": self.billing_semantic_id,
            "product_id": self.product_id,
            "subject": dict(self.subject),
            "request_fingerprint": self.request_fingerprint,
            "trace_id": self.trace_id,
            "estimated_units": self.estimated_units,
            "occurred_at": self.occurred_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class UsageReceipt:
    """Server-evidence-only post-dispatch usage receipt for Control Plane reporting.

    Mirrors the Control Plane ``UsageEvent`` public shape. It carries no
    prompt, response, secret, or arbitrary metadata field and must be built
    exclusively from trusted server-side execution evidence.
    """

    event_id: str
    idempotency_key: str
    billing_semantic_id: str
    product_id: str
    subject: Mapping[str, str]
    execution_id: str
    outcome: str
    billing_disposition: str
    occurred_at: datetime
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        _identifier(self.event_id, "event_id")
        _opaque(self.idempotency_key, "idempotency_key", limit=256)
        _identifier(self.billing_semantic_id, "billing_semantic_id")
        _identifier(self.product_id, "product_id")
        _identifier(self.execution_id, "execution_id")
        subject = _closed(self.subject, _SUBJECT_KEYS, "receipt subject")
        object.__setattr__(self, "subject", dict(subject))
        if self.outcome not in USAGE_OUTCOMES:
            raise ValueError("usage receipt outcome is invalid.")
        if self.billing_disposition not in BILLING_DISPOSITIONS:
            raise ValueError("usage receipt billing disposition is invalid.")
        _timestamp_value(self.occurred_at, "occurred_at")
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"usage receipt {name} must be a non-negative integer or None.")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "idempotency_key": self.idempotency_key,
            "billing_semantic_id": self.billing_semantic_id,
            "product_id": self.product_id,
            "subject": dict(self.subject),
            "execution_id": self.execution_id,
            "outcome": self.outcome,
            "billing_disposition": self.billing_disposition,
            "occurred_at": self.occurred_at.isoformat(),
            "tokens": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
            },
            "route": {"status": "unknown"},
            "cost": None,
        }


class ControlPlaneTenantAdmissionAdapter:
    """Resolve trusted Engine execution admission through the Control Plane.

    Implements the :class:`app.execution_admission.ExecutionAdmissionAdapter`
    contract. Every resolution performs at least one Control Plane authority
    call; a decision is never synthesized locally.
    """

    def __init__(
        self,
        *,
        client: ControlPlaneTrustClient,
        clock: Any | None = None,
        max_admission_ttl: timedelta = DEFAULT_MAX_ADMISSION_TTL,
        require_usage_reservation: bool = True,
        estimated_units: int = 1,
    ) -> None:
        if client is None or not callable(getattr(client, "fetch_entitlement_snapshot", None)):
            raise ExecutionAdmissionError(
                "entitlement_unavailable",
                "Control Plane entitlement authority is unavailable.",
                status_code=503,
            )
        if require_usage_reservation and not callable(getattr(client, "reserve_usage", None)):
            raise ExecutionAdmissionError(
                "entitlement_unavailable",
                "Control Plane usage reservation authority is unavailable.",
                status_code=503,
            )
        if (
            isinstance(estimated_units, bool)
            or not isinstance(estimated_units, int)
            or not 1 <= estimated_units <= MAX_RESERVATION_UNITS
        ):
            raise ValueError("estimated_units must be a bounded positive integer.")
        if max_admission_ttl <= timedelta(0):
            raise ValueError("max_admission_ttl must be positive.")
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_admission_ttl = max_admission_ttl
        self._require_usage_reservation = require_usage_reservation
        self._estimated_units = estimated_units

    async def resolve_admission(self, request: ExecutionAdmissionRequest) -> TrustedExecutionAdmission:
        now = self._clock()
        _timestamp_value(now, "now")
        tenant = identify_tenant(request)

        snapshot = parse_entitlement_snapshot(
            await _maybe_await(
                self._client.fetch_entitlement_snapshot(
                    product_id=tenant.product_id,
                    subject=tenant.subject_ref(),
                )
            ),
            expected=tenant,
            now=now,
        )

        grant = snapshot.grants.get(request.capability)
        allowed = bool(grant is not None and grant["allowed"])
        authority_ref = f"control-plane:entitlement:{snapshot.snapshot_id}"

        if allowed and self._require_usage_reservation:
            reservation = self._build_reservation(request, tenant, snapshot, now)
            decision = parse_usage_reservation(
                await _maybe_await(self._client.reserve_usage(reservation=reservation.to_public_dict())),
                reservation=reservation,
                now=now,
            )
            if not decision["admitted"]:
                allowed = False
            else:
                authority_ref = f"{authority_ref}@{decision['reservation_ref']}"

        expires_at = min(snapshot.expires_at, now + self._max_admission_ttl)
        if expires_at <= now:
            raise ExecutionAdmissionError(
                "entitlement_expired",
                "Control Plane admission window has elapsed.",
            )
        return TrustedExecutionAdmission(
            decision_id=_decision_id(request, snapshot, now, allowed),
            app_id=request.app_id,
            subject_id=request.subject_id,
            capability=request.capability,
            allowed=allowed,
            authority_ref=authority_ref,
            policy_revision=snapshot.revision,
            issued_at=now,
            expires_at=expires_at,
            request_fingerprint=request.request_fingerprint,
        )

    async def record_usage_receipt(self, receipt: UsageReceipt) -> dict[str, Any]:
        """Submit one post-dispatch usage receipt to the Control Plane authority.

        The Engine keeps no billing ledger; failures propagate as admission
        errors so composition can surface the receipt as failed without
        silently dropping usage evidence.
        """

        if not callable(getattr(self._client, "record_usage", None)):
            raise ExecutionAdmissionError(
                "entitlement_unavailable",
                "Control Plane usage receipt authority is unavailable.",
                status_code=503,
            )
        ack = _closed(
            await _maybe_await(self._client.record_usage(usage_event=receipt.to_public_dict())),
            _RECEIPT_ACK_KEYS,
            "usage receipt acknowledgement",
        )
        accepted = ack["accepted"]
        if not isinstance(accepted, bool):
            raise _unavailable("usage receipt acknowledgement accepted must be a boolean.")
        event_id = _identifier(ack["event_id"], "event_id")
        if event_id != receipt.event_id:
            raise ExecutionAdmissionError(
                "entitlement_request_mismatch",
                "Control Plane usage receipt event identity does not match.",
                status_code=409,
            )
        return {"accepted": accepted, "event_id": event_id}

    def _build_reservation(
        self,
        request: ExecutionAdmissionRequest,
        tenant: TenantIdentity,
        snapshot: EntitlementSnapshotView,
        now: datetime,
    ) -> UsageReservation:
        identity = "|".join(
            (
                "reserve",
                request.app_id,
                request.capability,
                request.request_fingerprint or "unbound",
                snapshot.revision,
            )
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return UsageReservation(
            idempotency_key=f"res-{digest}",
            billing_semantic_id=request.capability,
            product_id=tenant.product_id,
            subject=tenant.subject_ref(),
            request_fingerprint=request.request_fingerprint,
            trace_id=request.trace_id,
            estimated_units=self._estimated_units,
            occurred_at=now,
        )


def parse_usage_reservation(payload: Any, *, reservation: UsageReservation, now: datetime) -> dict[str, Any]:
    """Validate one Control Plane usage reservation decision."""

    decision = _closed(payload, _RESERVATION_KEYS, "usage reservation")
    reservation_ref = _identifier(decision["reservation_ref"], "reservation_ref")
    admitted = decision["admitted"]
    if not isinstance(admitted, bool):
        raise _unavailable("usage reservation admitted must be a boolean.")
    expires_at = _timestamp(decision["expires_at"], "reservation expires_at")
    if expires_at <= now:
        if admitted:
            raise ExecutionAdmissionError(
                "entitlement_expired",
                "Control Plane usage reservation is expired.",
            )
        admitted = False
    return {
        "reservation_ref": reservation_ref,
        "admitted": admitted,
        "idempotency_key": reservation.idempotency_key,
    }


def build_control_plane_admission_adapter(
    client: ControlPlaneTrustClient | None,
    **kwargs: Any,
) -> ControlPlaneTenantAdmissionAdapter | None:
    """Compose the live adapter only when a Control Plane client is configured.

    ``None`` preserves the current default Worker behavior: the gate fails
    closed with ``entitlement_unavailable`` exactly as before this slice.
    """

    if client is None:
        return None
    return ControlPlaneTenantAdmissionAdapter(client=client, **kwargs)


def _decision_id(
    request: ExecutionAdmissionRequest,
    snapshot: EntitlementSnapshotView,
    now: datetime,
    allowed: bool,
) -> str:
    identity = "|".join(
        (
            request.app_id,
            request.subject_id or "-",
            request.capability,
            snapshot.snapshot_id,
            now.isoformat(),
            "allow" if allowed else "deny",
        )
    )
    return f"eng-adm-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]}"


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _unavailable(message: str) -> ExecutionAdmissionError:
    return ExecutionAdmissionError("entitlement_unavailable", message, status_code=503)


def _closed(payload: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise _unavailable(f"{label} payload is invalid.")
    if frozenset(payload.keys()) != expected:
        raise _unavailable(f"{label} schema mismatch.")
    return dict(payload)


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise _unavailable(f"{name} must be a bounded safe identifier.")
    return value


def _opaque(value: Any, name: str, *, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise _unavailable(f"{name} must be a string.")
    normalized = value.strip()
    if not normalized or len(normalized) > limit or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise _unavailable(f"{name} must be a bounded non-empty opaque identifier.")
    return normalized


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise _unavailable(f"{name} must be ISO-8601 text.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _unavailable(f"{name} must be valid ISO-8601 text.") from exc
    _timestamp_value(parsed, name)
    return parsed


def _timestamp_value(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _unavailable(f"{name} must be timezone-aware.")
    return value
