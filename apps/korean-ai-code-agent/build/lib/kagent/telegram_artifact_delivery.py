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
  -> canonical artifact material        (#3594 authority, run/workspace scoped)
  -> existing approval authority        (opaque verdict consumed, never minted)
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
  never a parameter, never returned, never logged and never projected;
* the provider chat id is held to the **existing** runtime contract and
  nothing more: an exact ``int`` (``bool`` rejected). No positive-only or
  non-zero policy is invented here, because Telegram group/supergroup/channel
  identities are legitimately negative and the existing runtime accepts
  them:

  ```text
  NEGATIVE_PROVIDER_CHAT_ID_SUPPORTED=YES
  POSITIVE_ONLY_CHAT_ID_POLICY=NO
  ```

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
artifact authority — and is verified inside the adapter before any provider
call.

The lookup is **run/workspace scoped by contract**, not by convention: the
resolver port cannot be called without the delivering request's
``workspace_ref`` and ``run_ref``, the adapter rejects a resolver whose
signature does not accept them, and the resolved #3594 record's own
``workspace_ref``/``run_ref`` must correlate exactly with the request. Knowing
only ``(artifact_id, integrity_ref)`` can therefore never surface another
run's or another workspace's material:

```text
LOCAL_PATH_ONLY_REMOTE_DELIVERY=NO
ARTIFACT_RESOLVER_SCOPED_TO_RUN_AND_WORKSPACE=YES
ARTIFACT_WORKSPACE_SCOPE_VERIFIED=YES
ARTIFACT_RUN_SCOPE_VERIFIED=YES
SECOND_ARTIFACT_AUTHORITY=0
```

### Approval boundary — opaque, consumed, never defined here

``ArtifactDeliveryExecutionRequest.approval_ref`` is an opaque handle into the
**existing** Engine approval-continuation authority (#3631 states this
explicitly: "no approval store, state machine or self-approval exists here").
This adapter therefore holds no approval vocabulary at all: it neither mints an
approval nor defines what an approval is *over*. It injects an
``TelegramDeliveryApprovalPort`` and consumes a single question — "is this
``approval_ref`` valid for this execution request?" — answered in the existing
``kagent.telegram_contracts.TelegramOutboundPreflightDecision`` vocabulary:

```text
APPROVAL_VERDICT_IS_OPAQUE=YES
APPROVAL_MATERIAL_RECONSTRUCTED_IN_ADAPTER=NO
NEW_APPROVAL_MATERIAL_SCHEMA=NO
CUSTOM_APPROVAL_FINGERPRINT_AUTHORITY=NO
SECOND_APPROVAL_AUTHORITY=0
FAKE_QUARANTINE_EVIDENCE=NO
```

The existing ``telegram_outbound_preflight()`` is **not** reused here, and
that is a semantic decision rather than an oversight.
``TelegramOutboundMaterial`` requires a ``TelegramApprovedDocument``, and
``TelegramApprovedDocument`` mandates ``quarantine_evidence_ref`` — *inbound*
file-quarantine evidence belonging to the B54 inbound-file flow. An **outbound**
#3594 canonical artifact carries its provenance through the registration record
(identity + integrity + run/workspace), never through inbound quarantine
evidence. Forcing the outbound record into that shape would mean inventing a
quarantine reference, so the preflight is left untouched and the existing
authority is consumed opaquely instead:

```text
REAL_EXISTING_PRELIGHT_REUSABLE=NO
PREFLIGHT_REUSE_BLOCKED_BY_SEMANTIC_MISMATCH=YES
```

A missing approval reference produces a ``REFUSED`` receipt with zero side
effects; an approval that the existing authority does not accept for this
request fails closed. Neither path can reach the provider.

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
digest, and an optional bounded rate-limit projection. A transport exception
contributes nothing but its exception *class name*, never its message:

```text
RAW_PROVIDER_ERROR_BODY=0
PROVIDER_ERROR_TEXT_IN_RECEIPT=0
AUTO_RETRY=NO
SECOND_SEND=0
```

### Refusal semantics

A request that is structurally inadmissible (wrong delivery kind, failed
re-resolution, unpaired conversation, noncanonical artifact, out-of-scope
artifact provenance, replay) raises and never reaches the provider. A request
that carries no approval reference at all produces a ``REFUSED`` receipt with
zero external side effects — the existing terminal vocabulary's "the adapter
never acted". An approval the existing authority rejects for this request fails
closed, because that is evidence of a mismatch rather than of an absent
decision.

### What this module deliberately does not do

* no real network transport: the document-send port is injected, and this
  slice ships no transport implementation, no endpoint host literal and no
  live path. Wiring the production transport behind the port is a separate,
  explicitly authorized change with its own live gate;
* no second execution/receipt/connector-identity/artifact/approval
  authority: receipts are built only through #3631's
  ``build_delivery_receipt`` (correlation copied from the request, so a
  receipt can never be pointed at another attempt), and the approval is an
  opaque verdict handed over by the existing authority — no fingerprint, no
  material schema and no approval store live here;
* no durable store, no schema, no persisted state.

Zero network, zero model, zero provider calls at import or construction: the
adapter is hermetic by construction and every collaborator is injected.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import inspect
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
    TelegramOutboundPreflightDecision,
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

# --- provider chat identity: the existing runtime contract, nothing added -----
#: Telegram group/supergroup/channel ids are negative, and the existing
#: ``TelegramTrustedBindingPort`` consumer only demands an exact ``int``.
NEGATIVE_PROVIDER_CHAT_ID_SUPPORTED = True
POSITIVE_ONLY_CHAT_ID_POLICY = False
CHAT_ID_RESOLVED_FROM_TRUSTED_BINDING_ONLY = True

# --- approval: opaque verdict, no local material semantics -------------------
#: The adapter asks one question of the existing approval authority and
#: consumes its existing decision vocabulary. No approval is minted, stored or
#: self-approved here, and no approval *material* schema is defined here.
APPROVAL_VERDICT_IS_OPAQUE = True
APPROVAL_MATERIAL_RECONSTRUCTED_IN_ADAPTER = False
NEW_APPROVAL_MATERIAL_SCHEMA = False
CUSTOM_APPROVAL_FINGERPRINT_AUTHORITY = False
LOCAL_APPROVAL_STORE = False
LOCAL_APPROVAL_MINT = False
APPROVAL_FINGERPRINT_AUTHORITY_IN_ADAPTER = 0

#: ``telegram_outbound_preflight`` is left untouched: its material contract is
#: the inbound quarantine flow, so reusing it for an outbound canonical
#: artifact would require fabricating quarantine evidence.
REAL_EXISTING_PRELIGHT_REUSABLE = False
PREFLIGHT_REUSE_BLOCKED_BY_SEMANTIC_MISMATCH = True
FAKE_QUARANTINE_EVIDENCE = False

# --- artifact provenance ----------------------------------------------------
#: The material lookup is run/workspace scoped by contract and by verified
#: record correlation, so ``(artifact_id, integrity_ref)`` alone can never
#: resolve another run's or another workspace's material.
ARTIFACT_RESOLVER_SCOPED_TO_RUN_AND_WORKSPACE = True
ARTIFACT_WORKSPACE_SCOPE_VERIFIED = True
ARTIFACT_RUN_SCOPE_VERIFIED = True

# --- provider error boundary ------------------------------------------------
#: Nothing but a kind, a digest-derived reference and a bounded rate-limit
#: projection ever leaves the adapter.
RAW_PROVIDER_ERROR_BODY = 0
PROVIDER_ERROR_TEXT_IN_RECEIPT = 0

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

    A specialization of the existing ``kagent.telegram_bot_runtime.
    TelegramBotApiRequestPort`` provider seam for the document upload: the same
    trusted-token / bounded-timeout / provider-envelope discipline, with
    document material added. The adapter core never opens a network path. A
    production transport (the official Bot API document upload, multipart form
    encoding over TLS) is a separate, explicitly authorized change that plugs in
    behind this port; tests always inject a hermetic fake.

    ``provider_chat_id`` arrives already resolved from the trusted binding and
    is sign-agnostic: Telegram group/channel identities are negative.
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

    The lookup is deliberately **not** a global ``artifact_id`` lookup: the
    delivering run's and workspace's scope are mandatory arguments, so an
    implementation cannot be called without them and the adapter additionally
    verifies that the resolved #3594 record's own ``workspace_ref``/
    ``run_ref`` correlate exactly with the request. This is what makes
    cross-workspace and wrong-run material unreachable rather than merely
    discouraged.
    """

    def resolve_artifact_material(
        self,
        artifact_ref: LineageArtifactRef,
        *,
        workspace_ref: str,
        run_ref: str,
    ) -> TelegramArtifactMaterial | None:  # pragma: no cover - structural port only
        ...


@runtime_checkable
class TelegramDeliveryApprovalPort(Protocol):
    """Injected seam onto the **existing** approval authority.

    ``ArtifactDeliveryExecutionRequest.approval_ref`` is an opaque handle into
    the existing Engine approval-continuation authority. This adapter asks one
    question of that authority — "is this reference valid for this execution
    request?" — and consumes the existing
    ``TelegramOutboundPreflightDecision`` vocabulary in return.

    The adapter deliberately has no approval *material* semantics of its own:
    it never receives an approval record, never recomputes an approval
    fingerprint, never mints an approval and never stores one. Whatever the
    production composition binds here is the authority's own verifier; the
    tests bind a hermetic fake.
    """

    def verify_delivery_approval(
        self,
        *,
        approval_ref: str,
        request: ArtifactDeliveryExecutionRequest,
    ) -> TelegramOutboundPreflightDecision:  # pragma: no cover - structural port only
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


def _resolver_takes_scope(resolver: Any) -> bool:
    """True when the material lookup structurally requires run/workspace scope.

    Rejecting the ``**kwargs`` escape hatch matters: a lookup that swallows
    arbitrary keywords could accept the scope and ignore it, which is exactly
    the global-lookup shape this contract forbids.
    """

    try:
        parameters = inspect.signature(resolver.resolve_artifact_material).parameters
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return False
    accepted = {
        name
        for name, parameter in parameters.items()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {"workspace_ref", "run_ref"} <= accepted


def _provider_int(value: Any, field_name: str) -> int:
    """The existing provider-identity rule: exact ``int``, ``bool`` rejected.

    Deliberately no sign/range policy — Telegram group and channel identities
    are negative, and the existing ``kagent.telegram_bot_runtime`` runtime
    applies no such rule either.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"provider {field_name} must be an exact integer")
    return value


def _bounded_timeout(value: Any) -> int:
    """Same bounded timeout rule the existing provider seam enforces."""

    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 60:
        raise ContractError("document send timeout must be between 1 and 60 seconds")
    return value


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
        approval_authority: TelegramDeliveryApprovalPort,
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
        if not _resolver_takes_scope(artifact_material):
            raise TelegramArtifactDeliveryError(
                "artifact material lookup must require the delivering workspace_ref and run_ref"
            )
        if not callable(getattr(approval_authority, "verify_delivery_approval", None)):
            raise TelegramArtifactDeliveryError(
                "approval_authority does not implement the existing approval verification seam"
            )
        _require_callable(channel_context, "channel_context")
        self._scope = scope
        self._binding = trusted_binding
        self._document_send = document_send
        self._material = artifact_material
        self._channel_context = channel_context
        self._approval = approval_authority
        self._account_ref = _bounded_ref(account_ref, "account_ref")
        self._actor_ref = _bounded_ref(actor_ref, "actor_ref")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._attempts = attempt_registry or InMemoryDeliveryAttemptRegistry()

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

        # 5. Canonical artifact material, resolved under this delivery's run and
        #    workspace scope and verified against the request ref + provenance.
        material = self._material.resolve_artifact_material(
            request.artifact_ref,
            workspace_ref=request.workspace_ref,
            run_ref=request.run_ref,
        )
        if material is None:
            raise TelegramArtifactDeliveryError(
                "artifact reference does not resolve in the canonical artifact authority"
            )
        self._verify_material(material, request)

        # 6. The existing approval authority is asked one question and answers
        #    in its own vocabulary. No approval is minted, read or reconstructed
        #    here, and no provider call happens before it answers ALLOW.
        try:
            self._consume_approval(request)
        except TelegramArtifactDeliveryRefusal:
            return build_delivery_receipt(
                receipt_ref=_receipt_ref_for(request),
                request=request,
                terminal_status=DeliveryTerminalStatus.REFUSED,
                started_at=started_at,
                completed_at=self._clock(),
            )

        # 7. Resolve token + provider chat id inside the trusted boundary. The
        #    chat identity is held to the existing runtime contract only: an
        #    exact int, sign-agnostic, because group/channel ids are negative.
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

        # 8. One bounded provider call; the result is normalized into the
        #    existing taxonomy and the existing receipt contract.
        try:
            envelope = self._document_send.send_document(
                token=token,
                provider_chat_id=provider_chat_id,
                document_bytes=material.document_bytes,
                filename=material.record.filename,
                mime_type=material.record.media_type,
                timeout_seconds=_bounded_timeout(_MAX_DOCUMENT_SEND_TIMEOUT_SECONDS),
            )
        except ContractError:
            raise
        except (OSError, TimeoutError) as exc:
            # The exception *class name* is the only thing that reaches the
            # receipt; the message is dropped because a transport can echo a
            # provider body (and a URL carrying the bot token) inside it.
            return self._failure_receipt(
                request,
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
            return self._failure_receipt(
                request,
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

    def _failure_receipt(
        self,
        request: ArtifactDeliveryExecutionRequest,
        *,
        started_at: datetime,
        completed_at: datetime,
        provider_error: ConnectorProviderError,
    ) -> ArtifactDeliveryReceipt:
        """Terminal failure receipt.

        The existing taxonomy's ``retryable`` flag is the single source of
        truth for the terminal split, so the receipt can never disagree with
        the normalized provider error it carries.
        """

        return build_delivery_receipt(
            receipt_ref=_receipt_ref_for(request),
            request=request,
            terminal_status=(
                DeliveryTerminalStatus.FAILED_RETRYABLE
                if provider_error.retryable
                else DeliveryTerminalStatus.FAILED_TERMINAL
            ),
            started_at=started_at,
            completed_at=completed_at,
            provider_error=provider_error,
        )

    def _verify_material(
        self, material: TelegramArtifactMaterial, request: ArtifactDeliveryExecutionRequest
    ) -> None:
        record = material.record
        if record.artifact_id != request.artifact_ref.artifact_id:
            raise TelegramArtifactDeliveryError(
                "material record identity does not match the requested artifact"
            )
        if record.integrity_ref != request.artifact_ref.integrity_ref:
            raise TelegramArtifactDeliveryError(
                "material record integrity does not match the requested artifact"
            )
        # Run/workspace correlation is required, not optional: an artifact whose
        # canonical record does not name this delivery's workspace and run
        # cannot be proven to belong to it, so the delivery fails closed.
        if record.workspace_ref != request.workspace_ref:
            raise TelegramArtifactDeliveryError(
                "artifact provenance does not correlate with the delivering workspace"
            )
        if record.run_ref != request.run_ref:
            raise TelegramArtifactDeliveryError(
                "artifact provenance does not correlate with the delivering run"
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

    def _consume_approval(self, request: ArtifactDeliveryExecutionRequest) -> None:
        """Ask the existing approval authority; consume an opaque verdict.

        The adapter never sees an approval record, never recomputes an approval
        fingerprint and never decides what an approval covers. Absence of a
        reference is a connector-policy refusal (``REFUSED``); a reference the
        existing authority does not accept for this request is a mismatch and
        fails closed.
        """

        if request.approval_ref is None:
            raise TelegramArtifactDeliveryRefusal("no approval reference on the delivery request")
        decision = self._approval.verify_delivery_approval(
            approval_ref=request.approval_ref,
            request=request,
        )
        if not isinstance(decision, TelegramOutboundPreflightDecision):
            raise TelegramArtifactDeliveryError(
                "the approval authority returned an unusable verdict"
            )
        if decision is not TelegramOutboundPreflightDecision.ALLOW:
            raise TelegramArtifactDeliveryError(
                "the existing approval authority does not accept this delivery request"
            )

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
