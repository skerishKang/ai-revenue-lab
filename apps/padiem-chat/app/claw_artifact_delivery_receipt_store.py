"""#3580 owner-scoped artifact delivery receipt store.

The existing ``ArtifactDeliveryReceipt`` (#3631) is an in-memory contract
object; nothing durable recorded that an artifact had already been delivered.
Without that, a repeated request could deliver the same file twice.

This store adds exactly that record — and nothing else. It is **not** an
approval authority, a connector authority or a second artifact authority:

```text
RESERVATION IS THE DUPLICATE GUARD
  ``reserve`` inserts one row per (owner, conversation, workspace, artifact,
  artifact digest) with a fresh reservation id. If the row already exists the
  caller gets ``existing`` (and the recorded receipt) instead of a second send.

ONE ATTEMPT PER ARTIFACT
  A delivery that may have reached the provider is never retried from here. The
  repository's existing rule is that recovery needs a separately authorized
  reconciler, not a browser retry, so ``existing`` always means "do not send
  again".
```

The D1 reservation is an ``INSERT OR IGNORE ... SELECT`` restricted by BOTH the
owner's conversation and the completed owner run, so a caller-chosen run or a
foreign conversation cannot create a receipt row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from kagent.artifact_delivery_execution_receipt import (
    ArtifactDeliveryReceipt, DeliveryTerminalStatus, terminal_class_for,
)
from .history import _row_to_dict
from .workspace_storage import _safe_identifier

DELIVERY_RECEIPT_CONTRACT_VERSION = "claw-artifact-delivery-receipt.v1"

RESERVATION_NEW = "new"
RESERVATION_EXISTING = "existing"
RESERVATION_REFUSED = "refused"

PENDING_STATUS = "pending"
PENDING_CLASS = "pending"

_MAX_REF_CHARS = 128
_MAX_REASON_CHARS = 200


class ArtifactDeliveryReceiptError(RuntimeError):
    """Store error; never carries a provider body or a credential."""


@dataclass(frozen=True, slots=True)
class DeliveryReservation:
    """Outcome of one reservation attempt.

    ``NEW`` means the caller owns the only attempt for this artifact and may
    proceed. ``EXISTING`` means an attempt is already recorded and **no second
    send may happen**. ``REFUSED`` means the correlation was not valid.
    """

    disposition: str
    receipt: dict[str, Any] | None = None

    @property
    def may_deliver(self) -> bool:
        return self.disposition == RESERVATION_NEW


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, name: str, limit: int = _MAX_REF_CHARS) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ArtifactDeliveryReceiptError(f"{name} must be bounded non-empty text")
    return value


def _optional_text(value: Any, name: str, limit: int = _MAX_REF_CHARS) -> str | None:
    if value is None:
        return None
    return _text(value, name, limit)


class ArtifactDeliveryReceiptStore(Protocol):
    async def reserve(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
        source_run_ref: str, artifact_id: str, artifact_integrity_ref: str,
        delivery_kind: str, connector_id: str, delivery_intent_id: str,
        attempt_ref: str, now: datetime,
    ) -> DeliveryReservation: ...

    async def complete(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
        artifact_id: str, artifact_integrity_ref: str,
        receipt: ArtifactDeliveryReceipt, now: datetime,
    ) -> bool: ...

    async def load(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
        artifact_id: str, artifact_integrity_ref: str,
    ) -> dict[str, Any] | None: ...


def receipt_public_projection(row: dict[str, Any]) -> dict[str, Any]:
    """Sanitized receipt projection for the API response.

    Carries no raw trusted-channel reference, no provider error text, no
    provider id and no artifact bytes.
    """
    status = row.get("terminal_status")
    return {
        "contract_version": DELIVERY_RECEIPT_CONTRACT_VERSION,
        "artifact_id": row.get("artifact_id"),
        "artifact_integrity_ref": row.get("artifact_integrity_ref"),
        "connector_id": row.get("connector_id"),
        "delivery_kind": row.get("delivery_kind"),
        "terminal_status": status,
        "terminal_class": row.get("terminal_class"),
        "external_side_effect_count": int(row.get("external_side_effect_count") or 0),
        "retry_count": int(row.get("retry_count") or 0),
        "receipt_ref": row.get("receipt_ref"),
        "provider_error_kind": row.get("provider_error_kind"),
        "provider_error_retryable": (
            None if row.get("provider_error_retryable") is None
            else bool(row.get("provider_error_retryable"))
        ),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "in_progress": status == PENDING_STATUS,
        "raw_channel_ref_in_projection": False,
        "raw_provider_error_in_projection": False,
        "raw_artifact_bytes": False,
    }


def _receipt_columns(receipt: ArtifactDeliveryReceipt) -> dict[str, Any]:
    if not isinstance(receipt, ArtifactDeliveryReceipt):
        raise ArtifactDeliveryReceiptError("canonical delivery receipt required")
    error = receipt.provider_error
    return {
        "receipt_ref": _optional_text(receipt.receipt_ref, "receipt_ref"),
        "terminal_status": receipt.terminal_status.value,
        "terminal_class": terminal_class_for(receipt.terminal_status).value,
        "external_side_effect_count": int(receipt.external_side_effect_count),
        "retry_count": int(receipt.retry_count),
        "external_result_ref": _optional_text(
            receipt.external_result_ref, "external_result_ref"
        ),
        "provider_error_ref": (
            None if error is None else _optional_text(error.error_ref, "error_ref")
        ),
        "provider_error_kind": None if error is None else error.kind.value,
        "provider_error_retryable": (
            None if error is None else (1 if error.retryable else 0)
        ),
        "started_at": receipt.started_at.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "completed_at": receipt.completed_at.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
    }


_SELECT = (
    "SELECT id, user_id, conversation_id, workspace_id, source_run_ref, "
    "artifact_id, artifact_integrity_ref, delivery_kind, connector_id, "
    "delivery_intent_id, attempt_ref, receipt_ref, terminal_status, "
    "terminal_class, external_side_effect_count, retry_count, external_result_ref, "
    "provider_error_ref, provider_error_kind, provider_error_retryable, "
    "started_at, completed_at, created_at "
    "FROM claw_artifact_delivery_receipts"
)


class D1ArtifactDeliveryReceiptStore:
    """Cloudflare D1 adapter. All dynamic values use prepared statement binds."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _row_to_dict(await statement.first())

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.run()

    async def _select(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
        artifact_id: str, artifact_integrity_ref: str,
    ) -> dict[str, Any] | None:
        return await self._first(
            _SELECT + " WHERE user_id=? AND conversation_id=? AND workspace_id=? "
            "AND artifact_id=? AND artifact_integrity_ref=?",
            owner_id, conversation_id, workspace_ref, artifact_id,
            artifact_integrity_ref,
        )

    async def reserve(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
        source_run_ref: str, artifact_id: str, artifact_integrity_ref: str,
        delivery_kind: str, connector_id: str, delivery_intent_id: str,
        attempt_ref: str, now: datetime,
    ) -> DeliveryReservation:
        owner = _text(owner_id, "owner_id")
        conversation = _text(conversation_id, "conversation_id")
        workspace = _safe_identifier("workspace_ref", workspace_ref)
        run_ref = _text(source_run_ref, "source_run_ref")
        artifact = _text(artifact_id, "artifact_id")
        integrity = _text(artifact_integrity_ref, "artifact_integrity_ref")
        kind = _text(delivery_kind, "delivery_kind", 64)
        connector = _text(connector_id, "connector_id", 64)
        intent_id = _text(delivery_intent_id, "delivery_intent_id")
        attempt = _text(attempt_ref, "attempt_ref")
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ArtifactDeliveryReceiptError("trusted aware time required")

        reservation_id = "dlv_" + uuid.uuid4().hex
        await self._run(
            "INSERT OR IGNORE INTO claw_artifact_delivery_receipts "
            "(id, user_id, conversation_id, workspace_id, source_run_ref, "
            "artifact_id, artifact_integrity_ref, delivery_kind, connector_id, "
            "delivery_intent_id, attempt_ref, terminal_status, terminal_class, "
            "external_side_effect_count, retry_count, created_at) "
            "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ? "
            "FROM conversations c INNER JOIN claw_run_history r "
            "ON r.conversation_id=c.id AND r.user_id=c.user_id "
            "WHERE c.id=? AND c.user_id=? AND r.run_id=? "
            "AND r.workspace_id=? AND r.status='completed'",
            reservation_id, owner, conversation, workspace, run_ref, artifact,
            integrity, kind, connector, intent_id, attempt,
            PENDING_STATUS, PENDING_CLASS, _now_iso(),
            conversation, owner, run_ref, workspace,
        )
        row = await self._select(
            owner_id=owner, conversation_id=conversation, workspace_ref=workspace,
            artifact_id=artifact, artifact_integrity_ref=integrity,
        )
        if row is None:
            return DeliveryReservation(RESERVATION_REFUSED, None)
        if row.get("id") == reservation_id:
            return DeliveryReservation(RESERVATION_NEW, None)
        return DeliveryReservation(RESERVATION_EXISTING, row)

    async def complete(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
        artifact_id: str, artifact_integrity_ref: str,
        receipt: ArtifactDeliveryReceipt, now: datetime,
    ) -> bool:
        columns = _receipt_columns(receipt)
        result = await self._run(
            "UPDATE claw_artifact_delivery_receipts SET "
            "receipt_ref=?, terminal_status=?, terminal_class=?, "
            "external_side_effect_count=?, retry_count=?, external_result_ref=?, "
            "provider_error_ref=?, provider_error_kind=?, "
            "provider_error_retryable=?, started_at=?, completed_at=? "
            "WHERE user_id=? AND conversation_id=? AND workspace_id=? "
            "AND artifact_id=? AND artifact_integrity_ref=? "
            "AND terminal_status=?",
            columns["receipt_ref"], columns["terminal_status"],
            columns["terminal_class"], columns["external_side_effect_count"],
            columns["retry_count"], columns["external_result_ref"],
            columns["provider_error_ref"], columns["provider_error_kind"],
            columns["provider_error_retryable"], columns["started_at"],
            columns["completed_at"],
            owner_id, conversation_id, workspace_ref, artifact_id,
            artifact_integrity_ref, PENDING_STATUS,
        )
        row = await self._select(
            owner_id=owner_id, conversation_id=conversation_id,
            workspace_ref=workspace_ref, artifact_id=artifact_id,
            artifact_integrity_ref=artifact_integrity_ref,
        )
        if row is None:
            return False
        if row.get("terminal_status") == PENDING_STATUS:
            return False
        # A completed row must match exactly what this attempt reported.
        return all(row.get(key) == value for key, value in columns.items())

    async def load(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
        artifact_id: str, artifact_integrity_ref: str,
    ) -> dict[str, Any] | None:
        return await self._select(
            owner_id=owner_id, conversation_id=conversation_id,
            workspace_ref=workspace_ref, artifact_id=artifact_id,
            artifact_integrity_ref=artifact_integrity_ref,
        )


class InMemoryArtifactDeliveryReceiptStore:
    """Network-free store for bounded deployments and conformance tests.

    Same reservation semantics as the D1 store, including "one attempt per
    artifact" and the exact-correlation requirement.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, ...], dict[str, Any]] = {}

    @staticmethod
    def _key(
        owner_id: str, conversation_id: str, workspace_ref: str,
        artifact_id: str, artifact_integrity_ref: str,
    ) -> tuple[str, ...]:
        return (
            _text(owner_id, "owner_id"), _text(conversation_id, "conversation_id"),
            _safe_identifier("workspace_ref", workspace_ref),
            _text(artifact_id, "artifact_id"),
            _text(artifact_integrity_ref, "artifact_integrity_ref"),
        )

    async def reserve(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
        source_run_ref: str, artifact_id: str, artifact_integrity_ref: str,
        delivery_kind: str, connector_id: str, delivery_intent_id: str,
        attempt_ref: str, now: datetime,
    ) -> DeliveryReservation:
        key = self._key(
            owner_id, conversation_id, workspace_ref, artifact_id,
            artifact_integrity_ref,
        )
        existing = self._rows.get(key)
        if existing is not None:
            return DeliveryReservation(RESERVATION_EXISTING, dict(existing))
        self._rows[key] = {
            "id": "dlv_" + uuid.uuid4().hex,
            "user_id": key[0], "conversation_id": key[1], "workspace_id": key[2],
            "source_run_ref": _text(source_run_ref, "source_run_ref"),
            "artifact_id": key[3], "artifact_integrity_ref": key[4],
            "delivery_kind": _text(delivery_kind, "delivery_kind", 64),
            "connector_id": _text(connector_id, "connector_id", 64),
            "delivery_intent_id": _text(delivery_intent_id, "delivery_intent_id"),
            "attempt_ref": _text(attempt_ref, "attempt_ref"),
            "receipt_ref": None, "terminal_status": PENDING_STATUS,
            "terminal_class": PENDING_CLASS, "external_side_effect_count": 0,
            "retry_count": 0, "external_result_ref": None,
            "provider_error_ref": None, "provider_error_kind": None,
            "provider_error_retryable": None, "started_at": None,
            "completed_at": None, "created_at": _now_iso(),
        }
        return DeliveryReservation(RESERVATION_NEW, None)

    async def complete(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
        artifact_id: str, artifact_integrity_ref: str,
        receipt: ArtifactDeliveryReceipt, now: datetime,
    ) -> bool:
        key = self._key(
            owner_id, conversation_id, workspace_ref, artifact_id,
            artifact_integrity_ref,
        )
        row = self._rows.get(key)
        if row is None or row.get("terminal_status") != PENDING_STATUS:
            return False
        row.update(_receipt_columns(receipt))
        return True

    async def load(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
        artifact_id: str, artifact_integrity_ref: str,
    ) -> dict[str, Any] | None:
        row = self._rows.get(self._key(
            owner_id, conversation_id, workspace_ref, artifact_id,
            artifact_integrity_ref,
        ))
        return None if row is None else dict(row)


__all__ = [
    "ArtifactDeliveryReceiptError",
    "ArtifactDeliveryReceiptStore",
    "DELIVERY_RECEIPT_CONTRACT_VERSION",
    "D1ArtifactDeliveryReceiptStore",
    "DeliveryReservation",
    "InMemoryArtifactDeliveryReceiptStore",
    "PENDING_CLASS",
    "PENDING_STATUS",
    "RESERVATION_EXISTING",
    "RESERVATION_NEW",
    "RESERVATION_REFUSED",
    "receipt_public_projection",
]
