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
  authorities.

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

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kagent.connector_trust import ConnectorBindingProjection
from kagent.contracts import ContractError
from kagent.telegram_artifact_delivery import TelegramArtifactDeliveryAdapter
from kagent.telegram_contracts import TelegramBotScope, TelegramOutboundCapability
from kagent.telegram_document_send_composition import TelegramDocumentSendComposition

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


def build_claw_telegram_delivery_host_state(
    *,
    binding: ConnectorBindingProjection | None = None,
    scope: TelegramBotScope | None = None,
    trusted_binding: Any = None,
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
    "ClawTelegramDeliveryHostError",
    "ClawTelegramDeliveryHostState",
    "HOST_INJECTION_BOUNDARY_IMPLEMENTED",
    "PRODUCTION_TELEGRAM_DELIVERY_INJECTED",
    "READ_SCOPE_IS_NOT_SEND",
    "SEND_DOCUMENT_CAPABILITY",
    "TELEGRAM_CONNECTOR_ID",
    "build_claw_telegram_artifact_delivery",
    "build_claw_telegram_delivery_host_state",
    "telegram_send_grant_present",
]
