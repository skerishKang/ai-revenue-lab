"""#3580 host injection boundary for the Claw Telegram SEND delivery adapter.

``create_app`` now accepts ``claw_telegram_artifact_delivery`` and defaults it to
``None``. This module is the one place that says **which** trusted authorities a
host must supply to bind the existing Telegram delivery adapter, and it is a
boundary, not an authority:

```text
WHAT THIS FILE IS
  One fail-closed builder that binds the already-composed sendDocument
  transport to the existing TelegramArtifactDeliveryAdapter using the host's
  trusted binding, bot scope, artifact-material, channel-context and approval
  authorities. When the host supplies only the trusted secret and pairing
  sources, the builder wraps them in the one canonical
  ``TrustedTelegramOutboundBinding`` — so the token/chat-id seam is now
  completable with real components instead of a test double.

WHAT IT IS NOT
  Not a SEND grant, not a bot-token store, not a channel authority and not a
  second delivery adapter. Every authority decision still belongs to
  TelegramArtifactDeliveryAdapter, which re-resolves the trusted channel
  reference, resolves the bot token and chat id inside the trusted binding,
  verifies run/workspace scoped canonical material and consumes the existing
  approval verdict on every execution.
```

The SEND-grant rule is the load-bearing part, mirroring
``claw_drive_upload_host_composition.drive_write_grant_present``: #2010 keeps
Telegram at READ, and a READ capability must never be reinterpreted as SEND
authority. The token, the chat id and the destination are never parameters of
this module — they stay inside the trusted binding and the source-owned
transport, so neither a model nor a browser can supply them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kagent.artifact_delivery_execution_receipt import (
    ArtifactDeliveryExecutionRequest, declare_delivery_execution_request,
)
from kagent.artifact_delivery_intent import DeliveryKind
from kagent.artifact_lineage import LineageArtifactRef
from kagent.connector_trust import ConnectorBindingProjection
from kagent.contracts import ContractError
from kagent.telegram_artifact_delivery import TelegramArtifactDeliveryAdapter
from kagent.telegram_contracts import TelegramBotScope, TelegramOutboundCapability
from kagent.telegram_document_send_composition import TelegramDocumentSendComposition
from kagent.telegram_outbound_binding import (
    TelegramBotTokenSecretPort, TelegramProviderChatIdPort,
    TrustedTelegramOutboundBinding,
)
from kagent.trusted_channel_reference import (
    bind_delivery_intent, resolve_trusted_channel_reference,
)

TELEGRAM_CONNECTOR_ID = "telegram"

#: The existing kagent capability name; not a new vocabulary.
SEND_DOCUMENT_CAPABILITY = TelegramOutboundCapability.SEND_DOCUMENT.value

#: Static contract markers for this boundary.
HOST_INJECTION_BOUNDARY_IMPLEMENTED = True
PRODUCTION_TELEGRAM_DELIVERY_INJECTED = False
NEW_TELEGRAM_AUTHORITY = False
NEW_SECRET_STORE = False
SECOND_DELIVERY_ADAPTER = False
READ_SCOPE_IS_NOT_SEND = True
TOKEN_IS_NEVER_A_PARAMETER = True
DESTINATION_IS_NEVER_A_PARAMETER = True
CANONICAL_OUTBOUND_BINDING_BUILDER = True

#: The host authorities the canonical delivery adapter requires, and the exact
#: methods each one must expose. Checked structurally so a look-alike cannot
#: slip in.
_REQUIRED_HOST_AUTHORITIES = (
    ("trusted_binding", ("resolve_bot_token", "provider_chat_id")),
    ("artifact_material", ("resolve_artifact_material",)),
    ("approval_authority", ("verify_delivery_approval",)),
)


class ClawTelegramDeliveryHostError(ValueError):
    """Boundary error; never carries a token, chat id or provider body."""


@dataclass(frozen=True, slots=True)
class ClawTelegramDeliveryHostState:
    """The boundary's outcome. ``delivery is None`` is the fail-closed answer."""

    delivery: TelegramArtifactDeliveryAdapter | None
    blocked_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.delivery is not None and not isinstance(
            self.delivery, TelegramArtifactDeliveryAdapter
        ):
            raise ClawTelegramDeliveryHostError(
                "the boundary yields the canonical delivery adapter only"
            )
        if self.delivery is not None and self.blocked_reasons:
            raise ClawTelegramDeliveryHostError(
                "an injected delivery adapter cannot also report a blocking reason"
            )

    @property
    def injected(self) -> bool:
        return self.delivery is not None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-telegram-delivery-host-boundary.v1",
            "boundary_implemented": HOST_INJECTION_BOUNDARY_IMPLEMENTED,
            "delivery_injected": self.injected,
            "production_telegram_delivery_injected": (
                PRODUCTION_TELEGRAM_DELIVERY_INJECTED
            ),
            "new_telegram_authority": NEW_TELEGRAM_AUTHORITY,
            "new_secret_store": NEW_SECRET_STORE,
            "second_delivery_adapter": SECOND_DELIVERY_ADAPTER,
            "read_scope_is_not_send": READ_SCOPE_IS_NOT_SEND,
            "token_is_never_a_parameter": TOKEN_IS_NEVER_A_PARAMETER,
            "destination_is_never_a_parameter": DESTINATION_IS_NEVER_A_PARAMETER,
            "blocked_reasons": list(self.blocked_reasons),
            "production_claim": False,
        }


def _carries_telegram_send_authority(binding: ConnectorBindingProjection) -> bool:
    """Capability half of the SEND-grant rule, without a clock."""
    return (
        binding.connector_id == TELEGRAM_CONNECTOR_ID
        and SEND_DOCUMENT_CAPABILITY in binding.granted_capabilities
    )


def telegram_send_grant_present(
    binding: ConnectorBindingProjection | None, *, now: datetime,
) -> bool:
    """True only for a *live* binding that really carries Telegram SEND authority.

    An existing READ-only grant (#2010) is not a SEND grant, and neither is a
    revoked or expired one. Time-dependent revocation stays with the delivery
    adapter, which re-checks the binding on every execution; this helper is the
    single statement of the rule for callers that hold a clock.
    """
    if not isinstance(binding, ConnectorBindingProjection):
        return False
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return False
    return _carries_telegram_send_authority(binding) and binding.usable_at(now)


def _delivery_identity_digest(
    *, workspace_ref: str, run_ref: str, artifact_ref: LineageArtifactRef,
) -> str:
    """Deterministic attempt/intent identity for one artifact delivery.

    Stable across retries, so a repeated request maps to the same logical
    attempt and the adapter's own attempt registry refuses a replay.
    """
    payload = json.dumps({
        "workspace_ref": workspace_ref,
        "run_ref": run_ref,
        "artifact_id": artifact_ref.artifact_id,
        "artifact_integrity_ref": artifact_ref.integrity_ref,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_claw_telegram_delivery_request(
    *,
    channel_context: Any,
    account_ref: str,
    workspace_ref: str,
    run_ref: str,
    artifact_ref: LineageArtifactRef,
    approval_ref: str,
    now: datetime,
    connector_id: str = TELEGRAM_CONNECTOR_ID,
) -> ArtifactDeliveryExecutionRequest:
    """Bind one owner-proved artifact to the *current* trusted Telegram channel.

    The destination is never a parameter: it comes from re-resolving the
    trusted current-channel context the host supplies. The approval handle must
    come from the **existing** approval authority — this function never mints
    one, and an absent handle is a refusal at the caller, not a default here.
    """
    if not callable(channel_context):
        raise ClawTelegramDeliveryHostError("trusted current-channel context required")
    if not isinstance(artifact_ref, LineageArtifactRef):
        raise ClawTelegramDeliveryHostError("canonical artifact reference required")
    if not isinstance(approval_ref, str) or not approval_ref:
        raise ClawTelegramDeliveryHostError("existing send approval reference required")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ClawTelegramDeliveryHostError("trusted aware time required")

    context = channel_context()
    reference = resolve_trusted_channel_reference(
        context, now=now, expected_account_ref=account_ref,
        expected_workspace_ref=workspace_ref,
        supported_connector_ids=(connector_id,),
    )
    digest = _delivery_identity_digest(
        workspace_ref=workspace_ref, run_ref=run_ref, artifact_ref=artifact_ref,
    )
    intent = bind_delivery_intent(
        delivery_intent_id="tgint" + digest[:32],
        artifact_ref=artifact_ref,
        reference=reference,
        workspace_ref=workspace_ref,
        run_ref=run_ref,
        created_at=now,
        approval_ref=approval_ref,
    )
    if intent.delivery_kind is not DeliveryKind.EXTERNAL_CONNECTOR:
        raise ClawTelegramDeliveryHostError(
            "the trusted channel did not resolve to an external connector delivery"
        )
    return declare_delivery_execution_request(
        attempt_ref="tgdlv" + digest[:32],
        intent=intent,
        reference=reference,
        context=context,
        now=now,
        expected_account_ref=account_ref,
        expected_workspace_ref=workspace_ref,
        supported_connector_ids=(connector_id,),
        approval_ref=approval_ref,
    )


def build_canonical_telegram_outbound_binding(
    *,
    scope: TelegramBotScope | None = None,
    secrets: TelegramBotTokenSecretPort | None = None,
    chat_ids: TelegramProviderChatIdPort | None = None,
) -> TrustedTelegramOutboundBinding | None:
    """The one canonical outbound binding a host may inject.

    Returns ``None`` without a trusted bot scope. Supplying no secret or
    pairing source is safe: the binding then refuses every resolution, so it
    cannot resolve a token or a destination for anything.
    """
    if not isinstance(scope, TelegramBotScope):
        return None
    return TrustedTelegramOutboundBinding(
        scope=scope, secrets=secrets, chat_ids=chat_ids,
    )


def build_claw_telegram_delivery_host_state(
    *,
    binding: ConnectorBindingProjection | None = None,
    scope: TelegramBotScope | None = None,
    trusted_binding: Any = None,
    outbound_secrets: TelegramBotTokenSecretPort | None = None,
    outbound_chat_ids: TelegramProviderChatIdPort | None = None,
    artifact_material: Any = None,
    channel_context: Any = None,
    approval_authority: Any = None,
    account_ref: str | None = None,
    actor_ref: str | None = None,
    composition: TelegramDocumentSendComposition | None = None,
) -> ClawTelegramDeliveryHostState:
    """Bind the canonical delivery adapter, or explain exactly what is missing.

    Every input must come from the trusted host. Nothing here reads an
    environment variable, a request body, a model answer or a browser cookie,
    and nothing mints a grant, an approval, a token or a chat id.

    ``trusted_binding`` may be the canonical ``TrustedTelegramOutboundBinding``
    directly, or omitted in favour of ``outbound_secrets`` +
    ``outbound_chat_ids`` — the trusted secret and pairing sources the boundary
    then wraps in that same canonical binding. Both sources are required
    together: a token without a paired destination (or the reverse) cannot
    deliver anything, and the boundary refuses to pretend otherwise.
    """
    reasons: list[str] = []

    if not isinstance(binding, ConnectorBindingProjection):
        reasons.append("no trusted Control Plane connector binding was supplied")
    elif binding.connector_id != TELEGRAM_CONNECTOR_ID:
        reasons.append("the trusted connector binding is not telegram")
    elif not _carries_telegram_send_authority(binding):
        reasons.append(
            "the supplied binding carries no Telegram SEND authority "
            "(#2010 is READ-only); a READ grant is not a SEND grant"
        )

    if not isinstance(scope, TelegramBotScope):
        reasons.append("no trusted Telegram bot scope was supplied")
    elif (
        isinstance(binding, ConnectorBindingProjection)
        and scope.workspace_ref != binding.workspace_ref
    ):
        reasons.append("the Telegram bot scope does not belong to the trusted binding")

    if trusted_binding is None and isinstance(scope, TelegramBotScope):
        if outbound_secrets is not None and outbound_chat_ids is not None:
            trusted_binding = build_canonical_telegram_outbound_binding(
                scope=scope, secrets=outbound_secrets, chat_ids=outbound_chat_ids,
            )

    supplied = {
        "trusted_binding": trusted_binding,
        "artifact_material": artifact_material,
        "approval_authority": approval_authority,
    }
    for name, methods in _REQUIRED_HOST_AUTHORITIES:
        if not all(callable(getattr(supplied[name], method, None)) for method in methods):
            reasons.append(f"no trusted Telegram {name} authority was supplied")

    if not callable(channel_context):
        reasons.append("no trusted current-channel context provider was supplied")
    if not isinstance(account_ref, str) or not account_ref:
        reasons.append("no trusted account reference was supplied")
    if not isinstance(actor_ref, str) or not actor_ref:
        reasons.append("no trusted actor reference was supplied")
    if not isinstance(composition, TelegramDocumentSendComposition):
        reasons.append("no composed Telegram sendDocument port was supplied")

    if reasons:
        return ClawTelegramDeliveryHostState(delivery=None, blocked_reasons=tuple(reasons))

    try:
        delivery = composition.delivery_adapter(
            scope=scope, trusted_binding=trusted_binding,
            artifact_material=artifact_material, channel_context=channel_context,
            approval_authority=approval_authority,
            account_ref=account_ref, actor_ref=actor_ref,
        )
    except ContractError:
        # The existing adapter owns the deeper structural rules (for example a
        # material lookup that does not require run/workspace scope). Fail
        # closed without forwarding its message.
        return ClawTelegramDeliveryHostState(
            delivery=None,
            blocked_reasons=(
                "the trusted Telegram authorities were rejected by the existing "
                "delivery adapter",
            ),
        )
    return ClawTelegramDeliveryHostState(delivery=delivery, blocked_reasons=())


def build_claw_telegram_artifact_delivery(
    **kwargs: Any,
) -> TelegramArtifactDeliveryAdapter | None:
    """The value ``create_app(claw_telegram_artifact_delivery=...)`` accepts."""
    return build_claw_telegram_delivery_host_state(**kwargs).delivery


__all__ = [
    "CANONICAL_OUTBOUND_BINDING_BUILDER",
    "ClawTelegramDeliveryHostError",
    "ClawTelegramDeliveryHostState",
    "HOST_INJECTION_BOUNDARY_IMPLEMENTED",
    "PRODUCTION_TELEGRAM_DELIVERY_INJECTED",
    "READ_SCOPE_IS_NOT_SEND",
    "SEND_DOCUMENT_CAPABILITY",
    "TELEGRAM_CONNECTOR_ID",
    "build_canonical_telegram_outbound_binding",
    "build_claw_telegram_artifact_delivery",
    "build_claw_telegram_delivery_host_state",
    "build_claw_telegram_delivery_request",
    "telegram_send_grant_present",
]
