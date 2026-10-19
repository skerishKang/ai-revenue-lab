"""#3580 outbound ``TelegramTrustedBindingPort`` for approved SEND.

``telegram_artifact_delivery.TelegramArtifactDeliveryAdapter`` resolves the bot
token and the destination chat id **inside** the adapter through an injected
``TelegramTrustedBindingPort``. The only implementation that existed was the
inbound-only ``StaticTelegramTrustedAuthority`` in the chat app, which exposes
neither ``resolve_bot_token`` nor ``provider_chat_id``. No outbound binding
existed anywhere, so the Telegram SEND path could not be composed even with a
grant.

This module is that binding. It introduces no secret store and no connector
identity:

```text
WHAT THIS FILE IS
  A scope-bound adapter that resolves the bot token and the provider chat id
  from two injected trusted ports, and refuses anything outside the trusted
  TelegramBotScope.

WHAT IT IS NOT
  Not a token store, not a pairing authority, not a SEND grant and not a
  transport. The token is resolved from the existing trusted secret source on
  every call (no cache, so revocation is immediate); the provider chat id is
  resolved from the same trusted pairing authority that produced the scope.
```

Boundaries, all fail-closed:

* ``binding_ref``/``bot_ref`` must be the scope's own — a foreign bot or binding
  can never be addressed;
* ``chat_ref`` must be a chat already paired in the scope, so a caller cannot
  invent a destination;
* the token must satisfy the existing ``kagent.telegram_bot_runtime`` token
  contract and the chat id the existing exact-integer contract (negative group
  and channel ids stay valid);
* an unconfigured port refuses, and no token or chat id reaches a projection,
  an exception message or a log line.

Construction performs no I/O, and nothing here sends anything: an actual
sendDocument is the adapter's job after the existing channel re-resolution,
scoped canonical material check and approval verdict, and #2010 keeps Telegram
SEND unauthorized.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import ContractError
from .telegram_bot_runtime import _bot_token, _provider_int
from .telegram_contracts import TelegramBotScope

TELEGRAM_OUTBOUND_BINDING_CONTRACT_VERSION = "claw-telegram-outbound-binding.v1"

#: Static contract markers for this binding.
NEW_SECRET_STORE = False
NEW_CONNECTOR_IDENTITY_AUTHORITY = False
TOKEN_CACHED = False
TOKEN_IN_MODEL_CONTEXT = False
TOKEN_IN_REQUEST_BODY = False
CHAT_ID_FROM_REQUEST_BODY = False
CHAT_ID_FROM_MODEL_CONTEXT = False
CONSTRUCTION_PROVIDER_CALLS = 0
PRODUCTION_OUTBOUND_BINDING_COMPOSED = False


class TelegramOutboundBindingError(ContractError):
    """Fail-closed resolution error; never carries a token or a chat id."""


class TelegramBotTokenSecretPort(Protocol):
    """Existing trusted secret source for one bot binding.

    In production this is the same server-side secret/binding lookup the chat
    app already uses for the Telegram webhook secret; it is **not** a new store
    and it must never be reachable from a model prompt or a browser request.
    """

    def resolve_bot_token(self, *, binding_ref: str, bot_ref: str) -> bytes | None: ...


class TelegramProviderChatIdPort(Protocol):
    """Existing trusted pairing authority, read in the outbound direction.

    It must be the reverse lookup of the *same* authority that produced the
    ``TelegramBotScope`` (the pairing identity map the inbound route already
    uses), so an outbound destination can never disagree with the paired chat.
    """

    def resolve_provider_chat_id(
        self, *, binding_ref: str, bot_ref: str, chat_ref: str,
    ) -> int | None: ...


class UnconfiguredTelegramBotTokenSecretPort:
    """Refuses when no trusted secret source is wired."""

    def resolve_bot_token(self, *, binding_ref: str, bot_ref: str) -> bytes | None:
        return None


class UnconfiguredTelegramProviderChatIdPort:
    """Refuses when no trusted pairing authority is wired."""

    def resolve_provider_chat_id(
        self, *, binding_ref: str, bot_ref: str, chat_ref: str,
    ) -> int | None:
        return None


@dataclass(frozen=True, slots=True)
class TrustedTelegramOutboundBinding:
    """``TelegramTrustedBindingPort`` restricted to the trusted bot scope."""

    scope: TelegramBotScope
    secrets: TelegramBotTokenSecretPort | None = None
    chat_ids: TelegramProviderChatIdPort | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, TelegramBotScope):
            raise TelegramOutboundBindingError("trusted Telegram bot scope required")
        if self.secrets is not None and not callable(
            getattr(self.secrets, "resolve_bot_token", None)
        ):
            raise TelegramOutboundBindingError(
                "bot token secret source must resolve a bot token"
            )
        if self.chat_ids is not None and not callable(
            getattr(self.chat_ids, "resolve_provider_chat_id", None)
        ):
            raise TelegramOutboundBindingError(
                "provider chat id source must resolve a provider chat id"
            )

    # --- shared scope checks ------------------------------------------------

    def _require_scope_identity(self, *, binding_ref: str, bot_ref: str) -> None:
        if (
            not isinstance(binding_ref, str)
            or not isinstance(bot_ref, str)
            or binding_ref != self.scope.binding_ref
            or bot_ref != self.scope.bot_ref
        ):
            raise TelegramOutboundBindingError(
                "the requested binding or bot is outside the trusted Telegram scope"
            )

    # --- TelegramTrustedBindingPort ----------------------------------------

    def resolve_bot_token(self, *, binding_ref: str, bot_ref: str) -> bytes:
        """Resolve the bot token for the scope's own binding, or refuse."""
        self._require_scope_identity(binding_ref=binding_ref, bot_ref=bot_ref)
        source = self.secrets
        if source is None:
            raise TelegramOutboundBindingError(
                "no trusted Telegram bot token source is configured"
            )
        try:
            raw = source.resolve_bot_token(binding_ref=binding_ref, bot_ref=bot_ref)
        except Exception:
            # A secret source failure can carry provider or store detail.
            raise TelegramOutboundBindingError(
                "trusted Telegram bot token is unavailable"
            ) from None
        if not isinstance(raw, bytes) or not raw:
            raise TelegramOutboundBindingError(
                "trusted Telegram bot token is unavailable"
            )
        try:
            # Reuse the existing trusted token contract; never re-implement it.
            _bot_token(raw)
        except ContractError:
            raise TelegramOutboundBindingError(
                "trusted Telegram bot token is unavailable"
            ) from None
        return raw

    def provider_chat_id(self, *, binding_ref: str, bot_ref: str, chat_ref: str) -> int:
        """Resolve the paired chat's provider id, or refuse.

        The chat must already be paired in the scope, so a caller cannot invent
        or redirect a destination.
        """
        self._require_scope_identity(binding_ref=binding_ref, bot_ref=bot_ref)
        if not isinstance(chat_ref, str) or not chat_ref:
            raise TelegramOutboundBindingError(
                "the requested chat is not paired in the trusted Telegram scope"
            )
        try:
            paired = self.scope.chat(chat_ref)
        except ContractError:
            # The scope's own reference contract rejects a malformed chat ref.
            paired = None
        if paired is None:
            raise TelegramOutboundBindingError(
                "the requested chat is not paired in the trusted Telegram scope"
            )
        source = self.chat_ids
        if source is None:
            raise TelegramOutboundBindingError(
                "no trusted Telegram provider chat id source is configured"
            )
        try:
            resolved = source.resolve_provider_chat_id(
                binding_ref=binding_ref, bot_ref=bot_ref, chat_ref=chat_ref,
            )
        except Exception:
            raise TelegramOutboundBindingError(
                "trusted Telegram provider chat id is unavailable"
            ) from None
        if resolved is None:
            raise TelegramOutboundBindingError(
                "trusted Telegram provider chat id is unavailable"
            )
        try:
            # Reuse the existing provider identity rule: exact int, bool
            # rejected, negative group/channel ids valid.
            return _provider_int(resolved, "chat id")
        except ContractError:
            raise TelegramOutboundBindingError(
                "trusted Telegram provider chat id is unavailable"
            ) from None

    # --- diagnostics --------------------------------------------------------

    def safe_dict(self) -> dict[str, Any]:
        """Projection safe to log: no token, no chat id, no destination."""
        return {
            "contract_version": TELEGRAM_OUTBOUND_BINDING_CONTRACT_VERSION,
            "binding_ref": self.scope.binding_ref,
            "bot_ref": self.scope.bot_ref,
            "workspace_ref": self.scope.workspace_ref,
            "paired_chat_count": len(self.scope.paired_chats),
            "token_source_configured": self.secrets is not None,
            "chat_id_source_configured": self.chat_ids is not None,
            "token_cached": TOKEN_CACHED,
            "token_in_model_context": TOKEN_IN_MODEL_CONTEXT,
            "chat_id_from_request_body": CHAT_ID_FROM_REQUEST_BODY,
            "new_secret_store": NEW_SECRET_STORE,
            "new_connector_identity_authority": NEW_CONNECTOR_IDENTITY_AUTHORITY,
            "construction_provider_calls": CONSTRUCTION_PROVIDER_CALLS,
            "production_outbound_binding_composed": (
                PRODUCTION_OUTBOUND_BINDING_COMPOSED
            ),
            "production_claim": False,
        }


def build_trusted_telegram_outbound_binding(
    *,
    scope: TelegramBotScope | None = None,
    secrets: TelegramBotTokenSecretPort | None = None,
    chat_ids: TelegramProviderChatIdPort | None = None,
) -> TrustedTelegramOutboundBinding | None:
    """Build the outbound binding, or ``None`` when no trusted scope exists.

    Supplying no ports is the normal deployed state: the binding still refuses
    every resolution, so it is safe to construct and impossible to use without
    an explicitly authorized secret and pairing source.
    """
    if not isinstance(scope, TelegramBotScope):
        return None
    return TrustedTelegramOutboundBinding(
        scope=scope, secrets=secrets, chat_ids=chat_ids,
    )


__all__ = [
    "CHAT_ID_FROM_MODEL_CONTEXT",
    "CHAT_ID_FROM_REQUEST_BODY",
    "CONSTRUCTION_PROVIDER_CALLS",
    "NEW_CONNECTOR_IDENTITY_AUTHORITY",
    "NEW_SECRET_STORE",
    "PRODUCTION_OUTBOUND_BINDING_COMPOSED",
    "TELEGRAM_OUTBOUND_BINDING_CONTRACT_VERSION",
    "TOKEN_CACHED",
    "TOKEN_IN_MODEL_CONTEXT",
    "TelegramBotTokenSecretPort",
    "TelegramOutboundBindingError",
    "TelegramProviderChatIdPort",
    "TrustedTelegramOutboundBinding",
    "UnconfiguredTelegramBotTokenSecretPort",
    "UnconfiguredTelegramProviderChatIdPort",
    "build_trusted_telegram_outbound_binding",
]
