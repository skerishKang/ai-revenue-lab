"""Provider-neutral artifact delivery execution request + receipt contract (#3631, parent #3580).

The artifact chain stops one step short of any real delivery. #3592/#3594
defined ONE canonical artifact, #3599/#3602 the lineage between artifacts,
#3605 the provider-neutral delivery intent and #3621 the trusted
current-channel reference resolver. This module adds the **last model-free
contract** — the boundary an adapter would sit behind — and nothing more:

```text
ArtifactDeliveryIntent      (#3605, unchanged)
+ TrustedChannelReference   (#3621, re-resolved, never trusted as a string)
+ existing approval evidence (opaque ref into the Engine approval authority)
        |
        v
ArtifactDeliveryExecutionRequest        <- this module
        |
        v
ArtifactDeliveryAdapterPort             <- a Protocol, never implemented here
        |
        v
ArtifactDeliveryReceipt                 <- this module
```

This module **does not execute anything**. It defines the request/receipt
boundary and the exact binding between them. There is no adapter
implementation, no transport, no provider client and no network path:

```text
TELEGRAM_ADAPTER=NO
DRIVE_ADAPTER=NO
NETWORK_SEND=0
NETWORK_WRITE=0
DELIVERY_EXECUTION_AUTHORITY=NO
EXTERNAL_SEND_AUTHORITY=NO
```

### Reused, never duplicated

* the **connector binding** authority stays with
  ``kagent.connector_trust.ConnectorBindingProjection`` — consumed through
  #3621's re-resolution, never re-derived here;
* the **artifact** authority stays with #3594/#3602
  (``kagent.artifact_lineage.LineageArtifactRef``);
* the **delivery intent** authority stays with #3605
  (``kagent.artifact_delivery_intent.ArtifactDeliveryIntent``) — this module
  re-declares no intent field and re-exports nothing;
* the **channel resolution** authority stays with #3621
  (``verify_trusted_channel_reference``) — every request is re-resolved
  against the trusted context, so the reference string is never authority;
* the **approval** authority stays with the existing Engine
  approval-continuation authority. ``approval_ref`` is an opaque handle; no
  approval store, state machine or self-approval exists here;
* the **bounded requested action class** is the existing
  ``kagent.artifact_delivery_intent.DeliveryKind`` — no new action vocabulary;
* the **idempotency vocabulary** is the existing
  ``kagent.connector_trust.IdempotencyDisposition`` (``NEW`` /
  ``REPLAY_SAME`` / ``CONFLICT``), and the replay guard below mirrors the
  existing in-memory ``InMemoryWriteIdempotencyRegistry`` pattern. Nothing is
  persisted, so no durable store is introduced;
* the **failure taxonomy** is the existing
  ``kagent.connector_trust.ConnectorProviderError`` /
  ``ConnectorProviderErrorKind``, whose ``retryable`` flag is what separates
  ``FAILED_RETRYABLE`` from ``FAILED_TERMINAL``.

### The reference is re-resolved, never trusted as a token

``trusted_channel_ref`` is a trusted-context-bound opaque reference, not a
capability. A consumer that receives an execution request must **not** treat
the string as authority: :func:`declare_delivery_execution_request` re-resolves
it through #3621 against the trusted context on every call, and fails closed on
a wrong account, wrong workspace, stale context, stale or revoked binding, a
non-matching artifact, a mismatched intent, or tampered reference metadata.

```text
TOKEN_STRING_IS_AUTHORITY=NO
RE_RESOLUTION_REQUIRED=YES
```

### A receipt contract is not send authority

``ArtifactDeliveryReceipt`` existing does **not** authorize an external send.
The receipt records what an already-authorized adapter reported; it grants
nothing. This boundary is pinned in source and asserted by the tests:

```text
SECOND_EXECUTION_AUTHORITY=0
SECOND_REPLAY_AUTHORITY=0
SECOND_APPROVAL_AUTHORITY=0
```

A duplicate or replayed attempt for the same ``attempt_ref`` fails closed
rather than granting a second execution.

### Deliberate boundary: durable-store delivery is not bindable here

#3621's ``TrustedChannelClass`` has exactly two members
(``CURRENT_SURFACE``, ``EXTERNAL_CONNECTOR``). ``DeliveryKind.DURABLE_STORE``
therefore has no #3621 channel class to re-resolve against, and an execution
request for it fails closed rather than inventing a third channel class. That
extension belongs to a separate, explicitly authorized change.

### Structural, not lexical, protection

The request has no destination field, no transport field, no provider field and
no secret field, so no raw chat id, Drive folder/file id, connector credential,
bot token or OAuth refresh token can be carried. Raw destinations and
credential-shaped material are additionally rejected at construction, and the
receipt's ``public_projection()`` withholds the raw ``trusted_channel_ref``,
the raw external-result reference and the raw provider error — matching #3594's
withheld ``location_ref``, #3602's withheld ``working_representation_ref``,
#3605's withheld ``trusted_channel_ref`` and #3621's withheld
``channel_ref``.

Zero network, zero model, zero provider, zero execution: deterministic and
network-free by construction, in the same style as ``artifact_registration``,
``artifact_lineage``, ``artifact_delivery_intent`` and
``trusted_channel_reference``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Protocol, runtime_checkable

from .artifact_delivery_intent import ArtifactDeliveryIntent, DeliveryKind
from .artifact_lineage import LineageArtifactRef
from .connector_trust import ConnectorProviderError, IdempotencyDisposition
from .contracts import ContractError
from .security import redact_secrets
from .trusted_channel_reference import (
    TrustedChannelClass,
    TrustedChannelReference,
    TrustedCurrentChannelContext,
    verify_trusted_channel_reference,
)


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
#: #3621's resolved-reference shape (``tcr1_`` + SHA-256 hex digest). Pinned so a
#: hand-built token cannot masquerade as a resolved trusted reference.
_TRUSTED_CHANNEL_REF_RE = re.compile(r"^tcr1_[0-9a-f]{64}$")
_OPAQUE_REF_MAX_CHARS = 512
_BARE_PROVIDER_ID_RE = re.compile(r"^[+-]?\d{1,32}$")

_CREDENTIAL_PREFIXES = (
    "secret",
    "oauth",
    "token",
    "api_key",
    "apikey",
    "bearer",
    "password",
    "credential",
)

# Invariants of this module's own surface, asserted by the tests.
DELIVERY_EXECUTION_AUTHORITY = False
SECOND_EXECUTION_AUTHORITY = False
SECOND_REPLAY_AUTHORITY = False
SECOND_APPROVAL_AUTHORITY = False
SECOND_CONNECTOR_IDENTITY_AUTHORITY = False
SECOND_ARTIFACT_AUTHORITY = False
REQUEST_BODY_DESTINATION_AUTHORITY = False
TOKEN_STRING_IS_AUTHORITY = False
RE_RESOLUTION_REQUIRED = True
EXTERNAL_SEND_AUTHORITY = False
NETWORK_ACCESS = False
NEW_DURABLE_STORE = False
PROVIDER_NEUTRAL_ADAPTER_PORT_ONLY = True


class ArtifactDeliveryExecutionError(ContractError):
    """Provider-neutral delivery execution request/receipt failure (fail closed)."""


class DeliveryTerminalStatus(str, Enum):
    """Bounded, closed terminal vocabulary for one delivery attempt.

    Deliberately small and provider-neutral: a status says what happened to the
    *attempt*, never which provider was involved.
    """

    SUCCEEDED = "succeeded"
    REFUSED = "refused"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    CANCELLED = "cancelled"


class DeliveryTerminalClass(str, Enum):
    """Coarse class a terminal status belongs to (closed vocabulary)."""

    SUCCESS = "success"
    REFUSAL = "refusal"
    FAILURE = "failure"
    CANCELLATION = "cancellation"


_TERMINAL_CLASS_BY_STATUS: dict[DeliveryTerminalStatus, DeliveryTerminalClass] = {
    DeliveryTerminalStatus.SUCCEEDED: DeliveryTerminalClass.SUCCESS,
    DeliveryTerminalStatus.REFUSED: DeliveryTerminalClass.REFUSAL,
    DeliveryTerminalStatus.FAILED_RETRYABLE: DeliveryTerminalClass.FAILURE,
    DeliveryTerminalStatus.FAILED_TERMINAL: DeliveryTerminalClass.FAILURE,
    DeliveryTerminalStatus.CANCELLED: DeliveryTerminalClass.CANCELLATION,
}

#: #3621 channel class each bindable delivery kind must re-resolve to.
#: ``DeliveryKind.DURABLE_STORE`` is intentionally absent (see module docstring).
_CHANNEL_CLASS_BY_DELIVERY_KIND: dict[DeliveryKind, TrustedChannelClass] = {
    DeliveryKind.CURRENT_SURFACE: TrustedChannelClass.CURRENT_SURFACE,
    DeliveryKind.EXTERNAL_CONNECTOR: TrustedChannelClass.EXTERNAL_CONNECTOR,
}

_TERMINAL_STATUSES_REQUIRING_PROVIDER_ERROR = frozenset(
    {DeliveryTerminalStatus.FAILED_RETRYABLE, DeliveryTerminalStatus.FAILED_TERMINAL}
)


def terminal_class_for(status: DeliveryTerminalStatus | str) -> DeliveryTerminalClass:
    """Map a terminal status onto its closed terminal class."""
    try:
        coerced = DeliveryTerminalStatus(status)
    except (TypeError, ValueError) as exc:
        raise ArtifactDeliveryExecutionError("unsupported terminal status") from exc
    return _TERMINAL_CLASS_BY_STATUS[coerced]


def _bounded_id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ArtifactDeliveryExecutionError(f"{field_name} must be a bounded safe identifier")
    value = value.strip()
    if _CONTROL_RE.search(value):
        raise ArtifactDeliveryExecutionError(f"{field_name} must not contain control characters")
    return value


def _bounded_ref(value: str, field_name: str) -> str:
    """Identifier-semantics provenance ref (workspace_ref / run_ref).

    Consumed from the existing run/workspace authority: no URL scheme, no
    credential-shaped prefix, no traversal or control characters.
    """
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ArtifactDeliveryExecutionError(f"{field_name} must be a bounded safe identifier")
    value = value.strip()
    if _CONTROL_RE.search(value) or ".." in value:
        raise ArtifactDeliveryExecutionError(
            f"{field_name} must not contain traversal or control characters"
        )
    lowered = value.lower()
    if "://" in lowered or ":" in value:
        raise ArtifactDeliveryExecutionError(
            f"{field_name} must be an identifier, not a URL or scheme-prefixed token"
        )
    if any(lowered.startswith(prefix) for prefix in _CREDENTIAL_PREFIXES):
        raise ArtifactDeliveryExecutionError(f"{field_name} must not carry credential-like material")
    return value


def _opaque_ref(value: str, field_name: str) -> str:
    """Opaque, provider-neutral handle (approval_ref / external_result_ref).

    The value's meaning belongs to the authority that issued it; this contract
    never interprets it. Local references, ``file://`` URIs, URLs with
    query/fragment material, whitespace/credential material, credential-like
    prefixes and bare numeric provider ids all fail closed. This is a secondary
    guard — the structural protection is that the schema has no provider field.
    """
    if not isinstance(value, str) or not value.strip():
        raise ArtifactDeliveryExecutionError(f"{field_name} must be non-empty text")
    value = value.strip()
    if len(value) > _OPAQUE_REF_MAX_CHARS or _CONTROL_RE.search(value):
        raise ArtifactDeliveryExecutionError(f"{field_name} must be bounded control-free text")
    lowered = value.lower()
    if (
        re.match(r"^[A-Za-z]:[\\/]", value)
        or value.startswith(("\\\\", "/", "file:", "file://"))
        or "file://" in lowered
        or "://" in lowered
        or ".." in value
        or "?" in value
        or "#" in value
        or " " in value
        or "=" in value
        or ";" in value
        or "," in value
        or ":" in value
        or lowered.startswith(("bearer ", "basic ", "token "))
    ):
        raise ArtifactDeliveryExecutionError(
            f"{field_name} must be an opaque reference without URL/credential/local-path material"
        )
    for prefix in _CREDENTIAL_PREFIXES:
        if lowered.startswith(prefix + ":"):
            raise ArtifactDeliveryExecutionError(
                f"{field_name} must not carry credential-like material"
            )
    if _BARE_PROVIDER_ID_RE.fullmatch(value):
        raise ArtifactDeliveryExecutionError(
            f"{field_name} must be an opaque reference, not a bare provider id"
        )
    if redact_secrets(value) != value:
        raise ArtifactDeliveryExecutionError(
            f"{field_name} must not carry credential-like material"
        )
    return value


def _trusted_channel_ref(value: str, field_name: str) -> str:
    """A #3621-resolved reference handle (``tcr1_`` + digest).

    Pinned by shape so a hand-built string cannot pass for a resolved reference.
    Authority still comes from re-resolution, never from this value.
    """
    if not isinstance(value, str) or not _TRUSTED_CHANNEL_REF_RE.fullmatch(value.strip()):
        raise ArtifactDeliveryExecutionError(
            f"{field_name} must be a resolved trusted channel reference handle"
        )
    return value.strip()


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ArtifactDeliveryExecutionError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _non_negative_int(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactDeliveryExecutionError(f"{field_name} must be a non-negative integer")
    return value


def _coerce_artifact_ref(value: Any) -> LineageArtifactRef:
    if not isinstance(value, LineageArtifactRef):
        raise ArtifactDeliveryExecutionError("artifact_ref must be a LineageArtifactRef")
    return value


@dataclass(frozen=True, slots=True)
class ArtifactDeliveryExecutionRequest:
    """One bounded request to deliver an already-registered artifact.

    Inert metadata. It carries only refs that already exist in the chain — no
    destination, no transport, no provider field, no secret. Construct it with
    :func:`declare_delivery_execution_request`, which performs the trusted
    re-resolution; a hand-built request still cannot carry authority because the
    reference shape is pinned and re-resolution is required by every consumer.
    """

    attempt_ref: str
    delivery_intent_id: str
    artifact_ref: LineageArtifactRef
    delivery_kind: DeliveryKind
    trusted_channel_ref: str
    workspace_ref: str
    run_ref: str
    requested_at: datetime
    channel_binding_ref: str | None = None
    approval_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_ref", _bounded_id(self.attempt_ref, "attempt_ref"))
        object.__setattr__(
            self,
            "delivery_intent_id",
            _bounded_id(self.delivery_intent_id, "delivery_intent_id"),
        )
        object.__setattr__(self, "artifact_ref", _coerce_artifact_ref(self.artifact_ref))
        if not isinstance(self.delivery_kind, DeliveryKind):
            try:
                object.__setattr__(self, "delivery_kind", DeliveryKind(self.delivery_kind))
            except (TypeError, ValueError) as exc:
                raise ArtifactDeliveryExecutionError("invalid delivery kind") from exc
        object.__setattr__(
            self,
            "trusted_channel_ref",
            _trusted_channel_ref(self.trusted_channel_ref, "trusted_channel_ref"),
        )
        object.__setattr__(self, "workspace_ref", _bounded_ref(self.workspace_ref, "workspace_ref"))
        object.__setattr__(self, "run_ref", _bounded_ref(self.run_ref, "run_ref"))
        object.__setattr__(self, "requested_at", _aware_utc(self.requested_at, "requested_at"))
        if self.channel_binding_ref is not None:
            object.__setattr__(
                self,
                "channel_binding_ref",
                _opaque_ref(self.channel_binding_ref, "channel_binding_ref"),
            )
        if self.approval_ref is not None:
            object.__setattr__(self, "approval_ref", _opaque_ref(self.approval_ref, "approval_ref"))

        if self.delivery_kind not in _CHANNEL_CLASS_BY_DELIVERY_KIND:
            raise ArtifactDeliveryExecutionError(
                "delivery kind has no trusted channel class to re-resolve against"
            )
        if (
            self.delivery_kind is DeliveryKind.EXTERNAL_CONNECTOR
            and self.channel_binding_ref is None
        ):
            raise ArtifactDeliveryExecutionError(
                "external connector delivery must name the existing channel binding authority"
            )
        if (
            self.delivery_kind is DeliveryKind.CURRENT_SURFACE
            and self.channel_binding_ref is not None
        ):
            raise ArtifactDeliveryExecutionError(
                "current-surface delivery must not carry a connector binding ref"
            )

    @property
    def artifact_id(self) -> str:
        return self.artifact_ref.artifact_id

    @property
    def artifact_integrity_ref(self) -> str:
        return self.artifact_ref.integrity_ref

    def stable_identity(self) -> tuple[str, ...]:
        """Identity used for the duplicate/replay decision.

        Excludes ``requested_at`` on purpose: the same logical attempt retried at
        a later timestamp is the same attempt.
        """
        return (
            self.delivery_intent_id,
            self.artifact_ref.artifact_id,
            self.artifact_ref.integrity_ref,
            self.delivery_kind.value,
            self.trusted_channel_ref,
            self.workspace_ref,
            self.run_ref,
            self.channel_binding_ref or "",
            self.approval_ref or "",
        )

    def public_projection(self) -> dict[str, Any]:
        """JSON-safe metadata-only projection.

        The raw ``trusted_channel_ref`` is withheld (matching #3594/#3602/#3605/
        #3621); only its presence is projected. This projection carries no
        origin attestation for the reference and grants no authority: this
        module has no execution path.
        """
        return {
            "contract_version": "claw-artifact-delivery-execution-request.v1",
            "attempt_ref": self.attempt_ref,
            "delivery_intent_id": self.delivery_intent_id,
            "artifact_id": self.artifact_ref.artifact_id,
            "artifact_integrity_ref": self.artifact_ref.integrity_ref,
            "delivery_kind": self.delivery_kind.value,
            "workspace_ref": self.workspace_ref,
            "run_ref": self.run_ref,
            "requested_at": _iso(self.requested_at),
            "trusted_channel_ref_present": True,
            "channel_binding_ref_present": self.channel_binding_ref is not None,
            "approval_ref_present": self.approval_ref is not None,
            "raw_channel_ref_in_projection": False,
            "raw_destination_in_projection": False,
            "delivery_execution": False,
            "send_write_authority": False,
        }


@dataclass(frozen=True, slots=True)
class ArtifactDeliveryReceipt:
    """Provider-neutral terminal receipt for one delivery attempt.

    Records what an already-authorized adapter reported. It grants no authority:
    a receipt existing is not send permission. ``terminal_class`` is derived from
    ``terminal_status`` so the two can never disagree.
    """

    receipt_ref: str
    attempt_ref: str
    delivery_intent_id: str
    artifact_ref: LineageArtifactRef
    trusted_channel_ref: str
    terminal_status: DeliveryTerminalStatus
    started_at: datetime
    completed_at: datetime
    retry_count: int = 0
    external_side_effect_count: int = 0
    external_result_ref: str | None = None
    provider_error: ConnectorProviderError | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_ref", _bounded_id(self.receipt_ref, "receipt_ref"))
        object.__setattr__(self, "attempt_ref", _bounded_id(self.attempt_ref, "attempt_ref"))
        object.__setattr__(
            self,
            "delivery_intent_id",
            _bounded_id(self.delivery_intent_id, "delivery_intent_id"),
        )
        object.__setattr__(self, "artifact_ref", _coerce_artifact_ref(self.artifact_ref))
        object.__setattr__(
            self,
            "trusted_channel_ref",
            _trusted_channel_ref(self.trusted_channel_ref, "trusted_channel_ref"),
        )
        if not isinstance(self.terminal_status, DeliveryTerminalStatus):
            try:
                object.__setattr__(
                    self, "terminal_status", DeliveryTerminalStatus(self.terminal_status)
                )
            except (TypeError, ValueError) as exc:
                raise ArtifactDeliveryExecutionError("unsupported terminal status") from exc

        started = _aware_utc(self.started_at, "started_at")
        completed = _aware_utc(self.completed_at, "completed_at")
        if completed < started:
            raise ArtifactDeliveryExecutionError("completed_at cannot precede started_at")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "completed_at", completed)

        object.__setattr__(self, "retry_count", _non_negative_int(self.retry_count, "retry_count"))
        object.__setattr__(
            self,
            "external_side_effect_count",
            _non_negative_int(self.external_side_effect_count, "external_side_effect_count"),
        )
        if self.external_result_ref is not None:
            object.__setattr__(
                self,
                "external_result_ref",
                _opaque_ref(self.external_result_ref, "external_result_ref"),
            )
        if self.provider_error is not None and not isinstance(
            self.provider_error, ConnectorProviderError
        ):
            raise ArtifactDeliveryExecutionError(
                "provider_error must be a ConnectorProviderError or None"
            )

        # A refusal means the adapter never acted, so it cannot have produced an
        # external side effect.
        if (
            self.terminal_status is DeliveryTerminalStatus.REFUSED
            and self.external_side_effect_count != 0
        ):
            raise ArtifactDeliveryExecutionError(
                "a refused delivery cannot report an external side effect"
            )

        # The reused failure taxonomy carries the retryable bit, so it must agree
        # with the terminal status rather than restate a second opinion.
        if self.terminal_status in _TERMINAL_STATUSES_REQUIRING_PROVIDER_ERROR:
            if self.provider_error is None:
                raise ArtifactDeliveryExecutionError(
                    "a failed delivery must carry the provider error taxonomy"
                )
            expected_retryable = self.terminal_status is DeliveryTerminalStatus.FAILED_RETRYABLE
            if self.provider_error.retryable is not expected_retryable:
                raise ArtifactDeliveryExecutionError(
                    "provider error retryable flag disagrees with the terminal status"
                )
        elif self.provider_error is not None:
            raise ArtifactDeliveryExecutionError(
                "a non-failed delivery must not carry a provider error"
            )

    @property
    def artifact_id(self) -> str:
        return self.artifact_ref.artifact_id

    @property
    def artifact_integrity_ref(self) -> str:
        return self.artifact_ref.integrity_ref

    @property
    def terminal_class(self) -> DeliveryTerminalClass:
        return _TERMINAL_CLASS_BY_STATUS[self.terminal_status]

    def correlates_with(self, request: ArtifactDeliveryExecutionRequest) -> bool:
        """Exact correlation with the request that produced this receipt."""
        if not isinstance(request, ArtifactDeliveryExecutionRequest):
            raise ArtifactDeliveryExecutionError(
                "request must be an ArtifactDeliveryExecutionRequest"
            )
        return (
            self.attempt_ref == request.attempt_ref
            and self.delivery_intent_id == request.delivery_intent_id
            and self.artifact_ref == request.artifact_ref
            and self.trusted_channel_ref == request.trusted_channel_ref
        )

    def public_projection(self) -> dict[str, Any]:
        """JSON-safe metadata-only projection.

        The raw ``trusted_channel_ref``, the raw external-result reference and
        the raw provider error are withheld; only presence is projected. No
        credential, destination id or artifact byte can appear here.
        """
        return {
            "contract_version": "claw-artifact-delivery-receipt.v1",
            "receipt_ref": self.receipt_ref,
            "attempt_ref": self.attempt_ref,
            "delivery_intent_id": self.delivery_intent_id,
            "artifact_id": self.artifact_ref.artifact_id,
            "artifact_integrity_ref": self.artifact_ref.integrity_ref,
            "terminal_status": self.terminal_status.value,
            "terminal_class": self.terminal_class.value,
            "started_at": _iso(self.started_at),
            "completed_at": _iso(self.completed_at),
            "retry_count": self.retry_count,
            "external_side_effect_count": self.external_side_effect_count,
            "trusted_channel_ref_present": True,
            "external_result_ref_present": self.external_result_ref is not None,
            "provider_error_present": self.provider_error is not None,
            "provider_error_retryable": (
                self.provider_error.retryable if self.provider_error is not None else None
            ),
            "raw_channel_ref_in_projection": False,
            "raw_external_result_ref_in_projection": False,
            "raw_provider_error_in_projection": False,
            "raw_destination_in_projection": False,
            "connector_secret_in_projection": False,
            "artifact_bytes_in_projection": False,
            "delivery_execution": False,
            "send_write_authority": False,
        }


@runtime_checkable
class ArtifactDeliveryAdapterPort(Protocol):
    """Provider-neutral execution port an authorized adapter would implement.

    Deliberately a Protocol with **no implementation in this module**: this child
    defines the boundary, not an adapter. A real implementation is separate,
    explicitly authorized work (a Telegram document send, or a Drive
    write/upload).
    """

    def deliver(
        self,
        request: ArtifactDeliveryExecutionRequest,
    ) -> ArtifactDeliveryReceipt:  # pragma: no cover - structural port only
        ...


class InMemoryDeliveryAttemptRegistry:
    """Deterministic, in-memory duplicate/replay guard for delivery attempts.

    Reuses the existing ``IdempotencyDisposition`` vocabulary and mirrors the
    existing ``InMemoryWriteIdempotencyRegistry`` pattern. Nothing is persisted,
    so this introduces no durable store. Admission is fail-closed: a replay or a
    conflicting reuse of an ``attempt_ref`` is refused rather than granted a
    second execution.
    """

    def __init__(self) -> None:
        self._seen: dict[str, tuple[str, ...]] = {}

    def disposition(
        self, request: ArtifactDeliveryExecutionRequest
    ) -> IdempotencyDisposition:
        if not isinstance(request, ArtifactDeliveryExecutionRequest):
            raise ArtifactDeliveryExecutionError(
                "request must be an ArtifactDeliveryExecutionRequest"
            )
        identity = request.stable_identity()
        existing = self._seen.get(request.attempt_ref)
        if existing is None:
            self._seen[request.attempt_ref] = identity
            return IdempotencyDisposition.NEW
        if existing == identity:
            return IdempotencyDisposition.REPLAY_SAME
        return IdempotencyDisposition.CONFLICT

    def admit(self, request: ArtifactDeliveryExecutionRequest) -> None:
        """Admit a first attempt; fail closed on any duplicate or conflict."""
        outcome = self.disposition(request)
        if outcome is IdempotencyDisposition.REPLAY_SAME:
            raise ArtifactDeliveryExecutionError(
                "delivery attempt replay is refused; a second execution is not authorized"
            )
        if outcome is IdempotencyDisposition.CONFLICT:
            raise ArtifactDeliveryExecutionError(
                "attempt_ref is already bound to a different delivery attempt"
            )


def declare_delivery_execution_request(
    *,
    attempt_ref: str,
    intent: ArtifactDeliveryIntent,
    reference: TrustedChannelReference | str,
    context: TrustedCurrentChannelContext | None,
    now: datetime,
    expected_account_ref: str,
    expected_workspace_ref: str,
    supported_connector_ids: Iterable[str] | None = None,
    artifact_ref: Any | None = None,
    approval_ref: str | None = None,
    caller_destination: str | None = None,
    caller_channel_label: str | None = None,
) -> ArtifactDeliveryExecutionRequest:
    """Bind an existing #3605 intent to a re-resolved trusted channel reference.

    Fails closed when the trusted context is missing/malformed, the account or
    workspace does not match, the context or binding is stale/expired/revoked,
    the reference is forged/unknown/expired/tampered, the artifact or intent does
    not match, the delivery kind has no channel class, or a caller tries to
    supply a destination or a channel label as authority.
    """

    current = _aware_utc(now, "now")

    if not isinstance(intent, ArtifactDeliveryIntent):
        raise ArtifactDeliveryExecutionError("intent must be an ArtifactDeliveryIntent")

    # A request-body destination is never authority; there is no parameter for it.
    if caller_destination is not None:
        raise ArtifactDeliveryExecutionError(
            "a caller-supplied destination is not delivery authority"
        )

    if artifact_ref is not None:
        candidate_artifact = _coerce_artifact_ref(artifact_ref)
        if candidate_artifact != intent.artifact_ref:
            raise ArtifactDeliveryExecutionError(
                "requested artifact does not match the delivery intent artifact"
            )

    expected_channel_class = _CHANNEL_CLASS_BY_DELIVERY_KIND.get(intent.delivery_kind)
    if expected_channel_class is None:
        raise ArtifactDeliveryExecutionError(
            "delivery kind has no trusted channel class to re-resolve against"
        )

    # Authority comes from re-resolution against the trusted context, never from
    # the reference string the caller handed us.
    resolved = verify_trusted_channel_reference(
        reference,
        context,
        now=current,
        expected_account_ref=expected_account_ref,
        expected_workspace_ref=expected_workspace_ref,
        supported_connector_ids=supported_connector_ids,
    )

    if resolved.channel_class is not expected_channel_class:
        raise ArtifactDeliveryExecutionError(
            "resolved channel class does not match the delivery intent kind"
        )
    if intent.trusted_channel_ref != resolved.channel_ref:
        raise ArtifactDeliveryExecutionError(
            "delivery intent does not reference this trusted channel"
        )
    if intent.workspace_ref != resolved.workspace_ref:
        raise ArtifactDeliveryExecutionError(
            "delivery intent workspace does not match the resolved channel workspace"
        )
    if intent.channel_binding_ref != resolved.binding_ref:
        raise ArtifactDeliveryExecutionError(
            "delivery intent binding does not match the resolved channel binding"
        )

    # A request-body channel label is never authority. It is only allowed to agree.
    if caller_channel_label is not None:
        label = caller_channel_label.strip().lower() if isinstance(caller_channel_label, str) else ""
        if label != resolved.channel_class.value:
            raise ArtifactDeliveryExecutionError(
                "caller-supplied channel label is not delivery authority"
            )

    # The approval handle is consumed from the existing authority; a caller may
    # not substitute a different one.
    effective_approval_ref = intent.approval_ref
    if approval_ref is not None:
        normalized = _opaque_ref(approval_ref, "approval_ref")
        if normalized != intent.approval_ref:
            raise ArtifactDeliveryExecutionError(
                "approval reference does not match the delivery intent approval"
            )
        effective_approval_ref = normalized

    return ArtifactDeliveryExecutionRequest(
        attempt_ref=attempt_ref,
        delivery_intent_id=intent.delivery_intent_id,
        artifact_ref=intent.artifact_ref,
        delivery_kind=intent.delivery_kind,
        trusted_channel_ref=resolved.channel_ref,
        workspace_ref=resolved.workspace_ref,
        run_ref=intent.run_ref,
        requested_at=current,
        channel_binding_ref=resolved.binding_ref,
        approval_ref=effective_approval_ref,
    )


def build_delivery_receipt(
    *,
    receipt_ref: str,
    request: ArtifactDeliveryExecutionRequest,
    terminal_status: DeliveryTerminalStatus,
    started_at: datetime,
    completed_at: datetime,
    retry_count: int = 0,
    external_side_effect_count: int = 0,
    external_result_ref: str | None = None,
    provider_error: ConnectorProviderError | None = None,
) -> ArtifactDeliveryReceipt:
    """Build a receipt whose correlation is copied exactly from the request.

    The correlation fields are derived from the request rather than accepted from
    the caller, so a receipt can never be pointed at another attempt, artifact or
    channel.
    """

    if not isinstance(request, ArtifactDeliveryExecutionRequest):
        raise ArtifactDeliveryExecutionError(
            "request must be an ArtifactDeliveryExecutionRequest"
        )

    return ArtifactDeliveryReceipt(
        receipt_ref=receipt_ref,
        attempt_ref=request.attempt_ref,
        delivery_intent_id=request.delivery_intent_id,
        artifact_ref=request.artifact_ref,
        trusted_channel_ref=request.trusted_channel_ref,
        terminal_status=terminal_status,
        started_at=started_at,
        completed_at=completed_at,
        retry_count=retry_count,
        external_side_effect_count=external_side_effect_count,
        external_result_ref=external_result_ref,
        provider_error=provider_error,
    )
