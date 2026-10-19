"""#3580 composition root for the existing trusted Telegram SEND port.

``telegram_document_transport.py`` already owns the concrete Bot API
``sendDocument`` multipart transport (``StdlibTelegramDocumentSendPort``) and
``telegram_artifact_delivery.py`` already owns the connector-owned
``TelegramArtifactDeliveryAdapter``. What no file owned was the one place that
assembles them for a trusted host, which is why the canonical flag
``PRODUCTION_TELEGRAM_SEND_ACTIVATED`` still reads ``False`` and the only
callers of the real transport were its own hermetic tests.

This module is that place, and it is deliberately powerless:

```text
WHAT THIS FILE IS
  One composition root that binds the existing sendDocument transport to the
  existing delivery adapter for an authorized Control Plane host.

WHAT IT IS NOT
  Not a Telegram SEND grant, not a bot-token store and not a channel authority.
  Assembling the objects changes nothing about whether a document may be sent:
  #2010 keeps Telegram SEND unauthorized and no live canary has been run. The
  adapter still re-resolves the trusted channel, resolves the token inside the
  trusted binding, verifies scoped canonical material and consumes the existing
  approval verdict, so a composed adapter still refuses before any socket.
```
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import telegram_document_transport as _transport
from .artifact_delivery_execution_receipt import InMemoryDeliveryAttemptRegistry
from .contracts import ContractError
from .telegram_artifact_delivery import TelegramArtifactDeliveryAdapter
from .telegram_bot_runtime import TELEGRAM_API_HOST
from .telegram_contracts import TelegramBotScope
from .telegram_document_transport import StdlibTelegramDocumentSendPort

TELEGRAM_SEND_COMPOSITION_CONTRACT_VERSION = "claw-telegram-send-composition.v1"

#: The composition root now exists. This records source wiring only; the SEND
#: grant, the production host and the live canary below are still closed.
TELEGRAM_DOCUMENT_SEND_COMPOSITION_ROOT_WIRED = True

#: #2010 keeps Telegram SEND unauthorized. No authority is created here.
TELEGRAM_SEND_GRANT_AUTHORIZED = False
LIVE_TELEGRAM_SEND_CANARY = False
PRODUCTION_ACTIVATION = "BLOCKED"
NEW_TELEGRAM_AUTHORITY = False
NEW_SECRET_STORE = False
AUTO_RETRY = False

#: The composition root's entire caller surface, pinned as data. It can carry
#: no token, no chat id, no endpoint and no destination.
TELEGRAM_SEND_COMPOSITION_PARAMETERS = ("document_send",)

#: Construction-time I/O counters, kept as data a reviewer can assert against.
TELEGRAM_SEND_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS = 0
TELEGRAM_SEND_COMPOSITION_CONSTRUCTION_TOKEN_RESOLUTIONS = 0


class TelegramSendCompositionError(ContractError):
    """Fail-closed composition error; no token, chat id or provider detail leaks."""


@dataclass(frozen=True, slots=True)
class TelegramDocumentSendComposition:
    """The assembled Telegram SEND stack, in the order the adapter consumes it.

    Holding the objects is not permission to use them: ``armed`` stays ``False``
    for every instance that can exist in this build, because the SEND grant and
    the live canary are both closed and no production host has composed one.
    """

    document_send: StdlibTelegramDocumentSendPort

    def __post_init__(self) -> None:
        # Structural defence against a second stack: a composition that held a
        # look-alike transport would be a new send authority wearing a canonical
        # name. The adapter is the existing one and re-checks everything itself.
        if not isinstance(self.document_send, StdlibTelegramDocumentSendPort):
            raise TelegramSendCompositionError(
                "the composition root wires the canonical Telegram sendDocument transport only"
            )

    @property
    def blocked_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if _transport.PRODUCTION_TELEGRAM_SEND_ACTIVATED is not True:
            reasons.append("no production host composes the Telegram sendDocument port")
        if TELEGRAM_SEND_GRANT_AUTHORIZED is not True:
            reasons.append("the Telegram SEND grant is not authorized (#2010)")
        if LIVE_TELEGRAM_SEND_CANARY is not True:
            reasons.append("no live Telegram delivery canary has been run")
        return tuple(reasons)

    @property
    def armed(self) -> bool:
        return False

    def delivery_adapter(
        self, *,
        scope: TelegramBotScope, trusted_binding: Any, artifact_material: Any,
        channel_context: Callable[[], Any], approval_authority: Any,
        account_ref: str, actor_ref: str,
        clock: Callable[[], datetime] | None = None,
        attempt_registry: InMemoryDeliveryAttemptRegistry | None = None,
    ) -> TelegramArtifactDeliveryAdapter:
        """Assemble the canonical adapter around the composed transport.

        The adapter independently re-resolves the trusted channel reference,
        resolves the bot token and chat id inside the trusted binding, verifies
        run/workspace scoped canonical material and consumes the existing
        approval verdict. This method cannot relax any of them: it only
        guarantees the adapter receives the canonical composed transport instead
        of a caller-supplied substitute. The token is never a parameter here.
        """
        return TelegramArtifactDeliveryAdapter(
            scope=scope, trusted_binding=trusted_binding,
            document_send=self.document_send, artifact_material=artifact_material,
            channel_context=channel_context, approval_authority=approval_authority,
            account_ref=account_ref, actor_ref=actor_ref,
            **({"clock": clock} if clock is not None else {}),
            **({} if attempt_registry is None else {"attempt_registry": attempt_registry}),
        )

    def safe_dict(self) -> dict[str, Any]:
        """Projection safe to log: no token, no chat id, no artifact bytes."""
        return {
            "contract_version": TELEGRAM_SEND_COMPOSITION_CONTRACT_VERSION,
            "composition_root_wired": TELEGRAM_DOCUMENT_SEND_COMPOSITION_ROOT_WIRED,
            # Read through the transport module, not copied: one flag, one authority.
            "production_telegram_send_activated": (
                _transport.PRODUCTION_TELEGRAM_SEND_ACTIVATED
            ),
            "telegram_send_grant_authorized": TELEGRAM_SEND_GRANT_AUTHORIZED,
            "live_telegram_send_canary": LIVE_TELEGRAM_SEND_CANARY,
            "production_activation": PRODUCTION_ACTIVATION,
            "new_telegram_authority": NEW_TELEGRAM_AUTHORITY,
            "new_secret_store": NEW_SECRET_STORE,
            "provider_host": TELEGRAM_API_HOST,
            "document_send_port": StdlibTelegramDocumentSendPort.__name__,
            "blocked_reasons": list(self.blocked_reasons),
            "armed": self.armed,
            "construction_provider_requests": (
                TELEGRAM_SEND_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS
            ),
            "construction_token_resolutions": (
                TELEGRAM_SEND_COMPOSITION_CONSTRUCTION_TOKEN_RESOLUTIONS
            ),
            "production_claim": False,
        }


def build_telegram_document_send_composition(
    *,
    document_send: StdlibTelegramDocumentSendPort | None = None,
) -> TelegramDocumentSendComposition:
    """Wire the canonical Telegram SEND stack from server-owned config.

    The transport endpoint, multipart encoding, timeout and response bound all
    come from source. Construction performs no provider request, resolves no
    token and reads no chat id; ``armed`` is still ``False`` because the SEND
    grant and the live canary are closed.
    """
    if document_send is not None and not isinstance(
        document_send, StdlibTelegramDocumentSendPort
    ):
        raise TelegramSendCompositionError(
            "the composition root wires the canonical Telegram sendDocument transport only"
        )
    return TelegramDocumentSendComposition(
        document_send=document_send if document_send is not None
        else StdlibTelegramDocumentSendPort(),
    )


__all__ = [
    "TELEGRAM_DOCUMENT_SEND_COMPOSITION_ROOT_WIRED",
    "TELEGRAM_SEND_COMPOSITION_CONTRACT_VERSION",
    "TELEGRAM_SEND_COMPOSITION_PARAMETERS",
    "TELEGRAM_SEND_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS",
    "TELEGRAM_SEND_COMPOSITION_CONSTRUCTION_TOKEN_RESOLUTIONS",
    "TELEGRAM_SEND_GRANT_AUTHORIZED",
    "LIVE_TELEGRAM_SEND_CANARY",
    "PRODUCTION_ACTIVATION",
    "TelegramDocumentSendComposition",
    "TelegramSendCompositionError",
    "build_telegram_document_send_composition",
]
