"""Canonical private Control Plane authority for Engine E7 admission.

This module reuses the existing padiem_control_plane entitlement and usage
contracts. It adds only the durable Control-Plane-owned persistence and
lifecycle needed by the Engine ControlPlaneTrustClient seam:

- immutable, scoped entitlement snapshots;
- idempotent pre-dispatch usage reservations; and
- idempotent post-dispatch UsageEvent recording.

It performs no network I/O, exposes no browser contract, owns no provider
routing, and does not treat a credit balance as an entitlement decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from .contracts import (
    BillingDisposition,
    CanonicalSubjectRef,
    ControlPlaneContractError,
    RouteEvidence,
    RouteEvidenceStatus,
    SubjectType,
    TokenUsage,
    UsageEvent,
    UsageOutcome,
)
from .entitlements import EntitlementGrant, EntitlementSnapshot

MAX_ESTIMATED_UNITS = 1_000_000
RESERVATION_TTL = timedelta(minutes=5)
RESERVATION_CLOCK_SKEW = timedelta(minutes=5)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SUBJECT_KEYS = frozenset({"subject_type", "subject_id"})
_SNAPSHOT_KEYS = frozenset(
    {"snapshot_id", "product_id", "subject", "revision", "issued_at", "expires_at", "grants"}
)
_GRANT_KEYS = frozenset({"key", "allowed", "limit"})
_RESERVATION_KEYS = frozenset(
    {
        "idempotency_key",
        "billing_semantic_id",
        "product_id",
        "subject",
        "request_fingerprint",
        "trace_id",
        "estimated_units",
        "occurred_at",
    }
)
_USAGE_EVENT_KEYS = frozenset(
    {
        "event_id",
        "idempotency_key",
        "billing_semantic_id",
        "product_id",
        "subject",
        "execution_id",
        "outcome",
        "billing_disposition",
        "occurred_at",
        "tokens",
        "route",
        "cost",
    }
)
_TOKEN_KEYS = frozenset({"input_tokens", "output_tokens", "total_tokens"})
_ENGINE_ROUTE_KEYS = frozenset({"status"})


def _error(code: str, message: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, message)


def _closed(payload: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or frozenset(payload.keys()) != keys:
        raise _error(
            "invalid_engine_admission_authority",
            f"{label} has an invalid shape",
        )
    return dict(payload)


def _safe_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise _error(
            "invalid_engine_admission_authority",
            f"{label} must be a bounded safe identifier",
        )
    return value


def _opaque(value: Any, label: str, *, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise _error(
            "invalid_engine_admission_authority",
            f"{label} must be text",
        )
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > limit
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        raise _error(
            "invalid_engine_admission_authority",
            f"{label} must be bounded opaque text",
        )
    return normalized


def _optional_opaque(value: Any, label: str, *, limit: int = 256) -> str | None:
    if value is None:
        return None
    return _opaque(value, label, limit=limit)


def _aware(value: Any, label: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise _error(
            "invalid_engine_admission_authority",
            f"{label} must be timezone-aware",
        )
    return value.astimezone(UTC)


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise _error(
            "invalid_engine_admission_authority",
            f"{label} must be ISO-8601 text",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error(
            "invalid_engine_admission_authority",
            f"{label} must be valid ISO-8601 text",
        ) from exc
    return _aware(parsed, label)


def _iso(value: datetime) -> str:
    return _aware(value, "timestamp").isoformat().replace("+00:00", "Z")


def _rows(cursor: Any) -> list[dict[str, Any]]:
    to_array = getattr(cursor, "toArray", None)
    if not callable(to_array):
        raise _error(
            "engine_admission_storage_error",
            "authority storage returned an invalid cursor",
        )
    raw = to_array()
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            result.append(dict(item))
            continue
        to_py = getattr(item, "to_py", None)
        converted = to_py() if callable(to_py) else None
        if isinstance(converted, dict):
            result.append(dict(converted))
            continue
        try:
            result.append(dict(item))
        except (TypeError, ValueError) as exc:
            raise _error(
                "engine_admission_storage_error",
                "authority storage row is invalid",
            ) from exc
    return result


def _subject_from_wire(payload: Any) -> CanonicalSubjectRef:
    wire = _closed(payload, _SUBJECT_KEYS, "subject")
    try:
        subject_type = SubjectType(wire["subject_type"])
    except (TypeError, ValueError) as exc:
        raise _error(
            "invalid_engine_admission_authority",
            "subject_type is invalid",
        ) from exc
    return CanonicalSubjectRef(
        subject_type=subject_type,
        subject_id=wire["subject_id"],
    )


def snapshot_from_wire(payload: Any) -> EntitlementSnapshot:
    """Parse the existing EntitlementSnapshot policy projection."""

    wire = _closed(payload, _SNAPSHOT_KEYS, "entitlement snapshot")
    grants_raw = wire["grants"]
    if not isinstance(grants_raw, list):
        raise _error(
            "invalid_engine_admission_authority",
            "entitlement grants must be a list",
        )
    grants: list[EntitlementGrant] = []
    for raw in grants_raw:
        grant = _closed(raw, _GRANT_KEYS, "entitlement grant")
        grants.append(
            EntitlementGrant(
                key=grant["key"],
                allowed=grant["allowed"],
                limit=grant["limit"],
            )
        )
    return EntitlementSnapshot(
        snapshot_id=wire["snapshot_id"],
        product_id=wire["product_id"],
        subject=_subject_from_wire(wire["subject"]),
        revision=wire["revision"],
        issued_at=_parse_time(wire["issued_at"], "issued_at"),
        expires_at=_parse_time(wire["expires_at"], "expires_at"),
        grants=tuple(grants),
    )


def _usage_event_from_engine_wire(payload: Any) -> UsageEvent:
    """Parse the deliberately narrowed Engine receipt projection."""

    wire = _closed(payload, _USAGE_EVENT_KEYS, "usage event")
    tokens = _closed(wire["tokens"], _TOKEN_KEYS, "usage tokens")
    route = _closed(wire["route"], _ENGINE_ROUTE_KEYS, "usage route")
    if route["status"] != RouteEvidenceStatus.UNKNOWN.value:
        raise _error(
            "invalid_engine_usage_event",
            "Engine admission receipts cannot assert provider route evidence",
        )
    if wire["cost"] is not None:
        raise _error(
            "invalid_engine_usage_event",
            "Engine admission receipts cannot assert provider cost evidence",
        )
    try:
        outcome = UsageOutcome(wire["outcome"])
        disposition = BillingDisposition(wire["billing_disposition"])
    except (TypeError, ValueError) as exc:
        raise _error(
            "invalid_engine_usage_event",
            "usage outcome/disposition is invalid",
        ) from exc
    return UsageEvent(
        event_id=wire["event_id"],
        idempotency_key=wire["idempotency_key"],
        billing_semantic_id=wire["billing_semantic_id"],
        product_id=wire["product_id"],
        subject=_subject_from_wire(wire["subject"]),
        execution_id=wire["execution_id"],
        outcome=outcome,
        billing_disposition=disposition,
        occurred_at=_parse_time(wire["occurred_at"], "occurred_at"),
        tokens=TokenUsage(
            input_tokens=tokens["input_tokens"],
            output_tokens=tokens["output_tokens"],
            total_tokens=tokens["total_tokens"],
        ),
        route=RouteEvidence(status=RouteEvidenceStatus.UNKNOWN),
        cost=None,
    )


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


class CloudflareEngineAdmissionAuthorityStore:
    """SQLite Durable Object store for canonical E7 entitlement/usage truth."""

    def __init__(
        self,
        storage: Any,
        *,
        allowed_product_ids: frozenset[str],
    ) -> None:
        sql = getattr(storage, "sql", None)
        transaction = getattr(storage, "transactionSync", None)
        if (
            sql is None
            or not callable(getattr(sql, "exec", None))
            or not callable(transaction)
        ):
            raise ValueError("SQLite Durable Object storage is required")
        if not isinstance(allowed_product_ids, frozenset) or not allowed_product_ids:
            raise ValueError("allowed_product_ids must be a non-empty frozenset")
        self._storage = storage
        self._sql = sql
        self._allowed_product_ids = frozenset(
            _safe_id(item, "product_id") for item in allowed_product_ids
        )
        self._initialize()

    def _initialize(self) -> None:
        self._sql.exec(
            "CREATE TABLE IF NOT EXISTS engine_entitlement_snapshot ("
            "snapshot_id TEXT PRIMARY KEY, product_id TEXT NOT NULL, "
            "subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, "
            "revision TEXT NOT NULL, issued_at TEXT NOT NULL, "
            "expires_at TEXT NOT NULL, grants_json TEXT NOT NULL, "
            "UNIQUE(product_id, subject_type, subject_id, revision))"
        )
        self._sql.exec(
            "CREATE INDEX IF NOT EXISTS idx_engine_entitlement_scope_time "
            "ON engine_entitlement_snapshot("
            "product_id, subject_type, subject_id, issued_at)"
        )
        self._sql.exec(
            "CREATE TABLE IF NOT EXISTS engine_usage_reservation ("
            "idempotency_key TEXT PRIMARY KEY, "
            "reservation_ref TEXT NOT NULL UNIQUE, "
            "product_id TEXT NOT NULL, subject_type TEXT NOT NULL, "
            "subject_id TEXT NOT NULL, billing_semantic_id TEXT NOT NULL, "
            "request_json TEXT NOT NULL, admitted INTEGER NOT NULL, "
            "expires_at TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        self._sql.exec(
            "CREATE TABLE IF NOT EXISTS engine_usage_event ("
            "event_id TEXT PRIMARY KEY, "
            "idempotency_key TEXT NOT NULL UNIQUE, "
            "product_id TEXT NOT NULL, subject_type TEXT NOT NULL, "
            "subject_id TEXT NOT NULL, billing_semantic_id TEXT NOT NULL, "
            "payload_json TEXT NOT NULL, recorded_at TEXT NOT NULL)"
        )

    def _require_product(self, product_id: Any) -> str:
        product = _safe_id(product_id, "product_id")
        if product not in self._allowed_product_ids:
            raise _error(
                "engine_admission_product_mismatch",
                "product is not authorized by this Control Plane authority",
            )
        return product

    def install_entitlement_snapshot(
        self,
        snapshot: EntitlementSnapshot,
        *,
        now: datetime,
    ) -> EntitlementSnapshot:
        """Persist one immutable CP-owned entitlement revision.

        This is an internal Control Plane producer seam. It is deliberately not
        forwarded by the Engine-facing Worker entrypoint.
        """

        if not isinstance(snapshot, EntitlementSnapshot):
            raise _error(
                "invalid_entitlement",
                "snapshot must be EntitlementSnapshot",
            )
        self._require_product(snapshot.product_id)
        observed_at = _aware(now, "now")
        if snapshot.issued_at.astimezone(UTC) > observed_at:
            raise _error(
                "future_entitlement_snapshot",
                "entitlement snapshot cannot be future-issued",
            )
        payload = snapshot.to_policy_dict()
        grants_json = _canonical_json(payload["grants"])
        subject = snapshot.subject

        def operation() -> EntitlementSnapshot:
            by_id = _rows(
                self._sql.exec(
                    "SELECT snapshot_id, product_id, subject_type, subject_id, "
                    "revision, issued_at, expires_at, grants_json "
                    "FROM engine_entitlement_snapshot WHERE snapshot_id=?",
                    snapshot.snapshot_id,
                )
            )
            by_revision = _rows(
                self._sql.exec(
                    "SELECT snapshot_id, product_id, subject_type, subject_id, "
                    "revision, issued_at, expires_at, grants_json "
                    "FROM engine_entitlement_snapshot "
                    "WHERE product_id=? AND subject_type=? "
                    "AND subject_id=? AND revision=?",
                    snapshot.product_id,
                    subject.subject_type.value,
                    subject.subject_id,
                    snapshot.revision,
                )
            )
            matches = by_id + [row for row in by_revision if row not in by_id]
            if matches:
                if (
                    len(matches) != 1
                    or self._snapshot_from_row(matches[0]).to_policy_dict()
                    != payload
                ):
                    raise _error(
                        "entitlement_snapshot_conflict",
                        "snapshot identity/revision already belongs to "
                        "different entitlement bytes",
                    )
                return snapshot

            latest = _rows(
                self._sql.exec(
                    "SELECT issued_at FROM engine_entitlement_snapshot "
                    "WHERE product_id=? AND subject_type=? AND subject_id=? "
                    "ORDER BY issued_at DESC LIMIT 1",
                    snapshot.product_id,
                    subject.subject_type.value,
                    subject.subject_id,
                )
            )
            if (
                latest
                and snapshot.issued_at.astimezone(UTC)
                <= _parse_time(latest[0]["issued_at"], "issued_at")
            ):
                raise _error(
                    "stale_entitlement_snapshot",
                    "new entitlement revision must move issued_at forward",
                )
            self._sql.exec(
                "INSERT INTO engine_entitlement_snapshot "
                "(snapshot_id, product_id, subject_type, subject_id, "
                "revision, issued_at, expires_at, grants_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                snapshot.snapshot_id,
                snapshot.product_id,
                subject.subject_type.value,
                subject.subject_id,
                snapshot.revision,
                _iso(snapshot.issued_at),
                _iso(snapshot.expires_at),
                grants_json,
            )
            return snapshot

        return self._storage.transactionSync(operation)

    def fetch_entitlement_snapshot(
        self,
        *,
        product_id: str,
        subject: Mapping[str, str],
        now: datetime,
    ) -> EntitlementSnapshot:
        product = self._require_product(product_id)
        subject_ref = _subject_from_wire(subject)
        observed_at = _aware(now, "now")
        rows = _rows(
            self._sql.exec(
                "SELECT snapshot_id, product_id, subject_type, subject_id, "
                "revision, issued_at, expires_at, grants_json "
                "FROM engine_entitlement_snapshot "
                "WHERE product_id=? AND subject_type=? AND subject_id=? "
                "AND issued_at<=? AND expires_at>? "
                "ORDER BY issued_at DESC LIMIT 1",
                product,
                subject_ref.subject_type.value,
                subject_ref.subject_id,
                _iso(observed_at),
                _iso(observed_at),
            )
        )
        if not rows:
            raise _error(
                "entitlement_snapshot_unavailable",
                "no current entitlement snapshot exists for this product subject",
            )
        return self._snapshot_from_row(rows[0])

    def reserve_usage(
        self,
        reservation: Any,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        wire = _closed(
            reservation,
            _RESERVATION_KEYS,
            "usage reservation",
        )
        product = self._require_product(wire["product_id"])
        subject = _subject_from_wire(wire["subject"])
        idempotency_key = _opaque(
            wire["idempotency_key"],
            "idempotency_key",
        )
        billing_semantic_id = _safe_id(
            wire["billing_semantic_id"],
            "billing_semantic_id",
        )
        request_fingerprint = wire["request_fingerprint"]
        if request_fingerprint is not None and (
            not isinstance(request_fingerprint, str)
            or not _SHA256_RE.fullmatch(request_fingerprint)
        ):
            raise _error(
                "invalid_engine_admission_authority",
                "request_fingerprint must be lowercase SHA-256 or null",
            )
        _optional_opaque(wire["trace_id"], "trace_id")
        estimated_units = wire["estimated_units"]
        if (
            isinstance(estimated_units, bool)
            or not isinstance(estimated_units, int)
            or not 1 <= estimated_units <= MAX_ESTIMATED_UNITS
        ):
            raise _error(
                "invalid_engine_admission_authority",
                "estimated_units is outside the bounded range",
            )
        occurred_at = _parse_time(
            wire["occurred_at"],
            "occurred_at",
        )
        observed_at = _aware(now, "now")
        if (
            occurred_at < observed_at - RESERVATION_CLOCK_SKEW
            or occurred_at > observed_at + RESERVATION_CLOCK_SKEW
        ):
            raise _error(
                "stale_usage_reservation",
                "usage reservation timestamp is outside the accepted clock window",
            )

        canonical_request = {
            "idempotency_key": idempotency_key,
            "billing_semantic_id": billing_semantic_id,
            "product_id": product,
            "subject": subject.to_public_dict(),
            "request_fingerprint": request_fingerprint,
            "trace_id": wire["trace_id"],
            "estimated_units": estimated_units,
            "occurred_at": _iso(occurred_at),
        }
        request_json = _canonical_json(canonical_request)

        def operation() -> dict[str, Any]:
            existing = _rows(
                self._sql.exec(
                    "SELECT reservation_ref, request_json, admitted, expires_at, created_at "
                    "FROM engine_usage_reservation WHERE idempotency_key=?",
                    idempotency_key,
                )
            )
            if existing:
                if (
                    len(existing) != 1
                    or existing[0]["request_json"] != request_json
                ):
                    raise _error(
                        "usage_reservation_replay_mismatch",
                        "idempotency key was already used for "
                        "different reservation bytes",
                    )
                return {
                    "reservation_ref": str(existing[0]["reservation_ref"]),
                    "admitted": bool(existing[0]["admitted"]),
                    "expires_at": str(existing[0]["expires_at"]),
                    "reserved_at": str(existing[0]["created_at"]),
                }

            try:
                snapshot = self.fetch_entitlement_snapshot(
                    product_id=product,
                    subject=subject.to_public_dict(),
                    now=observed_at,
                )
                grant = snapshot.resolve(billing_semantic_id)
                admitted = bool(
                    grant is not None
                    and grant.allowed
                    and (
                        grant.limit is None
                        or estimated_units <= grant.limit
                    )
                )
                authority_expiry = snapshot.expires_at.astimezone(UTC)
            except ControlPlaneContractError as exc:
                if exc.code != "entitlement_snapshot_unavailable":
                    raise
                admitted = False
                authority_expiry = observed_at + RESERVATION_TTL

            expires_at = min(
                authority_expiry,
                observed_at + RESERVATION_TTL,
            )
            material = "|".join(
                (
                    "engine-usage-reservation-v1",
                    idempotency_key,
                    product,
                    subject.subject_type.value,
                    subject.subject_id,
                    billing_semantic_id,
                    request_fingerprint or "unbound",
                )
            )
            reservation_ref = (
                "cp_res_"
                + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
            )
            self._sql.exec(
                "INSERT INTO engine_usage_reservation "
                "(idempotency_key, reservation_ref, product_id, "
                "subject_type, subject_id, billing_semantic_id, "
                "request_json, admitted, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                idempotency_key,
                reservation_ref,
                product,
                subject.subject_type.value,
                subject.subject_id,
                billing_semantic_id,
                request_json,
                1 if admitted else 0,
                _iso(expires_at),
                _iso(observed_at),
            )
            return {
                "reservation_ref": reservation_ref,
                "admitted": admitted,
                "expires_at": _iso(expires_at),
                "reserved_at": _iso(observed_at),
            }

        return self._storage.transactionSync(operation)

    def record_usage(
        self,
        usage_event: Any,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        event = _usage_event_from_engine_wire(usage_event)
        self._require_product(event.product_id)
        observed_at = _aware(now, "now")
        payload = event.to_public_dict()
        payload["route"] = {
            "status": RouteEvidenceStatus.UNKNOWN.value,
        }
        payload["cost"] = None
        payload_json = _canonical_json(payload)

        def operation() -> dict[str, Any]:
            existing = _rows(
                self._sql.exec(
                    "SELECT event_id, idempotency_key, payload_json "
                    "FROM engine_usage_event "
                    "WHERE event_id=? OR idempotency_key=?",
                    event.event_id,
                    event.idempotency_key,
                )
            )
            if existing:
                if (
                    len(existing) != 1
                    or existing[0]["event_id"] != event.event_id
                    or existing[0]["idempotency_key"]
                    != event.idempotency_key
                    or existing[0]["payload_json"] != payload_json
                ):
                    raise _error(
                        "usage_event_conflict",
                        "usage event identity was already recorded "
                        "with different bytes",
                    )
                return {
                    "accepted": True,
                    "event_id": event.event_id,
                }

            self._sql.exec(
                "INSERT INTO engine_usage_event "
                "(event_id, idempotency_key, product_id, subject_type, "
                "subject_id, billing_semantic_id, payload_json, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                event.event_id,
                event.idempotency_key,
                event.product_id,
                event.subject.subject_type.value,
                event.subject.subject_id,
                event.billing_semantic_id,
                payload_json,
                _iso(observed_at),
            )
            return {
                "accepted": True,
                "event_id": event.event_id,
            }

        return self._storage.transactionSync(operation)

    def _snapshot_from_row(
        self,
        row: Mapping[str, Any],
    ) -> EntitlementSnapshot:
        try:
            grants_raw = json.loads(str(row["grants_json"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise _error(
                "engine_admission_storage_error",
                "stored entitlement grants are invalid",
            ) from exc
        return snapshot_from_wire(
            {
                "snapshot_id": row["snapshot_id"],
                "product_id": row["product_id"],
                "subject": {
                    "subject_type": row["subject_type"],
                    "subject_id": row["subject_id"],
                },
                "revision": row["revision"],
                "issued_at": row["issued_at"],
                "expires_at": row["expires_at"],
                "grants": grants_raw,
            }
        )


CANONICAL_CP_ENTITLEMENT_SOURCE = True
CANONICAL_CP_USAGE_RESERVATION_SOURCE = True
CANONICAL_CP_USAGE_EVENT_SOURCE = True
ENGINE_BILLING_LEDGER = False
CREDIT_BALANCE_IS_ENTITLEMENT_AUTHORITY = False
PUBLIC_ENDPOINT_REQUIRED = False
