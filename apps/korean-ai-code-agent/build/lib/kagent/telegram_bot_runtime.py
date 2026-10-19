from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
import json
import re
import ssl
from typing import Any, Protocol
from urllib.parse import quote

from .connector_trust import InMemoryEventReplayGuard, ReplayDisposition
from .contracts import ContractError
from .telegram_contracts import (
    TelegramBotScope,
    TelegramInboundUpdate,
    TelegramIngressConfig,
    TelegramIngressMode,
    TelegramOutboundApproval,
    TelegramOutboundCapability,
    TelegramOutboundMaterial,
    TelegramOutboundPreflightDecision,
    telegram_outbound_preflight,
)
from .connector_trust import ConnectorWriteIntent


TELEGRAM_API_HOST = "api.telegram.org"
MAX_GET_UPDATES_BATCH = 25
MAX_BOT_API_RESPONSE_BYTES = 512_000
MAX_RESULT_MESSAGE_CHARS = 20_000
_TOKEN_RE = re.compile(r"^[A-Za-z0-9:_-]{20,256}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _provider_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{field_name} must be an exact integer")
    return value


def _bounded_text(value: Any, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
    if len(value) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    return value


def _bot_token(value: bytes) -> str:
    if not isinstance(value, bytes) or not value:
        raise ContractError("trusted Telegram token resolver returned invalid material")
    try:
        decoded = value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ContractError("trusted Telegram bot token must be bounded ASCII") from exc
    if not _TOKEN_RE.fullmatch(decoded):
        raise ContractError("trusted Telegram bot token shape is invalid")
    return decoded


@dataclass(frozen=True, slots=True)
class TelegramResolvedProviderIdentity:
    chat_ref: str
    sender_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "chat_ref", _safe_ref(self.chat_ref, "chat_ref"))
        object.__setattr__(self, "sender_ref", _safe_ref(self.sender_ref, "sender_ref"))


class TelegramTrustedBindingPort(Protocol):
    """Trusted Telegram account/chat authority outside task/model state."""

    def resolve_bot_token(self, *, binding_ref: str, bot_ref: str) -> bytes:
        ...

    def resolve_inbound_identity(
        self,
        *,
        binding_ref: str,
        bot_ref: str,
        provider_chat_id: int,
        provider_sender_id: int,
    ) -> TelegramResolvedProviderIdentity | None:
        ...

    def provider_chat_id(self, *, binding_ref: str, bot_ref: str, chat_ref: str) -> int:
        ...


class TelegramBotApiRequestPort(Protocol):
    def call(
        self,
        *,
        token: bytes,
        method: str,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        ...


class StdlibTelegramBotApiRequestPort:
    """Official Telegram Bot API HTTPS source using the OS/default trust store."""

    def call(
        self,
        *,
        token: bytes,
        method: str,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        token_text = _bot_token(token)
        method = _safe_ref(method, "telegram_method")
        if type(payload) is not dict:
            raise ContractError("Telegram Bot API payload must be a plain mapping")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 60:
            raise ContractError("Telegram Bot API timeout must be between 1 and 60 seconds")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 256_000:
            raise ContractError("Telegram Bot API request exceeds source bound")

        connection: http.client.HTTPSConnection | None = None
        try:
            context = ssl.create_default_context()
            connection = http.client.HTTPSConnection(
                TELEGRAM_API_HOST,
                port=443,
                timeout=timeout_seconds,
                context=context,
            )
            token_path = quote(token_text, safe=":_-")
            connection.request(
                "POST",
                f"/bot{token_path}/{method}",
                body=encoded,
                headers={
                    "accept": "application/json",
                    "cache-control": "no-store",
                    "content-type": "application/json",
                    "user-agent": "padiem-claw-telegram/0.1",
                },
            )
            response = connection.getresponse()
            body = response.read(MAX_BOT_API_RESPONSE_BYTES + 1)
            if len(body) > MAX_BOT_API_RESPONSE_BYTES:
                raise ContractError("Telegram Bot API response exceeds source bound")
            if 300 <= response.status < 400:
                raise ContractError("Telegram Bot API redirect is refused")
            if response.status != 200:
                raise ContractError(f"Telegram Bot API returned HTTP status {response.status}")
            content_type = (response.getheader("content-type") or "").lower()
            if not content_type.startswith("application/json"):
                raise ContractError("Telegram Bot API response must be application/json")
            try:
                decoded = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ContractError("Telegram Bot API response is invalid JSON") from exc
            if type(decoded) is not dict:
                raise ContractError("Telegram Bot API response must be a JSON object")
            return decoded
        except ContractError:
            raise
        except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as exc:
            raise ContractError("Telegram Bot API is unavailable") from exc
        finally:
            if connection is not None:
                connection.close()


@dataclass(frozen=True, slots=True)
class TelegramProviderMessageReceipt:
    binding_ref: str
    workspace_ref: str
    bot_ref: str
    chat_ref: str
    message_ref: str
    material_fingerprint: str
    delivered_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("binding_ref", "workspace_ref", "bot_ref", "chat_ref", "message_ref"):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        if not isinstance(self.material_fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", self.material_fingerprint):
            raise ContractError("material_fingerprint must be lowercase SHA-256")
        object.__setattr__(self, "delivered_at", _aware(self.delivered_at, "delivered_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-telegram-provider-message-receipt.v1",
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "bot_ref": self.bot_ref,
            "chat_ref": self.chat_ref,
            "message_ref": self.message_ref,
            "material_fingerprint": self.material_fingerprint,
            "delivered_at": self.delivered_at.isoformat().replace("+00:00", "Z"),
            "raw_bot_token": False,
            "raw_provider_chat_id": False,
            "raw_provider_response": False,
        }


class TelegramBusinessMvpRuntime:
    """Bounded natural-language intake + result surface for the business MVP."""

    def __init__(
        self,
        *,
        trusted_binding: TelegramTrustedBindingPort,
        api: TelegramBotApiRequestPort | None = None,
        replay_guard: InMemoryEventReplayGuard | None = None,
    ) -> None:
        for name in ("resolve_bot_token", "resolve_inbound_identity", "provider_chat_id"):
            if not callable(getattr(trusted_binding, name, None)):
                raise ContractError("trusted_binding does not implement Telegram binding authority")
        self._binding = trusted_binding
        self._api = api or StdlibTelegramBotApiRequestPort()
        if not callable(getattr(self._api, "call", None)):
            raise ContractError("api must implement TelegramBotApiRequestPort")
        self._replay = replay_guard or InMemoryEventReplayGuard()

    @staticmethod
    def _provider_result(response: dict[str, Any]) -> Any:
        if type(response) is not dict or type(response.get("ok")) is not bool:
            raise ContractError("Telegram Bot API envelope is invalid")
        if response["ok"] is not True:
            code = response.get("error_code")
            if isinstance(code, bool) or not isinstance(code, int):
                code = 0
            raise ContractError(f"Telegram Bot API rejected request with code {code}")
        if "result" not in response:
            raise ContractError("Telegram Bot API success response is missing result")
        return response["result"]

    def poll_text_updates(
        self,
        *,
        scope: TelegramBotScope,
        ingress: TelegramIngressConfig,
        after_update_id: int,
        now: datetime,
    ) -> tuple[TelegramInboundUpdate, ...]:
        if not isinstance(scope, TelegramBotScope):
            raise ContractError("scope must be TelegramBotScope")
        if not isinstance(ingress, TelegramIngressConfig) or ingress.mode is not TelegramIngressMode.GET_UPDATES:
            raise ContractError("business MVP polling requires reviewed getUpdates ingress config")
        if isinstance(after_update_id, bool) or not isinstance(after_update_id, int) or after_update_id < -1:
            raise ContractError("after_update_id must be -1 or a non-negative integer")
        now = _aware(now, "now")
        token = self._binding.resolve_bot_token(binding_ref=scope.binding_ref, bot_ref=scope.bot_ref)
        response = self._api.call(
            token=token,
            method="getUpdates",
            payload={
                "offset": after_update_id + 1,
                "limit": MAX_GET_UPDATES_BATCH,
                "timeout": 0,
                "allowed_updates": list(ingress.allowed_update_types),
            },
            timeout_seconds=30,
        )
        result = self._provider_result(response)
        if type(result) is not list or len(result) > MAX_GET_UPDATES_BATCH:
            raise ContractError("Telegram getUpdates result must be a bounded list")

        projected: list[TelegramInboundUpdate] = []
        seen_batch: set[int] = set()
        for raw_update in result:
            if type(raw_update) is not dict:
                raise ContractError("Telegram update must be an object")
            update_id = _provider_int(raw_update.get("update_id"), "update_id")
            if update_id < 0 or update_id in seen_batch:
                raise ContractError("Telegram update_id must be unique and non-negative")
            seen_batch.add(update_id)
            if update_id <= after_update_id:
                continue
            message = raw_update.get("message")
            if type(message) is not dict:
                continue
            text = message.get("text")
            if not isinstance(text, str):
                continue
            chat = message.get("chat")
            sender = message.get("from")
            if type(chat) is not dict or type(sender) is not dict:
                raise ContractError("Telegram text message is missing chat/sender identity")
            provider_chat_id = _provider_int(chat.get("id"), "provider_chat_id")
            provider_sender_id = _provider_int(sender.get("id"), "provider_sender_id")
            identity = self._binding.resolve_inbound_identity(
                binding_ref=scope.binding_ref,
                bot_ref=scope.bot_ref,
                provider_chat_id=provider_chat_id,
                provider_sender_id=provider_sender_id,
            )
            if identity is None:
                continue
            if not isinstance(identity, TelegramResolvedProviderIdentity):
                raise ContractError("trusted Telegram identity resolver returned invalid projection")
            if not scope.authorizes_inbound(
                binding_ref=scope.binding_ref,
                workspace_ref=scope.workspace_ref,
                bot_ref=scope.bot_ref,
                chat_ref=identity.chat_ref,
                sender_ref=identity.sender_ref,
                privileged=False,
            ):
                continue
            message_id = _provider_int(message.get("message_id"), "message_id")
            replay = self._replay.observe(
                connector_id="telegram",
                binding_ref=scope.binding_ref,
                event_ref=f"telegram-update:{update_id}",
            )
            projected.append(
                TelegramInboundUpdate(
                    update_id=update_id,
                    binding_ref=scope.binding_ref,
                    workspace_ref=scope.workspace_ref,
                    bot_ref=scope.bot_ref,
                    chat_ref=identity.chat_ref,
                    sender_ref=identity.sender_ref,
                    update_type="message",
                    text=_bounded_text(text, "Telegram text", MAX_RESULT_MESSAGE_CHARS),
                    replay=replay,
                    message_ref=f"telegram-message:{message_id}",
                )
            )
        return tuple(projected)

    def send_approved_result_message(
        self,
        *,
        scope: TelegramBotScope,
        material: TelegramOutboundMaterial,
        approval: TelegramOutboundApproval,
        intent: ConnectorWriteIntent,
        actor_ref: str,
        text: str,
        now: datetime,
    ) -> TelegramProviderMessageReceipt:
        if not isinstance(scope, TelegramBotScope):
            raise ContractError("scope must be TelegramBotScope")
        if material.capability is not TelegramOutboundCapability.SEND_MESSAGE:
            raise ContractError("business MVP result surface currently supports send_message only")
        text = _bounded_text(text, "Telegram result text", MAX_RESULT_MESSAGE_CHARS)
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != material.text_sha256:
            raise ContractError("Telegram result text changed after material approval")
        decision = telegram_outbound_preflight(
            scope=scope,
            material=material,
            approval=approval,
            intent=intent,
            actor_ref=actor_ref,
        )
        if decision is not TelegramOutboundPreflightDecision.ALLOW:
            raise ContractError(f"Telegram outbound preflight rejected result: {decision.value}")
        now = _aware(now, "now")
        provider_chat_id = self._binding.provider_chat_id(
            binding_ref=scope.binding_ref,
            bot_ref=scope.bot_ref,
            chat_ref=material.chat_ref,
        )
        provider_chat_id = _provider_int(provider_chat_id, "provider_chat_id")
        token = self._binding.resolve_bot_token(binding_ref=scope.binding_ref, bot_ref=scope.bot_ref)
        response = self._api.call(
            token=token,
            method="sendMessage",
            payload={"chat_id": provider_chat_id, "text": text},
            timeout_seconds=30,
        )
        result = self._provider_result(response)
        if type(result) is not dict:
            raise ContractError("Telegram sendMessage result must be an object")
        provider_message_id = _provider_int(result.get("message_id"), "message_id")
        return TelegramProviderMessageReceipt(
            binding_ref=scope.binding_ref,
            workspace_ref=scope.workspace_ref,
            bot_ref=scope.bot_ref,
            chat_ref=material.chat_ref,
            message_ref=f"telegram-message:{provider_message_id}",
            material_fingerprint=material.material_fingerprint,
            delivered_at=now,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-telegram-business-mvp-runtime.v1",
            "official_bot_api": True,
            "natural_language_text_intake": True,
            "paired_chat_required": True,
            "telegram_identity_alone_is_authority": False,
            "outbound_preflight_required": True,
            "raw_bot_token_in_state": False,
            "personal_account_scraping": False,
            "live_bot_configured": False,
        }


OFFICIAL_TELEGRAM_BOT_API_RUNTIME_SOURCE = True
TELEGRAM_PERSONAL_ACCOUNT_SCRAPING = False
TELEGRAM_PAIRED_CHAT_REQUIRED = True
TELEGRAM_RAW_BOT_TOKEN_IN_TASK = False
TELEGRAM_RESULT_SEND_REQUIRES_PREFLIGHT = True
REAL_TELEGRAM_BOT_TOKEN_CONFIGURED = False
LIVE_TELEGRAM_BOT_VERIFIED = False
PRODUCTION_READY = False
