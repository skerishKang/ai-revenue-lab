"""Thin Telegram inbound consumer seam for Claw (#2315).

Architecture authority: #2312 ``RETAIN_BUSINESS_MVP``. The canonical Telegram
authority remains the B54 business-MVP contracts
(``kagent.telegram_contracts``); this module adds no transport, no token
authority, no outbound send and no approval callback. It is the B62 server-side
ingress host that:

1. verifies the Telegram webhook secret header (``X-Telegram-Bot-Api-Secret-Token``
   equality at a trusted ingress, per ``TelegramWebhookProof`` semantics);
2. resolves raw provider chat/sender ids to Padiem ``chat_ref``/``sender_ref``
   through a trusted binding authority that lives only server-side;
3. authorizes the update through the canonical ``TelegramBotScope`` paired-chat
   contract (provider identity alone is never Padiem authority);
4. deduplicates update ids through the canonical replay disposition;
5. projects bounded, secret-redacted text and maps accepted updates onto the
   existing ``ManualIntakeChannel.TELEGRAM`` Claw manual-intake path.

Fail-closed rules: unknown bindings, bad/missing webhook proofs and oversized
text never accept an update; unpaired chats and non-allowlisted senders are
skipped without privileged intake; error and success projections never contain
the webhook secret, any bot token, or the raw provider update object. There is
deliberately no ``sendMessage``/callback path in this module: outbound actions
remain behind their own separate gate (#2312/#2315).
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from starlette.requests import Request
from starlette.responses import JSONResponse

from kagent.connector_trust import InMemoryEventReplayGuard, ReplayDisposition
from kagent.contracts import ContractError
from kagent.manual_intake import (
    ManualIntakeAction,
    ManualIntakeChannel,
    ManualIntakeRequest,
    ManualIntakeRouter,
)
from kagent.telegram_contracts import (
    TELEGRAM_WEBHOOK_SECRET_HEADER_SUPPORTED,
    TelegramInboundUpdate,
    TelegramIngressConfig,
    TelegramBotScope,
    TelegramWebhookProof,
)

TELEGRAM_WEBHOOK_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
_MAX_UPDATE_BODY_BYTES = 256 * 1024
_FALLBACK_BINDING_REF = "telegram-ingest"

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
        headers=_NO_STORE_HEADERS,
    )


class StaticTelegramTrustedAuthority:
    """Server-side trusted binding authority for one Telegram bot binding.

    Production composition roots supply a resolver backed by the trusted
    secret/binding store; the static form exists for bounded deployments and
    network-free tests. Secret material never leaves this object: projections
    carry only opaque refs.
    """

    def __init__(
        self,
        *,
        binding_ref: str,
        webhook_secret_binding_ref: str,
        webhook_secret: str,
        ingress: TelegramIngressConfig,
        scope: TelegramBotScope,
        identity_map: Mapping[tuple[int, int], tuple[str, str]],
    ) -> None:
        if not isinstance(ingress, TelegramIngressConfig):
            raise ValueError("ingress must be TelegramIngressConfig")
        self.binding_ref = binding_ref
        self.webhook_secret_binding_ref = webhook_secret_binding_ref
        self._webhook_secret = webhook_secret
        self.ingress = ingress
        self.scope = scope
        self._identity_map = dict(identity_map)
        self.replay_guard = InMemoryEventReplayGuard()

    def webhook_secret_bytes(self) -> bytes:
        return self._webhook_secret.encode("utf-8")

    def resolve_inbound_identity(
        self, *, provider_chat_id: int, provider_sender_id: int
    ) -> tuple[str, str] | None:
        return self._identity_map.get((provider_chat_id, provider_sender_id))


async def _read_bounded_update(request: Request) -> dict[str, Any] | None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return None
    raw = await request.body()
    if not raw or len(raw) > _MAX_UPDATE_BODY_BYTES:
        return None
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return decoded if type(decoded) is dict else None


def _extract_message_identity(update: Mapping[str, Any]) -> tuple[int, int, int, str, int] | None:
    """Return (update_id, provider_chat_id, provider_sender_id, text, message_id)."""
    update_id = update.get("update_id")
    if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
        return None
    message = update.get("message")
    if type(message) is not dict:
        return None
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    chat = message.get("chat")
    sender = message.get("from")
    if type(chat) is not dict or type(sender) is not dict:
        return None
    provider_chat_id = chat.get("id")
    provider_sender_id = sender.get("id")
    if isinstance(provider_chat_id, bool) or not isinstance(provider_chat_id, int):
        return None
    if isinstance(provider_sender_id, bool) or not isinstance(provider_sender_id, int):
        return None
    message_id = message.get("message_id")
    if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id < 0:
        return None
    return update_id, provider_chat_id, provider_sender_id, text, message_id


def _build_manual_intake(update: TelegramInboundUpdate) -> dict[str, Any]:
    """Map an accepted Telegram update onto the existing Claw intake path."""
    request = ManualIntakeRequest(
        request_id=f"tgintake-{update.update_id}",
        workspace_id=update.workspace_ref,
        channel=ManualIntakeChannel.TELEGRAM,
        action=ManualIntakeAction.QUOTE_DRAFT,
        raw_content=update.text,
        sender_hint=update.sender_ref,
    )
    result = ManualIntakeRouter().process(request)
    return result.safe_dict()


async def claw_telegram_ingest(request: Request) -> JSONResponse:
    authority: StaticTelegramTrustedAuthority | None = getattr(
        request.app.state, "claw_telegram_authority", None
    )
    path_binding = request.path_params.get("binding_ref", "")
    if authority is None or path_binding != authority.binding_ref:
        return _error(
            503 if authority is None else 403,
            "telegram_ingest_not_configured" if authority is None else "telegram_binding_unknown",
            "Telegram ingest is unavailable for this binding.",
        )

    # 1. Webhook proof: exact secret-header equality at the trusted ingress,
    #    compared in constant time. Fail closed on missing/wrong header.
    presented = request.headers.get(TELEGRAM_WEBHOOK_SECRET_HEADER, "")
    if not TELEGRAM_WEBHOOK_SECRET_HEADER_SUPPORTED or not presented:
        return _error(403, "telegram_webhook_proof_rejected", "Webhook proof missing.")
    expected = authority.webhook_secret_bytes()
    if not hmac.compare_digest(presented.encode("utf-8"), expected):
        return _error(403, "telegram_webhook_proof_rejected", "Webhook proof rejected.")

    update = await _read_bounded_update(request)
    if update is None:
        return _error(400, "telegram_update_invalid", "Telegram update body is invalid.")

    # 2. Only plain text messages of the configured update type are in scope.
    identity = _extract_message_identity(update)
    if identity is None or "message" not in update:
        return JSONResponse(
            {"ok": True, "accepted": False, "reason": "unsupported_update"},
            headers=_NO_STORE_HEADERS,
        )
    update_id, provider_chat_id, provider_sender_id, text, provider_message_id = identity

    now = datetime.now(timezone.utc)
    resolved = authority.resolve_inbound_identity(
        provider_chat_id=provider_chat_id, provider_sender_id=provider_sender_id
    )
    if resolved is None:
        return JSONResponse(
            {"ok": True, "accepted": False, "reason": "unpaired"},
            headers=_NO_STORE_HEADERS,
        )
    chat_ref, sender_ref = resolved

    replay = authority.replay_guard.observe(
        connector_id="telegram",
        binding_ref=authority.binding_ref,
        event_ref=f"telegram-update:{update_id}",
    )
    if replay is not ReplayDisposition.NEW:
        return JSONResponse(
            {"ok": True, "accepted": False, "reason": "duplicate"},
            headers=_NO_STORE_HEADERS,
        )

    # 4. Explicit bounded-text gate before canonical projection (fail-closed).
    if len(text) > 20_000:
        return JSONResponse(
            {"ok": True, "accepted": False, "reason": "text_exceeds_bound"},
            headers=_NO_STORE_HEADERS,
        )

    webhook_proof = TelegramWebhookProof(
        proof_ref=f"telegram-webhook-proof:{update_id}",
        secret_binding_ref=authority.webhook_secret_binding_ref,
        secret_header_verified=True,
        verified_at=now,
    )
    try:
        inbound = TelegramInboundUpdate(
            update_id=update_id,
            binding_ref=authority.binding_ref,
            workspace_ref=authority.scope.workspace_ref,
            bot_ref=authority.scope.bot_ref,
            chat_ref=chat_ref,
            sender_ref=sender_ref,
            update_type="message",
            text=text,
            replay=replay,
            webhook_proof=webhook_proof,
            message_ref=f"telegram-message:{provider_message_id}",
        )
    except ContractError:
        # Poison update (secret-shaped content, oversized after redaction,
        # malformed identity): fail closed without provider detail leakage.
        return JSONResponse(
            {"ok": True, "accepted": False, "reason": "rejected_by_contract"},
            headers=_NO_STORE_HEADERS,
        )

    # 3. Canonical paired-chat authorization + ingress acceptance.
    if not inbound.accepted_by(
        scope=authority.scope, ingress=authority.ingress, privileged=False
    ):
        return JSONResponse(
            {"ok": True, "accepted": False, "reason": "not_authorized"},
            headers=_NO_STORE_HEADERS,
        )

    # 5. Map onto the existing Claw manual intake path (no outbound action).
    intake = _build_manual_intake(inbound)
    return JSONResponse(
        {
            "ok": True,
            "accepted": True,
            "update": {
                "event_ref": inbound.event_ref,
                "update_id": inbound.update_id,
                "chat_ref": inbound.chat_ref,
                "sender_ref": inbound.sender_ref,
                "replay": inbound.replay.value,
                "message_ref": inbound.message_ref,
                "webhook_proof": inbound.webhook_proof.safe_dict(),
            },
            "intake": intake,
        },
        headers=_NO_STORE_HEADERS,
    )
