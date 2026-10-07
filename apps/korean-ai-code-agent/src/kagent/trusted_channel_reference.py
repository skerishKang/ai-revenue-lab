"""Trusted current-channel reference resolver (#3621, parent #3580).

The artifact chain already stops one step short of any real delivery:

```text
CanonicalArtifactRecord        (#3592/#3594, kagent.artifact_registration)
  -> ArtifactLineage           (#3599/#3602, kagent.artifact_lineage)
  -> ArtifactDeliveryIntent    (#3605, kagent.artifact_delivery_intent)
       trusted_channel_ref: CONSUMED, never minted
  -> ???                       <- this module
```

#3605 documents that the *origin* of ``trusted_channel_ref`` "is an input
precondition guaranteed by that authority" and that it "adds no resolver". This
module is exactly that missing step — and nothing more.

```text
trusted runtime context (already authenticated)
  account_ref + workspace_ref + conversation_ref + channel class
  + existing ConnectorBindingProjection   (connector classes only)
        |
        v
  TrustedChannelReference      opaque, bound, expiry-aware
        |
        v
  ArtifactDeliveryIntent.trusted_channel_ref   (#3605, unchanged)
```

### Reused, never duplicated

* the connector **binding** authority is
  ``kagent.connector_trust.ConnectorBindingProjection`` — its ``binding_ref``,
  ``connector_id``, ``account_ref``, ``workspace_ref``, ``expires_at`` and
  ``state`` (via ``usable_at``) are consumed as-is. No second connector
  identity authority is created, and no binding is stored or persisted here;
* the **conversation/channel** identity is an opaque ``conversation_ref`` the
  trusted host already holds (the same role ``chat_ref`` plays in
  ``kagent.telegram_contracts.TelegramPairedChat``). This module never derives a
  provider chat id;
* the **artifact** authority stays in #3594: the bridge below calls the
  existing ``declare_delivery_intent`` and re-declares no artifact field.

### What this module refuses to do

A request-body label such as ``channel=telegram`` is **not** delivery
authority. This module has no destination parameter, no transport parameter, no
secret access and no send/write path:

```text
TELEGRAM_SEND=NO
DRIVE_WRITE=NO
AUTO_EXTERNAL_SEND=NO
CONNECTOR_SECRET_READ=NO
REQUEST_BODY_CHANNEL_LABEL_AUTHORITY=NO
SECOND_CONNECTOR_IDENTITY_AUTHORITY=0
SECOND_ARTIFACT_AUTHORITY=0
```

Zero network, zero model, zero provider, zero execution: deterministic and
network-free by construction, in the same style as ``artifact_registration``,
``artifact_lineage`` and ``artifact_delivery_intent``.

### The reference is a binding digest, not a capability

``channel_ref`` is a deterministic digest over the trusted context's own opaque
refs. It is **not** a bearer token and carries no authority by itself: every
consumer must re-resolve against a trusted context with
``verify_trusted_channel_reference``. Nothing here reads or needs a secret, so
no key/secret authority is introduced either.

### Origin is an input precondition, not an attestation

This module validates and binds a context the **existing trusted host** already
holds. It cannot mechanically prove who produced that context, and it makes no
provenance claim anywhere, including in ``public_projection()``. The origin
guarantee stays an input precondition owned by the existing host/binding
authority — exactly as #3605 already documents for ``trusted_channel_ref``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .artifact_delivery_intent import (
    ArtifactDeliveryIntent,
    DeliveryKind,
    declare_delivery_intent,
)
from .connector_trust import ConnectorBindingProjection
from .contracts import ContractError


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_CHANNEL_REF_RE = re.compile(r"^tcr1_[0-9a-f]{64}$")
_REF_PREFIX = "tcr1"

# Bounded staleness window for a host-observed context. A context older than
# this is refused rather than resolved: a stale "current channel" is a guess.
MAX_CONTEXT_AGE = timedelta(minutes=15)

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
TRUSTED_CHANNEL_REF_IS_OPAQUE = True
REQUEST_BODY_CHANNEL_LABEL_IS_AUTHORITY = False
SECOND_CONNECTOR_IDENTITY_AUTHORITY = False
SECOND_ARTIFACT_AUTHORITY = False
EXTERNAL_SEND_AUTHORITY = False


class TrustedChannelReferenceError(ContractError):
    """Trusted current-channel reference resolution failure (fail closed)."""


class TrustedChannelClass(str, Enum):
    """Provider-neutral class of the caller's *current* channel.

    ``CURRENT_SURFACE``    the caller's already-authenticated in-app surface;
    ``EXTERNAL_CONNECTOR`` delivery through a separately authorized connector,
                           which must name the existing connector binding.

    Deliberately not a provider name: "telegram"/"drive" are never values here.
    """

    CURRENT_SURFACE = "current_surface"
    EXTERNAL_CONNECTOR = "external_connector"


SUPPORTED_CHANNEL_CLASSES: tuple[TrustedChannelClass, ...] = (
    TrustedChannelClass.CURRENT_SURFACE,
    TrustedChannelClass.EXTERNAL_CONNECTOR,
)


def _bounded_ref(value: str, field_name: str) -> str:
    """Opaque identity token consumed from an existing authority.

    Identifier semantics only: no URL scheme, no credential-shaped prefix, no
    traversal or control characters. These are never addresses.
    """
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise TrustedChannelReferenceError(f"{field_name} must be a bounded safe identifier")
    value = value.strip()
    if _CONTROL_RE.search(value) or ".." in value:
        raise TrustedChannelReferenceError(
            f"{field_name} must not contain traversal or control characters"
        )
    lowered = value.lower()
    if "://" in lowered or ":" in value:
        raise TrustedChannelReferenceError(
            f"{field_name} must be an identifier, not a URL or scheme-prefixed token"
        )
    if any(lowered.startswith(prefix) for prefix in _CREDENTIAL_PREFIXES):
        raise TrustedChannelReferenceError(f"{field_name} must not carry credential-like material")
    return value


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TrustedChannelReferenceError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_channel_class(value: Any) -> TrustedChannelClass:
    if isinstance(value, TrustedChannelClass):
        return value
    try:
        return TrustedChannelClass(value)
    except (TypeError, ValueError) as exc:
        raise TrustedChannelReferenceError("unsupported channel class") from exc


def _bounded_connector_ids(values: Iterable[str] | None) -> tuple[str, ...]:
    """Bounded connector-id allowlist consumed from the existing catalogue."""
    if values is None:
        return ()
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise TrustedChannelReferenceError("supported_connector_ids must be an iterable of ids")
    normalized: list[str] = []
    for value in values:
        normalized.append(_bounded_ref(value, "supported_connector_id"))
    if len(set(normalized)) != len(normalized):
        raise TrustedChannelReferenceError("supported_connector_ids values must be unique")
    if len(normalized) > 64:
        raise TrustedChannelReferenceError("supported_connector_ids is bounded to 64 entries")
    return tuple(normalized)


def supported_connector_ids_from_catalogue(entries: Iterable[Any]) -> tuple[str, ...]:
    """Read the bounded connector-id set from existing catalogue entries.

    Consumes ``kagent.connector_platform.ConnectorCatalogueEntry`` values (or
    anything exposing ``connector_id``) so this module never hard-codes a
    provider list and never mints a connector identity of its own.
    """
    ids: list[str] = []
    for entry in entries:
        connector_id = getattr(entry, "connector_id", None)
        if connector_id is None:
            raise TrustedChannelReferenceError("catalogue entry is missing connector_id")
        ids.append(_bounded_ref(connector_id, "connector_id"))
    return _bounded_connector_ids(ids)


@dataclass(frozen=True, slots=True)
class TrustedCurrentChannelContext:
    """What the trusted runtime already holds for the authenticated request.

    Supplied by the host. There is deliberately **no** destination field: the
    conversation is an opaque ref, and an external-connector context names the
    existing ``ConnectorBindingProjection`` that resolved it.
    """

    account_ref: str
    workspace_ref: str
    conversation_ref: str
    channel_class: TrustedChannelClass
    observed_at: datetime
    binding: ConnectorBindingProjection | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_ref", _bounded_ref(self.account_ref, "account_ref"))
        object.__setattr__(self, "workspace_ref", _bounded_ref(self.workspace_ref, "workspace_ref"))
        object.__setattr__(
            self, "conversation_ref", _bounded_ref(self.conversation_ref, "conversation_ref")
        )
        channel_class = _coerce_channel_class(self.channel_class)
        object.__setattr__(self, "channel_class", channel_class)
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, "observed_at"))
        if self.binding is not None and not isinstance(self.binding, ConnectorBindingProjection):
            raise TrustedChannelReferenceError(
                "binding must be a ConnectorBindingProjection or None"
            )
        # Fail closed rather than guess a destination: an external connector
        # class without the existing binding authority has nothing to resolve.
        if channel_class is TrustedChannelClass.EXTERNAL_CONNECTOR and self.binding is None:
            raise TrustedChannelReferenceError(
                "external connector channel class requires the existing connector binding"
            )


@dataclass(frozen=True, slots=True)
class TrustedChannelReference:
    """Opaque, bound, expiry-aware handle to the caller's current channel.

    ``channel_ref`` is a deterministic digest over this context's own opaque
    refs. It is a *binding digest*, not a capability: consumers must re-resolve
    with :func:`verify_trusted_channel_reference`.
    """

    channel_ref: str
    channel_class: TrustedChannelClass
    account_ref: str
    workspace_ref: str
    conversation_ref: str
    resolved_at: datetime
    binding_ref: str | None = None
    connector_id: str | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.channel_ref, str) or not _CHANNEL_REF_RE.fullmatch(
            self.channel_ref.strip()
        ):
            raise TrustedChannelReferenceError("channel_ref must be an opaque resolved reference")
        object.__setattr__(self, "channel_ref", self.channel_ref.strip())
        object.__setattr__(self, "channel_class", _coerce_channel_class(self.channel_class))
        object.__setattr__(self, "account_ref", _bounded_ref(self.account_ref, "account_ref"))
        object.__setattr__(self, "workspace_ref", _bounded_ref(self.workspace_ref, "workspace_ref"))
        object.__setattr__(
            self, "conversation_ref", _bounded_ref(self.conversation_ref, "conversation_ref")
        )
        object.__setattr__(self, "resolved_at", _aware_utc(self.resolved_at, "resolved_at"))
        if self.binding_ref is not None:
            object.__setattr__(self, "binding_ref", _bounded_ref(self.binding_ref, "binding_ref"))
        if self.connector_id is not None:
            object.__setattr__(self, "connector_id", _bounded_ref(self.connector_id, "connector_id"))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", _aware_utc(self.expires_at, "expires_at"))
        if self.channel_class is TrustedChannelClass.EXTERNAL_CONNECTOR and self.binding_ref is None:
            raise TrustedChannelReferenceError(
                "external connector reference requires the existing binding ref"
            )

    def is_expired(self, now: datetime) -> bool:
        if self.expires_at is None:
            return False
        return _aware_utc(now, "now") >= self.expires_at

    def public_projection(self) -> dict[str, Any]:
        """JSON-safe metadata-only projection.

        The raw ``channel_ref``, the raw ``binding_ref`` and the connector id
        are intentionally absent — matching #3594's raw ``location_ref``,
        #3602's raw ``working_representation_ref`` and #3605's raw
        ``trusted_channel_ref``. Only presence is projected.

        This projection carries **no origin/provenance attestation** for the
        reference. The origin guarantee is an input precondition owned by the
        existing trusted host/binding authority (see the module docstring).
        """

        return {
            "contract_version": "claw-trusted-channel-reference.v1",
            "channel_class": self.channel_class.value,
            "channel_ref_present": True,
            "conversation_ref_present": True,
            "resolved_at": _iso(self.resolved_at),
            "expires_at": _iso(self.expires_at) if self.expires_at is not None else None,
            "raw_channel_ref_in_projection": False,
            "raw_connector_id_in_projection": False,
            "raw_binding_ref_in_projection": False,
            "raw_destination_in_projection": False,
            "connector_secret_in_projection": False,
            "delivery_execution": False,
            "send_write_authority": False,
        }


def _channel_ref_digest(
    *,
    account_ref: str,
    workspace_ref: str,
    conversation_ref: str,
    channel_class: TrustedChannelClass,
    binding_ref: str | None,
    connector_id: str | None,
) -> str:
    """Deterministic digest binding the reference to this exact context.

    No secret is involved: the inputs are already-opaque refs, and the digest is
    never treated as authority. It exists so a reference resolved for one
    account/workspace/conversation/binding can never be replayed for another.
    """
    material = json.dumps(
        {
            "account_ref": account_ref,
            "workspace_ref": workspace_ref,
            "conversation_ref": conversation_ref,
            "channel_class": channel_class.value,
            "binding_ref": binding_ref,
            "connector_id": connector_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{_REF_PREFIX}_{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def resolve_trusted_channel_reference(
    context: TrustedCurrentChannelContext | None,
    *,
    now: datetime,
    expected_account_ref: str,
    expected_workspace_ref: str,
    supported_connector_ids: Iterable[str] | None = None,
    caller_channel_label: str | None = None,
) -> TrustedChannelReference:
    """Resolve the caller's current channel into an opaque trusted reference.

    Fails closed — it never guesses an external destination — when the trusted
    context is missing, the account or workspace does not match, the context or
    binding is stale/expired/revoked, the channel class is unsupported, the
    connector is outside the supplied catalogue authority, or a caller-supplied
    label contradicts the trusted class.
    """

    current = _aware_utc(now, "now")

    if context is None:
        raise TrustedChannelReferenceError(
            "trusted current-channel context is required; a caller-supplied destination is not authority"
        )
    if not isinstance(context, TrustedCurrentChannelContext):
        raise TrustedChannelReferenceError("trusted current-channel context is malformed")

    expected_account = _bounded_ref(expected_account_ref, "expected_account_ref")
    expected_workspace = _bounded_ref(expected_workspace_ref, "expected_workspace_ref")

    if context.account_ref != expected_account:
        raise TrustedChannelReferenceError("cross-account channel reuse is refused")
    if context.workspace_ref != expected_workspace:
        raise TrustedChannelReferenceError("cross-workspace channel reuse is refused")

    if context.observed_at > current:
        raise TrustedChannelReferenceError("trusted context observation time is in the future")
    if current - context.observed_at > MAX_CONTEXT_AGE:
        raise TrustedChannelReferenceError("trusted current-channel context is stale")

    if context.channel_class not in SUPPORTED_CHANNEL_CLASSES:
        raise TrustedChannelReferenceError("unsupported channel class")

    # A request-body label is never authority. It is only allowed to agree.
    if caller_channel_label is not None:
        label = caller_channel_label.strip().lower() if isinstance(caller_channel_label, str) else ""
        if label != context.channel_class.value:
            raise TrustedChannelReferenceError(
                "caller-supplied channel label is not delivery authority"
            )

    binding_ref: str | None = None
    connector_id: str | None = None
    expires_at: datetime | None = None

    if context.channel_class is TrustedChannelClass.EXTERNAL_CONNECTOR:
        binding = context.binding
        if binding is None:
            raise TrustedChannelReferenceError(
                "external connector channel class requires the existing connector binding"
            )
        if binding.account_ref != context.account_ref:
            raise TrustedChannelReferenceError("binding belongs to a different account")
        if binding.workspace_ref != context.workspace_ref:
            raise TrustedChannelReferenceError("binding belongs to a different workspace")
        if not binding.usable_at(current):
            raise TrustedChannelReferenceError("connector binding is expired, revoked or not yet valid")
        allowed = _bounded_connector_ids(supported_connector_ids)
        if not allowed:
            raise TrustedChannelReferenceError(
                "connector channel class requires the existing catalogue authority"
            )
        if binding.connector_id not in allowed:
            raise TrustedChannelReferenceError("unsupported connector for channel delivery")
        binding_ref = binding.binding_ref
        connector_id = binding.connector_id
        expires_at = binding.expires_at

    return TrustedChannelReference(
        channel_ref=_channel_ref_digest(
            account_ref=context.account_ref,
            workspace_ref=context.workspace_ref,
            conversation_ref=context.conversation_ref,
            channel_class=context.channel_class,
            binding_ref=binding_ref,
            connector_id=connector_id,
        ),
        channel_class=context.channel_class,
        account_ref=context.account_ref,
        workspace_ref=context.workspace_ref,
        conversation_ref=context.conversation_ref,
        resolved_at=current,
        binding_ref=binding_ref,
        connector_id=connector_id,
        expires_at=expires_at,
    )


def verify_trusted_channel_reference(
    reference: str | TrustedChannelReference,
    context: TrustedCurrentChannelContext | None,
    *,
    now: datetime,
    expected_account_ref: str,
    expected_workspace_ref: str,
    supported_connector_ids: Iterable[str] | None = None,
) -> TrustedChannelReference:
    """Re-resolve and prove a reference still belongs to this exact context.

    Authority comes from re-resolution against the trusted context, never from
    the token string: a forged, unknown, expired, cross-account or
    cross-workspace reference fails closed.
    """

    current = _aware_utc(now, "now")

    if isinstance(reference, TrustedChannelReference):
        candidate = reference
    elif isinstance(reference, str):
        candidate_text = reference.strip()
        if not _CHANNEL_REF_RE.fullmatch(candidate_text):
            raise TrustedChannelReferenceError("trusted channel reference is malformed")
        candidate = None
    else:
        raise TrustedChannelReferenceError("trusted channel reference is malformed")

    resolved = resolve_trusted_channel_reference(
        context,
        now=current,
        expected_account_ref=expected_account_ref,
        expected_workspace_ref=expected_workspace_ref,
        supported_connector_ids=supported_connector_ids,
    )

    if candidate is not None:
        if candidate.channel_ref != resolved.channel_ref:
            raise TrustedChannelReferenceError("trusted channel reference does not match the context")
        if candidate.is_expired(current):
            raise TrustedChannelReferenceError("trusted channel reference is expired")
        return candidate

    if candidate_text != resolved.channel_ref:
        raise TrustedChannelReferenceError("trusted channel reference does not match the context")
    return resolved


def bind_delivery_intent(
    *,
    delivery_intent_id: str,
    artifact_ref: Any,
    reference: TrustedChannelReference,
    workspace_ref: str,
    run_ref: str,
    created_at: datetime,
    lineage_ref: str | None = None,
    approval_ref: str | None = None,
) -> ArtifactDeliveryIntent:
    """Bind an existing #3605 delivery intent to an exactly-matching reference.

    Reuses ``declare_delivery_intent`` — no artifact field is re-declared here
    and no delivery kind is invented. The workspace must match the reference, so
    an intent can never be pointed at another workspace's channel.
    """

    if not isinstance(reference, TrustedChannelReference):
        raise TrustedChannelReferenceError("reference must be a resolved TrustedChannelReference")
    if _bounded_ref(workspace_ref, "workspace_ref") != reference.workspace_ref:
        raise TrustedChannelReferenceError(
            "delivery intent workspace must match the resolved channel workspace"
        )
    delivery_kind = (
        DeliveryKind.CURRENT_SURFACE
        if reference.channel_class is TrustedChannelClass.CURRENT_SURFACE
        else DeliveryKind.EXTERNAL_CONNECTOR
    )
    return declare_delivery_intent(
        delivery_intent_id=delivery_intent_id,
        artifact_ref=artifact_ref,
        delivery_kind=delivery_kind,
        trusted_channel_ref=reference.channel_ref,
        workspace_ref=workspace_ref,
        run_ref=run_ref,
        created_at=created_at,
        lineage_ref=lineage_ref,
        channel_binding_ref=reference.binding_ref,
        approval_ref=approval_ref,
    )
