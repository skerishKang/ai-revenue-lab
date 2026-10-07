"""Trusted Telegram document-delivery adapter (#3666, parent #3580).

The provider-neutral chain already landed every contract short of a real
delivery:

```text
CanonicalArtifactRecord        (#3592/#3594)
  -> ArtifactLineage           (#3599/#3602)
  -> ArtifactDeliveryIntent    (#3605)
  -> TrustedChannelReference   (#3621, re-resolved per execution)
  -> ArtifactDeliveryExecutionRequest + ArtifactDeliveryReceipt   (#3631)
  -> ArtifactDeliveryAdapterPort (a Protocol, still unimplemented)
```

This module is the first implementation of that port: a connector-owned
Telegram adapter that performs exactly one action — deliver one
already-registered canonical artifact to the caller's current trusted
Telegram conversation:

```text
ArtifactDeliveryExecutionRequest (#3631)
  -> trusted channel re-resolution      (#3621 verify, per execution)
  -> canonical artifact material        (#3594 authority via injected resolver)
  -> existing approval evidence         (consumed, never minted)
  -> injected document-send port        (transport seam, no raw HTTP surface)
  -> bounded provider result            (existing ConnectorProviderError taxonomy)
  -> ArtifactDeliveryReceipt            (#3631, existing receipt authority)
```

### Authority — the current channel comes from the trusted binding only

The destination is never an input. The request structurally has no
destination field, and the adapter resolves the outbound chat only through
the existing pairing/binding authorities:

```text
CURRENT_CHANNEL_FROM_TRUSTED_BINDING=YES
REQUEST_BODY_DESTINATION_AUTHORITY=NO
REQUEST_BODY_CHAT_ID_AUTHORITY=NO
TOKEN_STRING_IS_AUTHORITY=NO
```

* the trusted channel reference is re-resolved against the trusted host's
  *current* context on every execution through #3621's
  ``verify_trusted_channel_reference`` — a forged, stale, cross-account,
  cross-workspace or revoked reference fails closed;
* the resolved conversation must be a chat already paired in the existing
  ``kagent.telegram_contracts.TelegramBotScope``, and the scope must
  authorize the outbound actor for it;
* the provider chat id and the bot token are resolved *inside* the adapter
  through the existing ``TelegramTrustedBindingPort`` (the same trusted
  authority ``kagent.telegram_bot_runtime`` already uses) — the token is
  never a parameter, never returned, never logged and never projected.

### Secret boundary

```text
TELEGRAM_BOT_TOKEN_IN_MODEL_CONTEXT=NO
RAW_CONNECTOR_SECRET_IN_TASK_CONTEXT=NO
RAW_BOT_TOKEN_IN_LOG=0
RAW_CHAT_ID_IN_RECEIPT=0
RAW_ARTIFACT_BYTES_IN_RECEIPT=0
```

No new secret env, binding, store or identity authority is introduced: the
token and chat-id resolution authority stays with the existing
``TelegramTrustedBindingPort`` composition exactly as in the B54 runtime.

### Artifact boundary

The delivery consumes the canonical artifact reference, never a machine-local
path. Bounded document material is obtained through the injected
``TelegramArtifactMaterialResolver`` — a lookup into the existing #3594
artifact authority — and is verified inside the adapter against the request's
``LineageArtifactRef`` (id, integrity digest, size) before any provider call:

```text
LOCAL_PATH_ONLY_REMOTE_DELIVERY=NO
```

### Idempotency / retry / fan-out

The #3631 vocabulary is reused verbatim: ``InMemoryDeliveryAttemptRegistry``
admission happens before anything else, so a duplicate or replayed attempt
fails closed instead of granting a second execution.

```text
AUTO_RETRY=NO
FANOUT=0
SECOND_SEND=0
```

One execution performs at most one provider call and never retries. Provider
failures are normalized into the existing ``ConnectorProviderError`` /
``ConnectorProviderErrorKind`` taxonomy (``retryable`` selects between
``FAILED_RETRYABLE`` and ``FAILED_TERMINAL``); the raw provider error body is
never surfaced — only a kind, a deterministic error reference derived from a
digest, and an optional bounded rate-limit projection.

### Refusal semantics

A request that is structurally inadmissible (wrong delivery kind, failed
re-resolution, unpaired conversation, noncanonical artifact, approval
correlation mismatch, replay) raises and never reaches the provider. A request
that is admissible but refused by connector policy (missing or unresolvable
approval evidence) produces a ``REFUSED`` receipt with zero external side
effects — the existing terminal vocabulary's "the adapter never acted".

### What this module deliberately does not do

* no real network transport: the document-send port is injected, and this
  slice ships no transport implementation, no endpoint host literal and no
  live path. Wiring the production transport behind the port is a separate,
  explicitly authorized change with its own live gate;
* no second execution/receipt/connector-identity/artifact/approval
  authority: receipts are built only through #3631's
  ``build_delivery_receipt`` (correlation copied from the request, so a
  receipt can never be pointed at another attempt), and the approval
  evidence is the existing ``TelegramOutboundApproval`` shape consumed
  opaquely;
* no durable store, no schema, no persisted state.

Zero network, zero model, zero provider calls at import or construction: the
adapter is hermetic by construction and every collaborator is injected.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Protocol, runtime_checkable

from .artifact_delivery_execution_receipt import (
    ArtifactDeliveryExecutionError,
    ArtifactDeliveryExecutionRequest,
    ArtifactDeliveryReceipt,
    DeliveryTerminalStatus,
    InMemoryDeliveryAttemptRegistry,
    build_delivery_receipt,
)
from .artifact_lineage import LineageArtifactRef
from .artifact_registration import MAX_ARTIFACT_SIZE_BYTES, CanonicalArtifactRecord
from .connector_trust import (
    ConnectorProviderError,
    ConnectorProviderErrorKind,
    ConnectorRateLimitProjection,
)
from .contracts import ContractError
from .telegram_contracts import (
    MAX_TELEGRAM_FILE_BYTES,
    TelegramBotScope,
    TelegramOutboundApproval,
    TelegramOutboundCapability,
)
from .trusted_channel_reference import verify_trusted_channel_reference
from .telegram_bot_runtime import TelegramTrustedBindingPort

# Invariants of this module's own surface, asserted by the tests.
TELEGRAM_ARTIFACT_DELIVERY_ADAPTER = True
SOURCE_SLICE_WITHOUT_LIVE_SEND = True
CURRENT_CHANNEL_FROM_TRUSTED_BINDING = True
REQUEST_BODY_DESTINATION_AUTHORITY = False
REQUEST_BODY_CHAT_ID_AUTHORITY = False
TOKEN_STRING_IS_AUTHORITY = False
TELEGRAM_BOT_TOKEN_IN_MODEL_CONTEXT = False
RAW_CONNECTOR_SECRET_IN_TASK_CONTEXT = False
RAW_BOT_TOKEN_IN_LOG = 0
RAW_CHAT_ID_IN_RECEIPT = 0
RAW_ARTIFACT_BYTES_IN_RECEIPT = 0
LOCAL_PATH_ONLY_REMOTE_DELIVERY = False
MODEL_DIRECT_PROVIDER_HTTP = False
RAW_HTTP_SURFACE_EXPOSED = False
AUTO_RETRY = False
FANOUT = 0
SECOND_SEND = 0
RETRY_COUNT_PER_ATTEMPT = 0
SECOND_EXECUTION_AUTHORITY = 0
SECOND_RECEIPT_AUTHORITY = 0
SECOND_CONNECTOR_IDENTITY_AUTHORITY = 0
SECOND_ARTIFACT_AUTHORITY = 0
SECOND_APPROVAL_AUTHORITY = 0
NEW_DURABLE_STORE = False
EXTERNAL_NETWORK_PATH_IN_MODULE = False
LIVE_TELEGRAM_SEND = False

#: The adapter serves exactly the connector class it belongs to. The current
#: in-app surface and the durable store have their own (future) adapters.
_DELIVERY_KINDS_SERVED = frozenset({"external_connector"})

#: Existing catalogue authority for this adapter's connector identity.
_SUPPORTED_CONNECTOR_IDS = ("telegram",)

_MAX_DOCUMENT_SEND_TIMEOUT_SECONDS = 30
_MAX_PROVIDER_ERROR_CODE = 10_000
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


class TelegramArtifactDeliveryError(ArtifactDeliveryExecutionError):
    """Trusted Telegram document-delivery failure (fail closed)."""


@runtime_checkable
class TelegramDocumentSendPort(Protocol):
    """Injected connector-owned document transport seam.

    The adapter core never opens a network path. A production transport (the
    official Bot API document upload, multipart form encoding over TLS) is a
    separate, explicitly authorized change that plugs in behind this port;
    tests always inject a hermetic fake.
    """

    def send_document(
        self,
        *,
        token: bytes,
        provider_chat_id: int,
        document_bytes: bytes,
        filename: str,
        mime_type: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:  # pragma: no cover - structural port only
        ...


@dataclass(frozen=True, slots=True)
class TelegramArtifactMaterial:
    """Bounded document material resolved from the existing artifact authority.

    ``record`` is the #3594 canonical registration record; ``document_bytes``
    is the materialization of exactly those bytes. The adapter verifies the
    pair against the request's ``LineageArtifactRef`` before any provider call,
    so material can never drift from the registered artifact identity.
    """

    record: CanonicalArtifactRecord
    document_bytes: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.record, CanonicalArtifactRecord):
            raise TelegramArtifactDeliveryError(
                "material record must be a CanonicalArtifactRecord"
            )
        if not isinstance(self.document_bytes, bytes) or not self.document_bytes:
            raise TelegramArtifactDeliveryError("material must carry non-empty bytes")


@runtime_checkable
class TelegramArtifactMaterialResolver(Protocol):
    """Lookup seam into the existing canonical artifact authority.

    Consumed by the adapter as injected composition; this module introduces no
    artifact registry, store or second artifact authority.
    """

    def resolve_artifact_material(
        self, artifact_ref: LineageArtifactRef
    ) -> TelegramArtifactMaterial | None:  # pragma: no cover - structural port only
        ...


def _bounded_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TelegramArtifactDeliveryError(f"{field_name} must be non-empty text")
    value = value.strip()
    if not _SAFE_REF_RE.fullmatch(value):
        raise TelegramArtifactDeliveryError(f"{field_name} must be a bounded safe identifier")
    lowered = value.lower()
    if any(
        lowered.startswith(prefix)
        for prefix in ("secret", "oauth", "token", "api_key", "apikey", "bearer", "password", "credential")
    ):
        raise TelegramArtifactDeliveryError(f"{field_name} must not carry credential-like material")
    return value


def _require_callable(value: Any, field_name: str) -> None:
    if not callable(value):
        raise TelegramArtifactDeliveryError(f"{field_name} must be callable")


def _provider_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"provider {field_name} must be an exact integer")
    return value


def document_material_fingerprint(
    record: CanonicalArtifactRecord,
    *,
    binding_ref: str,
    workspace_ref: str,
    bot_ref: str,
    chat_ref: str,
) -> str:
    """Deterministic fingerprint binding approval evidence to one document send.

    The existing approval authority mints a ``TelegramOutboundApproval`` over
    this fingerprint; the adapter re-derives and compares it at execution time,
    so an approval minted for a different artifact, chat or binding can never
    authorize this send. This is a binding function, not a new approval
    authority: no approval is stored, minted or self-approved here.

    The inbound-file quarantine shape of the B54 material contract is not
    force-fit onto outbound canonical artifacts: an outbound artifact carries
    its provenance through the #3594 record (identity + integrity), not
    through inbound quarantine evidence.
    """

    if not isinstance(record, CanonicalArtifactRecord):
        raise TelegramArtifactDeliveryError("material fingerprint source must be a canonical record")
    material = {
        "contract_version": "claw-telegram-document-delivery-material.v1",
        "capability": TelegramOutboundCapability.SEND_DOCUMENT.value,
        "binding_ref": _bounded_ref(binding_ref, "binding_ref"),
        "workspace_ref": _bounded_ref(workspace_ref, "workspace_ref"),
        "bot_ref": _bounded_ref(bot_ref, "bot_ref"),
        "chat_ref": _bounded_ref(chat_ref, "chat_ref"),
        "artifact_id": record.artifact_id,
        "integrity_ref": record.integrity_ref,
        "filename": record.filename,
        "media_type": record.media_type,
        "size_bytes": record.size_bytes,
    }
    payload = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _receipt_ref_for(request: ArtifactDeliveryExecutionRequest) -> str:
    """Deterministic receipt handle derived from the attempt identity."""

    digest = hashlib.sha256(request.attempt_ref.encode("utf-8")).hexdigest()[:32]
    return f"tgdr{digest}"


def _provider_error_ref(code: int, description_digest: str) -> str:
    """Bounded error reference carrying kind/code/digest — never the raw body."""

    return f"tgdocerr-{code}-{description_digest[:16]}"


_RETRYABLE_HTTP_KINDS: dict[int, ConnectorProviderErrorKind] = {
    429: ConnectorProviderErrorKind.RATE_LIMITED,
}
_TERMINAL_HTTP_KINDS: dict[int, ConnectorProviderErrorKind] = {
    401: ConnectorProviderErrorKind.AUTHORIZATION,
    403: ConnectorProviderErrorKind.AUTHORIZATION,
    404: ConnectorProviderErrorKind.NOT_FOUND,
    409: ConnectorProviderErrorKind.CONFLICT,
    400: ConnectorProviderErrorKind.INVALID_REQUEST,
    422: ConnectorProviderErrorKind.INVALID_REQUEST,
}


def _normalize_provider_rejection(
    code: int,
    description: str,
    retry_after_seconds: int | None,
) -> ConnectorProviderError:
    """Map a provider rejection onto the existing bounded error taxonomy."""

    if code in _RETRYABLE_HTTP_KINDS:
        kind = _RETRYABLE_HTTP_KINDS[code]
        retryable = True
    elif 500 <= code <= 599:
        kind = ConnectorProviderErrorKind.UNAVAILABLE
        retryable = True
    elif code in _TERMINAL_HTTP_KINDS:
        kind = _TERMINAL_HTTP_KINDS[code]
        retryable = False
    else:
        kind = ConnectorProviderErrorKind.UNKNOWN
        retryable = False

    description_digest = hashlib.sha256(description.encode("utf-8")).hexdigest()
    rate_limit: ConnectorRateLimitProjection | None = None
    if kind is ConnectorProviderErrorKind.RATE_LIMITED:
        observed_at = datetime.now(timezone.utc)
        rate_limit = ConnectorRateLimitProjection(
            observed_at=observed_at,
            retry_after_seconds=(
                retry_after_seconds
                if retry_after_seconds is not None and 0 <= retry_after_seconds <= 3600
                else None
            ),
        )
    return ConnectorProviderError(
        kind=kind,
        error_ref=_provider_error_ref(code, description_digest),
        retryable=retryable,
        rate_limit=rate_limit,
    )


def _extract_retry_after(envelope: dict[str, Any]) -> int | None:
    parameters = envelope.get("parameters")
    if type(parameters) is not dict:
        return None
    retry_after = parameters.get("retry_after")
    if isinstance(retry_after, bool) or not isinstance(retry_after, int):
        return None
    return retry_after


class TelegramArtifactDeliveryAdapter:
    """Connector-owned implementation of #3631's ``ArtifactDeliveryAdapterPort``.

    Every collaborator is injected by the trusted host composition; the
    adapter holds no secrets, no destinations and no artifact bytes of its
    own, and performs at most one provider call per execution.
    """

    def __init__(
        self,
        *,
        scope: TelegramBotScope,
        trusted_binding: TelegramTrustedBindingPort,
        document_send: TelegramDocumentSendPort,
        artifact_material: TelegramArtifactMaterialResolver,
        channel_context: Callable[[], Any],
        approval_evidence: Callable[[str], TelegramOutboundApproval | None],
        account_ref: str,
        actor_ref: str,
        clock: Callable[[], datetime] | None = None,
        attempt_registry: InMemoryDeliveryAttemptRegistry | None = None,
    ) -> None:
        if not isinstance(scope, TelegramBotScope):
            raise TelegramArtifactDeliveryError("scope must be a TelegramBotScope")
        for name in ("resolve_bot_token", "provider_chat_id"):
            if not callable(getattr(trusted_binding, name, None)):
                raise TelegramArtifactDeliveryError(
                    "trusted_binding does not implement the existing binding authority"
                )
        if not callable(getattr(document_send, "send_document", None)):
            raise TelegramArtifactDeliveryError(
                "document_send does not implement the injected document-send port"
            )
        if not callable(getattr(artifact_material, "resolve_artifact_material", None)):
            raise TelegramArtifactDeliveryError(
                "artifact_material does not implement the existing artifact authority lookup"
            )
        _require_callable(channel_context, "channel_context")
        _require_callable(approval_evidence, "approval_evidence")
        object.__setattr__(self, "_scope", scope)
        object.__setattr__(self, "_binding", trusted_binding)
        object.__setattr__(self, "_document_send", document_send)
        object.__setattr__(self, "_material", artifact_material)
        object.__setattr__(self, "_channel_context", channel_context)
        object.__setattr__(self, "_approval_evidence", approval_evidence)
        object.__setattr__(self, "_account_ref", _bounded_ref(account_ref, "account_ref"))
        object.__setattr__(self, "_actor_ref", _bounded_ref(actor_ref, "actor_ref"))
        object.__setattr__(self, "_clock", clock or (lambda: datetime.now(timezone.utc)))
        object.__setattr__(
            self, "_attempts", attempt_registry or InMemoryDeliveryAttemptRegistry()
        )

    @property
    def scope(self) -> TelegramBotScope:
        return self._scope

    def deliver(
        self,
        request: ArtifactDeliveryExecutionRequest,
        *,
        now: datetime | None = None,
    ) -> ArtifactDeliveryReceipt:
        """Execute one trusted document delivery; fail closed on any doubt."""

        if not isinstance(request, ArtifactDeliveryExecutionRequest):
            raise TelegramArtifactDeliveryError(
                "request must be an ArtifactDeliveryExecutionRequest"
            )
        if now is None:
            now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise TelegramArtifactDeliveryError("now must be a timezone-aware datetime")
        now = now.astimezone(timezone.utc)
        started_at = now

        # 1. Only the delivery class this connector adapter serves.
        if request.delivery_kind.value not in _DELIVERY_KINDS_SERVED:
            raise TelegramArtifactDeliveryError(
                "this adapter serves external-connector delivery only"
            )

        # 2. Duplicate/replay guard first: a second execution is never granted.
        self._attempts.admit(request)

        # 3. Trusted channel re-resolution against the trusted host's *current*
        #    context — the reference string is never authority.
        context = self._channel_context()
        resolved = verify_trusted_channel_reference(
            request.trusted_channel_ref,
            context,
            now=now,
            expected_account_ref=self._account_ref,
            expected_workspace_ref=self._scope.workspace_ref,
            supported_connector_ids=_SUPPORTED_CONNECTOR_IDS,
        )
        if resolved.connector_id != _SUPPORTED_CONNECTOR_IDS[0]:
            raise TelegramArtifactDeliveryError(
                "resolved connector identity does not match this adapter"
            )
        if request.channel_binding_ref is None:
            raise TelegramArtifactDeliveryError(
                "external-connector delivery must carry the existing binding reference"
            )
        if resolved.binding_ref != request.channel_binding_ref:
            raise TelegramArtifactDeliveryError(
                "resolved binding does not match the request binding reference"
            )
        if resolved.binding_ref != self._scope.binding_ref:
            raise TelegramArtifactDeliveryError(
                "resolved binding does not match the adapter's connector scope"
            )

        # 4. The destination is the caller's current conversation, which must
        #    already be paired in the existing scope authority.
        chat = self._scope.chat(resolved.conversation_ref)
        if chat is None:
            raise TelegramArtifactDeliveryError(
                "the current conversation is not a paired chat of this connector scope"
            )
        if not self._scope.authorizes_outbound(
            binding_ref=self._scope.binding_ref,
            workspace_ref=self._scope.workspace_ref,
            bot_ref=self._scope.bot_ref,
            chat_ref=chat.chat_ref,
            actor_ref=self._actor_ref,
        ):
            raise TelegramArtifactDeliveryError(
                "the connector scope does not authorize this outbound actor for the chat"
            )

        # 5. Canonical artifact material, verified against the request ref.
        material = self._material.resolve_artifact_material(request.artifact_ref)
        if material is None:
            raise TelegramArtifactDeliveryError(
                "artifact reference does not resolve in the canonical artifact authority"
            )
        self._verify_material(material, request.artifact_ref)

        # 6. Existing approval evidence is consumed, never minted. Missing or
        #    unresolvable evidence refuses the delivery (the adapter never
        #    acted); mismatched evidence fails closed.
        try:
            self._consume_approval(request, material, chat.chat_ref)
        except TelegramArtifactDeliveryRefusal:
            return build_delivery_receipt(
                receipt_ref=_receipt_ref_for(request),
                request=request,
                terminal_status=DeliveryTerminalStatus.REFUSED,
                started_at=started_at,
                completed_at=self._clock(),
            )

        # 7. Resolve token + provider chat id inside the trusted boundary.
        token = self._binding.resolve_bot_token(
            binding_ref=self._scope.binding_ref, bot_ref=self._scope.bot_ref
        )
        provider_chat_id = _provider_int(
            self._binding.provider_chat_id(
                binding_ref=self._scope.binding_ref,
                bot_ref=self._scope.bot_ref,
                chat_ref=chat.chat_ref,
            ),
            "chat id",
        )
        if provider_chat_id <= 0:
            raise TelegramArtifactDeliveryError(
                "the trusted binding authority returned an invalid chat identity"
            )

        # 8. One bounded provider call; the result is normalized into the
        #    existing taxonomy and the existing receipt contract.
        try:
            envelope = self._document_send.send_document(
                token=token,
                provider_chat_id=provider_chat_id,
                document_bytes=material.document_bytes,
                filename=material.record.filename,
                mime_type=material.record.media_type,
                timeout_seconds=_MAX_DOCUMENT_SEND_TIMEOUT_SECONDS,
            )
        except ContractError:
            raise
        except (OSError, TimeoutError) as exc:
            return build_delivery_receipt(
                receipt_ref=_receipt_ref_for(request),
                request=request,
                terminal_status=DeliveryTerminalStatus.FAILED_RETRYABLE,
                started_at=started_at,
                completed_at=self._clock(),
                provider_error=ConnectorProviderError(
                    kind=ConnectorProviderErrorKind.UNAVAILABLE,
                    error_ref=_provider_error_ref(0, hashlib.sha256(
                        exc.__class__.__name__.encode("utf-8")
                    ).hexdigest()),
                    retryable=True,
                ),
            )

        result = self._normalize_envelope(envelope)
        completed_at = self._clock()
        if result is None:
            code, description, retry_after = self._rejection_details(envelope)
            return build_delivery_receipt(
                receipt_ref=_receipt_ref_for(request),
                request=request,
                terminal_status=(
                    DeliveryTerminalStatus.FAILED_RETRYABLE
                    if code in _RETRYABLE_HTTP_KINDS or 500 <= code <= 599
                    else DeliveryTerminalStatus.FAILED_TERMINAL
                ),
                started_at=started_at,
                completed_at=completed_at,
                provider_error=_normalize_provider_rejection(code, description, retry_after),
            )

        return build_delivery_receipt(
            receipt_ref=_receipt_ref_for(request),
            request=request,
            terminal_status=DeliveryTerminalStatus.SUCCEEDED,
            started_at=started_at,
            completed_at=completed_at,
            external_side_effect_count=1,
        )

    def _verify_material(
        self, material: TelegramArtifactMaterial, artifact_ref: LineageArtifactRef
    ) -> None:
        record = material.record
        if record.artifact_id != artifact_ref.artifact_id:
            raise TelegramArtifactDeliveryError(
                "material record identity does not match the requested artifact"
            )
        if record.integrity_ref != artifact_ref.integrity_ref:
            raise TelegramArtifactDeliveryError(
                "material record integrity does not match the requested artifact"
            )
        if len(material.document_bytes) != record.size_bytes:
            raise TelegramArtifactDeliveryError(
                "material size does not match the registered artifact size"
            )
        if hashlib.sha256(material.document_bytes).hexdigest() != record.integrity_ref:
            raise TelegramArtifactDeliveryError(
                "material bytes do not match the registered integrity ref"
            )
        if not 0 < len(material.document_bytes) <= min(
            MAX_ARTIFACT_SIZE_BYTES, MAX_TELEGRAM_FILE_BYTES
        ):
            raise TelegramArtifactDeliveryError(
                "document material exceeds the bounded delivery size"
            )

    def _consume_approval(
        self,
        request: ArtifactDeliveryExecutionRequest,
        material: TelegramArtifactMaterial,
        chat_ref: str,
    ) -> TelegramOutboundApproval:
        if request.approval_ref is None:
            raise TelegramArtifactDeliveryRefusal("no approval reference on the delivery request")
        evidence = self._approval_evidence(request.approval_ref)
        if evidence is None:
            raise TelegramArtifactDeliveryRefusal(
                "approval reference does not resolve in the existing approval authority"
            )
        if evidence.approval_ref != request.approval_ref:
            raise TelegramArtifactDeliveryError(
                "approval evidence does not match the request approval reference"
            )
        expected_fingerprint = document_material_fingerprint(
            material.record,
            binding_ref=self._scope.binding_ref,
            workspace_ref=self._scope.workspace_ref,
            bot_ref=self._scope.bot_ref,
            chat_ref=chat_ref,
        )
        if evidence.material_fingerprint != expected_fingerprint:
            raise TelegramArtifactDeliveryError(
                "approval evidence was not minted for this document material"
            )
        return evidence

    def _normalize_envelope(self, envelope: Any) -> dict[str, Any] | None:
        """Provider envelope -> ``result`` object, or ``None`` on rejection.

        A malformed success envelope is a port contract violation (the
        composition, not the provider, is broken) and fails closed.
        """

        if type(envelope) is not dict or type(envelope.get("ok")) is not bool:
            raise ContractError("provider envelope is invalid")
        if envelope["ok"] is not True:
            return None
        result = envelope.get("result")
        if type(result) is not dict:
            raise ContractError("provider success envelope is missing a result object")
        message_id = _provider_int(result.get("message_id"), "message id")
        if message_id < 0:
            raise ContractError("provider message id must be non-negative")
        return result

    def _rejection_details(self, envelope: dict[str, Any]) -> tuple[int, str, int | None]:
        code = envelope.get("error_code")
        if isinstance(code, bool) or not isinstance(code, int) or not 0 <= code <= _MAX_PROVIDER_ERROR_CODE:
            code = 0
        description = envelope.get("description")
        if not isinstance(description, str):
            description = ""
        return code, description, _extract_retry_after(envelope)


class TelegramArtifactDeliveryRefusal(TelegramArtifactDeliveryError):
    """Connector-policy refusal raised before any provider interaction.

    Carried as a distinct type so a host composition can translate it into a
    ``REFUSED`` receipt (the adapter never acted) if it prefers a receipt over
    the fail-closed raise.
    """
