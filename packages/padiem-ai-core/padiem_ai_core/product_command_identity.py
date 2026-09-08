"""Product-neutral material identity and idempotency projection for product commands.

This module owns the field classification used when a product-side command
envelope (for example the B54 ``ProductCommandEnvelope``) is projected onto the
shared Core ``IdempotencyAdapter`` contract so duplicate-suppression and
replay/conflict decisions run on the durable Engine authority instead of a
product-local journal.

Field classification follows the same doctrine as ``logical_execution_identity``:
``idempotency_key`` selects the durable record and is therefore excluded from the
material fingerprint; the workspace scope is folded into a deterministic scoped
record key so the same client key can never be shared across workspaces.

Authority boundary:

- Product lifecycle statuses (RECEIVED/DISPATCHED/COMPLETED/FAILED) stay with the
  product application. This module only answers FIRST-RESERVE vs DURABLE-REPLAY
  and fails closed on material conflict.
- Reserving or replaying a command never mints approval, write, or execution
  authority; the projection is metadata-only and carries no raw payload.
- Credential screening of reference material remains the product adapter's
  responsibility upstream of this projection; raw payloads are structurally
  excluded because only a SHA-256 digest participates in identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Mapping

from .execution_context import (
    _safe_idempotency_key,
    _safe_identifier,
    IdempotencyAdapter,
    IdempotencyConflictError,
    request_fingerprint,
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _safe_ref(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ValueError(f"{name} must be a bounded safe reference")
    return value.strip()


def _sha256_hex(value: str, name: str) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return normalized


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ProductCommandIdentity:
    """Material semantics of one product command, free of product enums.

    ``kind`` is a bounded safe identifier string owned by the product; Core
    never canonicalizes product command vocabularies.
    """

    workspace_id: str
    command_id: str
    idempotency_key: str
    kind: str
    subject_ref: str
    subject_version: int
    payload_sha256: str
    session_ref: str | None = None
    requested_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _safe_identifier("workspace_id", self.workspace_id))
        object.__setattr__(self, "command_id", _safe_ref(self.command_id, "command_id"))
        object.__setattr__(self, "idempotency_key", _safe_idempotency_key(self.idempotency_key))
        object.__setattr__(self, "kind", _safe_identifier("kind", self.kind))
        object.__setattr__(self, "subject_ref", _safe_ref(self.subject_ref, "subject_ref"))
        if isinstance(self.subject_version, bool) or not isinstance(self.subject_version, int) or self.subject_version < 1:
            raise ValueError("subject_version must be a positive integer")
        object.__setattr__(self, "payload_sha256", _sha256_hex(self.payload_sha256, "payload_sha256"))
        if self.session_ref is not None:
            object.__setattr__(self, "session_ref", _safe_ref(self.session_ref, "session_ref"))
        if self.requested_at is not None:
            object.__setattr__(self, "requested_at", _aware_utc(self.requested_at, "requested_at"))


def product_command_material_payload(identity: ProductCommandIdentity) -> dict[str, Any]:
    """Return the material command semantics bound into the durable record.

    ``idempotency_key`` is deliberately absent: it selects the record and is
    not execution material, exactly as ``trace_id`` is excluded from the
    logical execution fingerprint.
    """

    if not isinstance(identity, ProductCommandIdentity):
        raise TypeError("identity must be ProductCommandIdentity")
    return {
        "workspace_id": identity.workspace_id,
        "command_id": identity.command_id,
        "kind": identity.kind,
        "subject_ref": identity.subject_ref,
        "subject_version": identity.subject_version,
        "payload_sha256": identity.payload_sha256,
        "session_ref": identity.session_ref,
        "requested_at": identity.requested_at.isoformat() if identity.requested_at is not None else None,
    }


def product_command_material_fingerprint(identity: ProductCommandIdentity) -> str:
    """Return the canonical SHA-256 material identity of one product command."""

    return request_fingerprint(product_command_material_payload(identity))


def product_command_scoped_key(identity: ProductCommandIdentity) -> str:
    """Return the workspace-bound durable record selector for one command.

    The scoped key keeps a client-supplied idempotency key from ever resolving
    to another workspace's durable record: the (workspace, key) pair is folded
    into a bounded lowercase hex digest that satisfies the Core idempotency
    key grammar.
    """

    return request_fingerprint(
        {
            "workspace_id": identity.workspace_id,
            "idempotency_key": identity.idempotency_key,
        }
    )


class ProductCommandReservationOutcome(str, Enum):
    """Durable idempotency verdict for one product command reservation attempt.

    This is not a product lifecycle: product statuses remain owned by the
    calling application.
    """

    ACCEPTED = "accepted"
    REPLAY = "replay"


@dataclass(frozen=True, slots=True)
class ProductCommandReservation:
    """Result of one projection attempt against the shared durable authority."""

    outcome: ProductCommandReservationOutcome
    identity: ProductCommandIdentity
    scoped_idempotency_key: str
    request_fingerprint: str
    replay_result: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ProductCommandReservationOutcome):
            try:
                object.__setattr__(self, "outcome", ProductCommandReservationOutcome(self.outcome))
            except (TypeError, ValueError) as exc:
                raise ValueError("outcome must be a ProductCommandReservationOutcome") from exc
        if not isinstance(self.identity, ProductCommandIdentity):
            raise ValueError("identity must be ProductCommandIdentity")
        object.__setattr__(self, "scoped_idempotency_key", _safe_idempotency_key(self.scoped_idempotency_key))
        object.__setattr__(self, "request_fingerprint", _sha256_hex(self.request_fingerprint, "request_fingerprint"))
        if self.outcome is ProductCommandReservationOutcome.REPLAY and self.replay_result is None:
            raise ValueError("replay reservation must carry the durable replay result")
        if self.outcome is ProductCommandReservationOutcome.ACCEPTED and self.replay_result is not None:
            raise ValueError("accepted reservation must not carry a replay result")
        if self.replay_result is not None:
            object.__setattr__(self, "replay_result", dict(self.replay_result))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.identity.command_id,
            "workspace_id": self.identity.workspace_id,
            "kind": self.identity.kind,
            "outcome": self.outcome.value,
            "request_fingerprint": self.request_fingerprint,
            "replayed": self.outcome is ProductCommandReservationOutcome.REPLAY,
            "raw_payload": False,
            "authorization_granted": False,
            "approval_minted": False,
            "execution_authority_granted": False,
        }


def _replay_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_public = getattr(value, "to_public_dict", None)
    if callable(to_public):
        projected = to_public()
        if isinstance(projected, Mapping):
            return dict(projected)
    raise IdempotencyConflictError("idempotency adapter returned an invalid replay")


class ProductCommandIdempotency:
    """Project product commands onto the shared durable idempotency authority.

    The adapter is required at construction time. This class keeps no local
    record of its own: if the durable adapter is absent or raises, callers fail
    closed and must not dispatch, exactly like ``ContextualExecutionRunner``.
    """

    def __init__(self, *, adapter: IdempotencyAdapter, app_id: str) -> None:
        if adapter is None or not callable(getattr(adapter, "begin", None)):
            raise ValueError("product command idempotency requires an injected IdempotencyAdapter")
        if not callable(getattr(adapter, "complete", None)):
            raise ValueError("product command idempotency adapter must provide complete()")
        if not isinstance(app_id, str) or not app_id.strip():
            raise ValueError("app_id must be a non-empty string")
        self._adapter = adapter
        self._app_id = app_id

    @property
    def app_id(self) -> str:
        return self._app_id

    async def reserve(self, identity: ProductCommandIdentity) -> ProductCommandReservation:
        if not isinstance(identity, ProductCommandIdentity):
            raise TypeError("identity must be ProductCommandIdentity")
        scoped_key = product_command_scoped_key(identity)
        fingerprint = product_command_material_fingerprint(identity)

        read_completed = getattr(self._adapter, "read_completed", None)
        if callable(read_completed):
            completed = await read_completed(
                app_id=self._app_id,
                idempotency_key=scoped_key,
                request_fingerprint=fingerprint,
            )
            if completed is not None:
                return ProductCommandReservation(
                    outcome=ProductCommandReservationOutcome.REPLAY,
                    identity=identity,
                    scoped_idempotency_key=scoped_key,
                    request_fingerprint=fingerprint,
                    replay_result=_replay_mapping(completed),
                )

        replay = await self._adapter.begin(
            app_id=self._app_id,
            idempotency_key=scoped_key,
            request_fingerprint=fingerprint,
        )
        if replay is not None:
            return ProductCommandReservation(
                outcome=ProductCommandReservationOutcome.REPLAY,
                identity=identity,
                scoped_idempotency_key=scoped_key,
                request_fingerprint=fingerprint,
                replay_result=_replay_mapping(replay),
            )
        return ProductCommandReservation(
            outcome=ProductCommandReservationOutcome.ACCEPTED,
            identity=identity,
            scoped_idempotency_key=scoped_key,
            request_fingerprint=fingerprint,
        )

    async def complete(
        self,
        identity: ProductCommandIdentity,
        *,
        result: Mapping[str, Any],
    ) -> None:
        """Seal the durable record with the product result material.

        The result must be a JSON-safe mapping of references (for example a
        bounded ``result_ref``); raw command payloads never enter the durable
        journal through this seam.
        """

        if not isinstance(identity, ProductCommandIdentity):
            raise TypeError("identity must be ProductCommandIdentity")
        if not isinstance(result, Mapping):
            raise ValueError("product command result must be a mapping")
        await self._adapter.complete(
            app_id=self._app_id,
            idempotency_key=product_command_scoped_key(identity),
            request_fingerprint=product_command_material_fingerprint(identity),
            result=dict(result),
        )


PRODUCT_COMMAND_IDEMPOTENCY_AUTHORITY_MINTING = False
