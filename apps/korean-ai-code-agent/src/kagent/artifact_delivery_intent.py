"""Canonical provider-neutral artifact delivery intent contract (#3605, parent #3580).

#3592/#3594 defined ONE canonical artifact
(``kagent.artifact_registration.CanonicalArtifactRecord``) and #3599/#3602
defined the lineage *between* artifacts
(``kagent.artifact_lineage.ArtifactLineage``). This module defines the last
model-free contract before any real channel delivery:

```text
Canonical artifact
  -> delivery intent            <- this module stops here
  -> trusted host resolves the current channel binding
  -> approval if required
  -> separately authorized channel adapter
  -> delivery receipt
```

A delivery intent is **inert metadata**: it says *which* already-registered
artifact should be delivered, *what class* of delivery is intended, and *which
host-resolved channel reference* it targets. It performs no resolution, opens
no transport, mints no channel identity, and grants no SEND/WRITE authority.

Reused, never duplicated:

* the artifact identity/integrity pair is
  ``kagent.artifact_lineage.LineageArtifactRef`` — the canonical reference
  established by #3599/#3602, which itself consumes the #3594 record. This
  module re-exports nothing and re-declares no artifact field;
* ``lineage_ref`` (optional) carries **only** the opaque ``lineage_id``. The
  lineage's own metadata (source/working/output refs, transformation kind,
  integrity refs) is never re-copied here;
* ``approval_ref`` (optional) is an opaque reference into the **existing**
  approval-continuation authority. No approval store, state machine,
  self-approval, or artifact-creation-implies-approval rule exists here.

``trusted_channel_ref`` is **consumed, not minted**. It is an opaque handle
produced by a trusted host from an existing connector/channel binding. This
contract never derives a provider chat id, never derives a Drive destination,
never reads an OAuth/bot token, never maps a request-body ``channel`` label
into a trusted binding, never queries a connector, and never authorizes a send.

Structural, not lexical, protection. The record has **no** provider-specific
field: no chat id, no Drive file id or path, no OAuth/bot token, no connector
secret, no model-selected destination. Raw provider destinations and
secret-bearing material are rejected at construction, and the raw
``trusted_channel_ref`` is never projected — ``public_projection()`` exposes
only its presence, exactly as #3594 withholds the raw ``location_ref`` and
#3602 withholds the raw ``working_representation_ref``. Lexical blacklists are
a secondary guard, not the claim.

The distinction the contract must carry without provider logic:

* ``CURRENT_SURFACE`` — the already-authenticated in-app surface of the caller
  (a Padiem Chat attachment/download needs no external-send approval);
* ``EXTERNAL_CONNECTOR`` — delivery through a separately authorized connector
  adapter. Because an external delivery must name the **existing** binding
  authority that resolved the channel, ``channel_binding_ref`` is required for
  this kind (and remains an opaque ref — this module mints no authority);
* ``DURABLE_STORE`` — hand-off into the durable file authority. Provider-neutral
  on purpose: "Drive" is never a field of this contract.

Exactly one destination per intent: there is no destination list, so no
unbounded collection can exist in this schema.

Zero network, zero model, zero provider, zero execution: deterministic and
network-free by construction, in the same style as ``artifact_registration``
and ``artifact_lineage``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .artifact_lineage import LineageArtifactRef, ref_from_canonical_artifact
from .artifact_registration import CanonicalArtifactRecord
from .contracts import ContractError


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
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


class ArtifactDeliveryIntentError(ContractError):
    """Canonical artifact delivery intent contract failure."""


class DeliveryKind(str, Enum):
    """Provider-neutral delivery class (never a provider name).

    ``CURRENT_SURFACE``   the caller's already-authenticated in-app surface;
    ``EXTERNAL_CONNECTOR`` delivery through a separately authorized connector
                          adapter (requires ``channel_binding_ref``);
    ``DURABLE_STORE``     hand-off into the durable file authority.
    """

    CURRENT_SURFACE = "current_surface"
    EXTERNAL_CONNECTOR = "external_connector"
    DURABLE_STORE = "durable_store"


def _bounded_id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ArtifactDeliveryIntentError(f"{field_name} must be a bounded safe identifier")
    value = value.strip()
    if _CONTROL_RE.search(value):
        raise ArtifactDeliveryIntentError(f"{field_name} must not contain control characters")
    return value


def _bounded_ref(value: str, field_name: str) -> str:
    """Identifier-semantics provenance ref (workspace_ref / run_ref).

    Consumed from the existing run/workspace authority: no URL scheme, no
    credential-shaped prefix, no traversal or control characters.
    """
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ArtifactDeliveryIntentError(f"{field_name} must be a bounded safe identifier")
    value = value.strip()
    if _CONTROL_RE.search(value) or ".." in value:
        raise ArtifactDeliveryIntentError(f"{field_name} must not contain traversal or control characters")
    lowered = value.lower()
    if "://" in lowered or ":" in value:
        raise ArtifactDeliveryIntentError(f"{field_name} must be an identifier, not a URL or scheme-prefixed token")
    if any(lowered.startswith(prefix) for prefix in _CREDENTIAL_PREFIXES):
        raise ArtifactDeliveryIntentError(f"{field_name} must not carry credential-like material")
    return value


def _opaque_ref(value: str, field_name: str) -> str:
    """Opaque, provider-neutral handle (trusted_channel_ref / binding / approval).

    The value is a host-issued reference whose meaning belongs to the trusted
    authority that produced it. This contract never interprets it. Local
    references (drive letter, UNC, absolute POSIX), ``file://`` URIs, any URL
    with query/fragment material, whitespace-bearing credential material and
    credential-like prefixes fail closed.

    A bare integer is rejected as well: every provider destination in this
    repository's connector family is a raw numeric id at the wire layer, so a
    numeric value here is a provider id, not an opaque reference. This is a
    secondary guard — the structural protection is that this schema has no
    provider field and performs no resolution or execution.

    A scheme-less token that carries no URL/credential/local-path syntax is
    deliberately accepted: it is lexically indistinguishable from any other
    opaque host handle, and this contract does not claim to detect a provider
    from a token. Such a value is never interpreted, resolved, executed or
    projected.
    """
    if not isinstance(value, str) or not value.strip():
        raise ArtifactDeliveryIntentError(f"{field_name} must be non-empty text")
    value = value.strip()
    if len(value) > _OPAQUE_REF_MAX_CHARS or _CONTROL_RE.search(value):
        raise ArtifactDeliveryIntentError(f"{field_name} must be bounded control-free text")
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
        or lowered.startswith(("bearer ", "basic ", "token "))
    ):
        raise ArtifactDeliveryIntentError(
            f"{field_name} must be an opaque reference without URL/credential/local-path material"
        )
    for prefix in _CREDENTIAL_PREFIXES:
        if lowered.startswith(prefix + ":"):
            raise ArtifactDeliveryIntentError(f"{field_name} must not carry credential-like material")
    if _BARE_PROVIDER_ID_RE.fullmatch(value):
        raise ArtifactDeliveryIntentError(
            f"{field_name} must be an opaque reference, not a bare provider id"
        )
    return value


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ArtifactDeliveryIntentError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_artifact_ref(value: Any) -> LineageArtifactRef:
    """Accept the canonical lineage ref, or the #3594 record it is built from."""
    if isinstance(value, LineageArtifactRef):
        return value
    if isinstance(value, CanonicalArtifactRecord):
        return ref_from_canonical_artifact(value)
    raise ArtifactDeliveryIntentError(
        "artifact_ref must be a LineageArtifactRef or a CanonicalArtifactRecord"
    )


@dataclass(frozen=True, slots=True)
class ArtifactDeliveryIntent:
    """Where an already-registered canonical artifact is intended to go.

    Frozen, metadata-only, inert. ``artifact_ref`` is required; ``workspace_ref``
    and ``run_ref`` carry the run/workspace provenance; ``trusted_channel_ref``
    is a host-resolved opaque handle. Nothing here performs, schedules or
    authorizes a delivery.
    """

    delivery_intent_id: str
    artifact_ref: LineageArtifactRef
    delivery_kind: DeliveryKind
    trusted_channel_ref: str
    workspace_ref: str
    run_ref: str
    created_at: datetime
    lineage_ref: str | None = None
    channel_binding_ref: str | None = None
    approval_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "delivery_intent_id", _bounded_id(self.delivery_intent_id, "delivery_intent_id")
        )
        object.__setattr__(self, "artifact_ref", _coerce_artifact_ref(self.artifact_ref))

        if not isinstance(self.delivery_kind, DeliveryKind):
            try:
                object.__setattr__(self, "delivery_kind", DeliveryKind(self.delivery_kind))
            except (TypeError, ValueError) as exc:
                raise ArtifactDeliveryIntentError("invalid delivery kind") from exc

        object.__setattr__(
            self,
            "trusted_channel_ref",
            _opaque_ref(self.trusted_channel_ref, "trusted_channel_ref"),
        )
        object.__setattr__(self, "workspace_ref", _bounded_ref(self.workspace_ref, "workspace_ref"))
        object.__setattr__(self, "run_ref", _bounded_ref(self.run_ref, "run_ref"))
        object.__setattr__(self, "created_at", _aware_utc(self.created_at, "created_at"))

        if self.lineage_ref is not None:
            object.__setattr__(self, "lineage_ref", _bounded_id(self.lineage_ref, "lineage_ref"))
        if self.channel_binding_ref is not None:
            object.__setattr__(
                self,
                "channel_binding_ref",
                _opaque_ref(self.channel_binding_ref, "channel_binding_ref"),
            )
        if self.approval_ref is not None:
            object.__setattr__(self, "approval_ref", _opaque_ref(self.approval_ref, "approval_ref"))

        if (
            self.delivery_kind is DeliveryKind.EXTERNAL_CONNECTOR
            and self.channel_binding_ref is None
        ):
            raise ArtifactDeliveryIntentError(
                "external connector delivery must name the existing channel binding authority "
                "(channel_binding_ref); this contract never mints one"
            )

    @property
    def artifact_id(self) -> str:
        return self.artifact_ref.artifact_id

    @property
    def artifact_integrity_ref(self) -> str:
        return self.artifact_ref.integrity_ref

    @property
    def requires_external_approval(self) -> bool:
        """Whether the existing approval-continuation authority is implicated.

        External connector delivery may require approval; the in-app current
        surface does not. This is a *description*, not an approval decision —
        the decision stays with the existing approval authority.
        """
        return self.delivery_kind is DeliveryKind.EXTERNAL_CONNECTOR

    def public_projection(self) -> dict[str, Any]:
        """JSON-safe metadata-only projection (never bytes, never destinations).

        The raw ``trusted_channel_ref`` is intentionally absent, matching
        #3594's raw ``location_ref`` and #3602's raw
        ``working_representation_ref``: it is a handle whose meaning belongs to
        the trusted host. Only its presence is projected.
        """

        projection: dict[str, Any] = {
            "contract_version": "claw-artifact-delivery-intent.v1",
            "delivery_intent_id": self.delivery_intent_id,
            "artifact_id": self.artifact_ref.artifact_id,
            "artifact_integrity_ref": self.artifact_ref.integrity_ref,
            "delivery_kind": self.delivery_kind.value,
            "workspace_ref": self.workspace_ref,
            "run_ref": self.run_ref,
            "created_at": _iso(self.created_at),
            "trusted_channel_ref_present": True,
            "caller_minted_destination": False,
            "model_selected_destination": False,
            "delivery_execution": False,
            "send_write_authority": False,
        }
        if self.lineage_ref is not None:
            projection["lineage_ref"] = self.lineage_ref
        if self.channel_binding_ref is not None:
            projection["channel_binding_ref"] = self.channel_binding_ref
        if self.approval_ref is not None:
            projection["approval_ref"] = self.approval_ref
        return projection


def declare_delivery_intent(
    *,
    delivery_intent_id: str,
    artifact_ref: Any,
    delivery_kind: DeliveryKind,
    trusted_channel_ref: str,
    workspace_ref: str,
    run_ref: str,
    created_at: datetime,
    lineage_ref: str | None = None,
    channel_binding_ref: str | None = None,
    approval_ref: str | None = None,
) -> ArtifactDeliveryIntent:
    """Single entry point for delivery-intent declaration (validation included).

    ``artifact_ref`` accepts either a ``LineageArtifactRef`` (#3602) or a #3594
    ``CanonicalArtifactRecord``.
    """

    return ArtifactDeliveryIntent(
        delivery_intent_id=delivery_intent_id,
        artifact_ref=artifact_ref,
        delivery_kind=delivery_kind,
        trusted_channel_ref=trusted_channel_ref,
        workspace_ref=workspace_ref,
        run_ref=run_ref,
        created_at=created_at,
        lineage_ref=lineage_ref,
        channel_binding_ref=channel_binding_ref,
        approval_ref=approval_ref,
    )
