"""Promoted Telegram Bot API READ capability contract (#2353, parent #2010).

Ports the already-reviewed B54 Telegram contract surface
(``apps/korean-ai-code-agent/src/kagent/telegram_contracts.py``) into canonical
Padiem AI Core as the third shared connector alongside Gmail and Drive. This
module is a projection of reviewed logic, not a new design: the B54 bounds, the
official-Bot-API-only rule, the webhook/getUpdates exclusivity, the
callback-data-is-not-approval rule and the no-autonomous-spam rule all come
from B54, which remains product-local compatibility evidence and is never
mutated here.

Core owns no HTTP, no bot token, no webhook and no provider client. The host
application supplies a trusted :class:`TelegramReadPort`; Core only shapes
bounded, untrusted JSON projections. Unlike the Google connectors, the
Telegram bot token is a raw secret embedded in the provider URL path, so the
port boundary must sanitize every provider exception (Core already drops
exception messages, the cause chain and the implicit context chain).

Fail-closed rules ported from the reviewed B54 contract:

* only the two promoted READ tool ids (and their canonical ids) classify as
  READ; every unknown or future Telegram tool id — including sendMessage,
  sendDocument, editMessageText and answerCallbackQuery, which are NOT
  registered in Core — classifies as ``WRITE_OR_MATERIAL`` or ``UNKNOWN`` and
  never receives a READ grant;
* the official Bot API is the only supported transport: personal MTProto user
  sessions and scraping of arbitrary private chats are unsupported, and the
  READ surface is limited to the bot's own identity and server-side paired
  chats resolved by the trusted port;
* callback query data is never an approval authority; a send capability is
  never minted by this contract;
* the raw bot token never appears in Core types, projections, grants or error
  messages.

This module is deterministic and network-free. It performs zero provider calls
on its own: every provider read goes through the injected trusted port.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import inspect
import json
import re
from typing import Any, Awaitable, Mapping, Protocol

from .connector_registry import ConnectorDescriptor
from .contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from .tool_runtime import MAX_TOOL_OUTPUT_BYTES, ToolHandler, ToolRuntime


class TelegramContractError(ValueError):
    """Safe Telegram projection contract failure (B54 ContractError port)."""


TELEGRAM_CONNECTOR_ID = "connector:telegram:bot@1"

# Core ToolSpec auth-scope tokens. Telegram has no provider OAuth scope string
# here: the bot token is resolved entirely outside Core by the trusted port.
TELEGRAM_READONLY_AUTH_SCOPE = "telegram.readonly"

# Recorded as contract evidence only: no send/write tool is registered in Core,
# so this scope is never requested by this contract.
TELEGRAM_SEND_AUTH_SCOPE = "telegram.send"

TELEGRAM_API_HOST = "api.telegram.org"
TELEGRAM_BASE_URL = "https://api.telegram.org"

# Reviewed B54 bounds (telegram_contracts.py:15-22), ported verbatim.
MAX_TELEGRAM_CHATS = 128
MAX_TELEGRAM_SENDERS_PER_CHAT = 128
MAX_TELEGRAM_MESSAGE_CHARS = 20_000
MAX_TELEGRAM_FILE_BYTES = 10 * 1024 * 1024
MAX_TELEGRAM_FILES_PER_UPDATE = 8
TELEGRAM_PROVIDER_CLOUD_DOWNLOAD_LIMIT_BYTES = 20 * 1024 * 1024
TELEGRAM_PROVIDER_CLOUD_SEND_DOCUMENT_LIMIT_BYTES = 50 * 1024 * 1024
TELEGRAM_CALLBACK_DATA_MAX_BYTES = 64

REQUEST_TIMEOUT_SECONDS = 30

# Core-side output bounds (analogous to the Gmail/Drive promotions).
MAX_PROVIDER_METADATA_BYTES = 128_000
MAX_NAME_CHARS = 512
MAX_BOT_ID_DIGITS = 64

TELEGRAM_GET_BOT_INFO_TOOL_ID = "telegram.get_bot_info"
TELEGRAM_GET_CHAT_INFO_TOOL_ID = "telegram.get_chat_info"

TELEGRAM_READ_TOOL_IDS = (
    TELEGRAM_GET_BOT_INFO_TOOL_ID,
    TELEGRAM_GET_CHAT_INFO_TOOL_ID,
)

TELEGRAM_CANONICAL_TOOL_IDS = (
    "tool:telegram:bot.get_bot_info@1",
    "tool:telegram:bot.get_chat_info@1",
)

# B54 review-state mirrors (telegram_contracts.py:619-629), kept fail-closed.
TELEGRAM_OFFICIAL_BOT_API_REQUIRED = True
TELEGRAM_PERSONAL_MTPROTO_SESSION_SUPPORTED = False
TELEGRAM_WEBHOOK_SECRET_HEADER_SUPPORTED = True
TELEGRAM_WEBHOOK_SECRET_IS_HMAC_SIGNATURE = False
TELEGRAM_WEBHOOK_AND_GETUPDATES_SIMULTANEOUS = False
TELEGRAM_UPDATE_ID_DEDUP_REQUIRED = True
TELEGRAM_CALLBACK_DATA_IS_APPROVAL_AUTHORITY = False
TELEGRAM_CALLBACK_DURABLE_ATOMIC_CONSUME_REQUIRED = True
TELEGRAM_RAW_BOT_TOKEN_IN_CORE = False
TELEGRAM_AUTONOMOUS_SPAM_SUPPORTED = False
TELEGRAM_WRITE_TOOLS_PRESENT = False
TELEGRAM_LIVE_PROVIDER_CALLS = 0
TELEGRAM_PRODUCTION_SEND_AUTHORITY_MINTED = False


class TelegramReadPort(Protocol):
    """Trusted Telegram Bot API HTTP boundary (B54 provider-port role).

    Callers pass only connector binding + actor refs and the exact readonly
    auth-scope requirement. ``path`` is a bare Bot API method path such as
    ``/getMe``; the implementation inserts the bot token segment outside Core
    state, enforces the server-derived paired-chat allowlist for chat reads,
    sanitizes every provider exception so the token-bearing URL never leaks,
    enforces the response byte bound, and returns decoded provider JSON.
    Implementations may be sync or async; Core awaits when needed. Core never
    implements this port.
    """

    def get_json(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        required_scopes: tuple[str, ...],
        base_url: str,
        path: str,
        query: dict[str, str],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> dict[str, Any] | Awaitable[dict[str, Any]]:
        ...


def telegram_read_tool_specs() -> tuple[ToolSpec, ...]:
    """READ-only ToolSpecs for the promoted Telegram surface."""

    return (
        ToolSpec(
            id=TELEGRAM_GET_BOT_INFO_TOOL_ID,
            title="Telegram get bot info",
            description=(
                "Read the connected Telegram bot's own bounded identity: numeric bot id, "
                "username and display name. No chats, messages or credentials are returned."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            auth_scope=(TELEGRAM_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=TELEGRAM_GET_CHAT_INFO_TOOL_ID,
            title="Telegram get chat info",
            description=(
                "Read bounded metadata for one server-side paired chat: chat id, kind and "
                "display title or username. Chats outside the server-derived pairing are "
                "never readable, and message content is never returned."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {
                    "chatId": {"type": "integer", "description": "Telegram chat id to inspect."},
                },
                "required": ["chatId"],
                "additionalProperties": False,
            },
            auth_scope=(TELEGRAM_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
    )


TELEGRAM_DESCRIPTOR = ConnectorDescriptor(
    connector_id=TELEGRAM_CONNECTOR_ID,
    title="Telegram Bot",
    canonical_tool_ids=TELEGRAM_CANONICAL_TOOL_IDS,
    requires_authorization=True,
)


# --- bounded validation helpers (ported from B54 telegram_contracts.py) ---

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_BOT_ID_RE = re.compile(r"^[0-9]{1,64}$")

_CHAT_TYPES = frozenset({"private", "group", "supergroup", "channel"})


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TelegramContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise TelegramContractError(f"{field_name} must be a bounded safe reference")
    return normalized


def _bounded_text(value: Any, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise TelegramContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise TelegramContractError(f"{field_name} must be non-empty")
    if len(normalized) > limit:
        raise TelegramContractError(f"{field_name} exceeds {limit} characters")
    return normalized


def _chat_id_value(value: Any, field_name: str = "chat_id") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TelegramContractError(f"{field_name} must be an integer")
    if not -(2**63) < value < 2**63 or value == 0:
        raise TelegramContractError(f"{field_name} must be a bounded non-zero chat id")
    return value


def _optional_username(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    normalized = _bounded_text(value, field_name, 64).lstrip("@")
    if not _USERNAME_RE.fullmatch(normalized):
        raise TelegramContractError(f"{field_name} must be a bounded Telegram username")
    return normalized


class TelegramCapability(str, Enum):
    """Explicit Telegram capability classes (B54 read + gated outbound write set)."""

    READ = "read"
    SEND_MESSAGE = "send_message"
    SEND_DOCUMENT = "send_document"
    EDIT_MESSAGE = "edit_message"
    ANSWER_CALLBACK = "answer_callback"


_WRITE_CAPABILITIES = (
    TelegramCapability.SEND_MESSAGE,
    TelegramCapability.SEND_DOCUMENT,
    TelegramCapability.EDIT_MESSAGE,
    TelegramCapability.ANSWER_CALLBACK,
)


class TelegramCapabilityClassification(str, Enum):
    """Fail-closed classification result for an unclassified Telegram tool id."""

    READ = "read"
    WRITE_OR_MATERIAL = "write_or_material"
    UNKNOWN = "unknown"


_WRITE_HINT_TOKENS = (
    "send",
    "edit",
    "answer",
    "delete",
    "forward",
    "pin",
    "unpin",
    "leave",
    "kick",
    "ban",
    "unban",
    "restrict",
    "promote",
    "set_",
    "create",
    "approve",
    "refund",
    "webhook",
)


def classify_telegram_tool_id(tool_id: str) -> TelegramCapabilityClassification:
    """Classify a Telegram tool id; everything unregistered fails closed."""

    if not isinstance(tool_id, str) or not tool_id.strip():
        raise TelegramContractError("tool_id must be a non-empty string")
    normalized = tool_id.strip()
    if not _SAFE_ID_RE.fullmatch(normalized):
        raise TelegramContractError("tool_id must be a bounded safe identifier")
    if normalized in TELEGRAM_READ_TOOL_IDS or normalized in TELEGRAM_CANONICAL_TOOL_IDS:
        return TelegramCapabilityClassification.READ
    lowered = normalized.lower()
    if any(token in lowered for token in _WRITE_HINT_TOKENS):
        return TelegramCapabilityClassification.WRITE_OR_MATERIAL
    return TelegramCapabilityClassification.UNKNOWN


def core_auth_scopes_for_capability(capability: TelegramCapability) -> tuple[str, ...]:
    """Bounded Core auth-scope tokens required by a capability."""

    if not isinstance(capability, TelegramCapability):
        raise TelegramContractError("capability must be TelegramCapability")
    if capability is TelegramCapability.READ:
        return (TELEGRAM_READONLY_AUTH_SCOPE,)
    if capability in _WRITE_CAPABILITIES:
        # Recorded as contract evidence only: no write tool is registered in
        # Core, so this scope is never requested by this contract.
        return (TELEGRAM_SEND_AUTH_SCOPE,)
    raise TelegramContractError("unsupported Telegram capability")


def capability_requires_send_approval(capability: TelegramCapability) -> bool:
    """Whether a capability requires durable send-approval semantics.

    READ never requires approval. Every outbound write requires the reviewed
    B54 approval authority, which this contract never mints.
    """

    if not isinstance(capability, TelegramCapability):
        raise TelegramContractError("capability must be TelegramCapability")
    return capability in _WRITE_CAPABILITIES


@dataclass(frozen=True, slots=True)
class TelegramCapabilityGrant:
    """One bounded capability grant fact for a connector binding.

    ``granted_capabilities`` carries only explicit capability values resolved
    server-side from grant references; it is never derived from caller JSON.
    The raw bot token can never appear here — the grant carries capability
    facts only.
    """

    connector_id: str
    binding_ref: str
    granted_capabilities: tuple[TelegramCapability, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.connector_id, str) or not _SAFE_ID_RE.fullmatch(self.connector_id.strip()):
            raise TelegramContractError("connector_id must be a bounded safe identifier")
        if not isinstance(self.binding_ref, str) or not _SAFE_ID_RE.fullmatch(self.binding_ref.strip()):
            raise TelegramContractError("binding_ref must be a bounded safe identifier")
        if not isinstance(self.granted_capabilities, tuple) or any(
            not isinstance(item, TelegramCapability) for item in self.granted_capabilities
        ):
            raise TelegramContractError("granted_capabilities must contain TelegramCapability values")
        if len(self.granted_capabilities) != len(set(self.granted_capabilities)):
            raise TelegramContractError("granted_capabilities must be unique")

    def allows(self, capability: TelegramCapability) -> bool:
        if not isinstance(capability, TelegramCapability):
            raise TelegramContractError("capability must be TelegramCapability")
        return capability in self.granted_capabilities

    def write_authority(self) -> bool:
        """Whether this grant carries any Telegram send/edit authority."""

        return any(self.allows(capability) for capability in _WRITE_CAPABILITIES)

    def safe_dict(self) -> dict[str, object]:
        return {
            "connector_id": self.connector_id,
            "binding_ref": self.binding_ref,
            "granted_capabilities": sorted(item.value for item in self.granted_capabilities),
            "write_authority": self.write_authority(),
            "bot_token_present": False,
            "raw_credentials_present": False,
            "mints_approval_authority": False,
        }


@dataclass(frozen=True, slots=True)
class TelegramBotInfo:
    """Bounded projection of the bot's own identity (getMe)."""

    bot_id: str
    username: str
    first_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.bot_id, str) or not _BOT_ID_RE.fullmatch(self.bot_id):
            raise TelegramContractError("bot_id must be a bounded numeric string")
        if not _USERNAME_RE.fullmatch(self.username):
            raise TelegramContractError("username must be a bounded Telegram username")
        object.__setattr__(self, "first_name", _bounded_text(self.first_name, "first_name", MAX_NAME_CHARS))

    def safe_dict(self) -> dict[str, object]:
        return {
            "bot_id": self.bot_id,
            "username": self.username,
            "first_name": self.first_name,
            "is_bot": True,
            "personal_account": False,
            "bot_token_present": False,
        }


@dataclass(frozen=True, slots=True)
class TelegramChatInfo:
    """Bounded metadata projection for one server-side paired chat (getChat)."""

    chat_id: int
    chat_type: str
    title: str | None = None
    username: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "chat_id", _chat_id_value(self.chat_id))
        if not isinstance(self.chat_type, str) or self.chat_type not in _CHAT_TYPES:
            raise TelegramContractError("chat_type must be a known Telegram chat kind")
        if self.title is not None:
            object.__setattr__(self, "title", _bounded_text(self.title, "title", MAX_NAME_CHARS))
        object.__setattr__(self, "username", _optional_username(self.username, "username"))

    def safe_dict(self) -> dict[str, object]:
        return {
            "chat_id": self.chat_id,
            "chat_type": self.chat_type,
            "title": self.title,
            "username": self.username,
            "message_content_present": False,
            "bot_token_present": False,
        }


def _project_bot_info(result: Mapping[str, Any]) -> TelegramBotInfo:
    if result.get("is_bot") is not True:
        raise TelegramContractError("Telegram provider identity is not a bot.")
    return TelegramBotInfo(
        bot_id=str(_chat_id_value(result.get("id"), "bot id")),
        username=_bounded_text(result.get("username"), "username", 64),
        first_name=_bounded_text(result.get("first_name"), "first_name", MAX_NAME_CHARS),
    )


def _project_chat_info(result: Mapping[str, Any]) -> TelegramChatInfo:
    return TelegramChatInfo(
        chat_id=_chat_id_value(result.get("id")),
        chat_type=_bounded_text(result.get("type"), "chat_type", 32),
        title=result.get("title"),
        username=result.get("username"),
    )


def _bounded_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Bound the final JSON output to Core MAX_TOOL_OUTPUT_BYTES.

    Oversized envelopes are replaced by a visible REVIEW_REQUIRED marker with a
    content digest instead of raising or leaking unbounded provider output.
    """

    encoded = json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) <= MAX_TOOL_OUTPUT_BYTES:
        return envelope
    return {
        "provider": "telegram",
        "operation": envelope.get("operation"),
        "result_status": "REVIEW_REQUIRED",
        "truncated": True,
        "reason": "bounded Telegram projection exceeded the Core tool output bound",
        "result_sha256": hashlib.sha256(encoded).hexdigest(),
        "telegram_content_trusted": False,
        "bot_token_present": False,
    }


async def _port_json(
    port: TelegramReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
    path: str,
    query: dict[str, str],
    max_response_bytes: int,
) -> dict[str, Any]:
    def _call() -> dict[str, Any] | Awaitable[dict[str, Any]]:
        return port.get_json(
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            required_scopes=(TELEGRAM_READONLY_AUTH_SCOPE,),
            base_url=TELEGRAM_BASE_URL,
            path=path,
            query=dict(query),
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            max_response_bytes=max_response_bytes,
        )

    try:
        result = _call()
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        # The trusted port boundary is the only place that may surface
        # diagnostics; Core must not propagate its exception message, the
        # cause chain, or the implicit context chain. For Telegram this is
        # mandatory: the provider URL embeds the raw bot token.
        sanitized = TelegramContractError("The Telegram provider port failed.")
    else:
        if not isinstance(result, dict):
            raise TelegramContractError("The Telegram provider port returned an invalid body.")
        return result

    raise sanitized


def _provider_result(body: Mapping[str, Any]) -> Mapping[str, Any]:
    """Unwrap the Bot API ``ok/result`` envelope without echoing provider text."""

    if body.get("ok") is not True:
        raise TelegramContractError("The Telegram provider returned an error.")
    result = body.get("result")
    if not isinstance(result, dict):
        raise TelegramContractError("The Telegram provider returned an invalid result.")
    return result


def build_telegram_read_handlers(
    port: TelegramReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
    paired_chat_ids: tuple[int, ...] = (),
) -> dict[str, ToolHandler]:
    """Bind the promoted readonly projections to one trusted port instance.

    binding_ref/actor_ref are forwarded only to the trusted port and never
    appear in the returned output or in TelegramContractError messages.
    ``paired_chat_ids`` is a server-derived allowlist re-checked in Core as
    defense in depth; the port remains the pairing authority.
    """

    paired = {_chat_id_value(item) for item in paired_chat_ids}

    async def get_bot_info(arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, Mapping) or arguments:
            raise TelegramContractError("telegram.get_bot_info accepts no arguments.")
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path="/getMe",
            query={},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        bot = _project_bot_info(_provider_result(body))
        return _bounded_envelope(
            {
                "provider": "telegram",
                "operation": TELEGRAM_GET_BOT_INFO_TOOL_ID,
                "result_status": "OK",
                "bot": bot.safe_dict(),
                "telegram_content_trusted": False,
                "bot_token_present": False,
                "mints_approval_authority": False,
                "write_capability_granted": False,
            }
        )

    async def get_chat_info(arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, Mapping):
            raise TelegramContractError("telegram.get_chat_info requires an arguments object.")
        extra = set(arguments) - {"chatId"}
        if extra:
            raise TelegramContractError("telegram.get_chat_info accepts only chatId.")
        chat_id = _chat_id_value(arguments.get("chatId"), "chatId")
        if paired and chat_id not in paired:
            raise TelegramContractError("chat is not server-side paired.")
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path="/getChat",
            query={"chat_id": str(chat_id)},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        chat = _project_chat_info(_provider_result(body))
        if chat.chat_id != chat_id:
            raise TelegramContractError("Telegram provider returned mismatched chat identity.")
        return _bounded_envelope(
            {
                "provider": "telegram",
                "operation": TELEGRAM_GET_CHAT_INFO_TOOL_ID,
                "result_status": "OK",
                "chat": chat.safe_dict(),
                "arbitrary_private_chat_read": False,
                "telegram_content_trusted": False,
                "bot_token_present": False,
                "mints_approval_authority": False,
                "write_capability_granted": False,
            }
        )

    return {
        TELEGRAM_GET_BOT_INFO_TOOL_ID: get_bot_info,
        TELEGRAM_GET_CHAT_INFO_TOOL_ID: get_chat_info,
    }


def register_telegram_read_tools(
    runtime: ToolRuntime,
    port: TelegramReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
    paired_chat_ids: tuple[int, ...] = (),
) -> tuple[str, ...]:
    """Register the readonly Telegram tools on a ToolRuntime and return their ids."""

    handlers = build_telegram_read_handlers(
        port,
        binding_ref=binding_ref,
        actor_ref=actor_ref,
        paired_chat_ids=paired_chat_ids,
    )
    registered: list[str] = []
    for spec in telegram_read_tool_specs():
        runtime.register(spec, handlers[spec.id])
        registered.append(spec.id)
    return tuple(registered)


def telegram_capability_snapshot() -> dict[str, object]:
    """Deterministic, network-free snapshot of the promoted Telegram READ contract."""

    return {
        "contract_version": "padiem-telegram-capability.v1",
        "connector_id": TELEGRAM_CONNECTOR_ID,
        "capabilities": {
            "read": {
                "core_auth_scopes": list(core_auth_scopes_for_capability(TelegramCapability.READ)),
                "requires_send_approval": capability_requires_send_approval(
                    TelegramCapability.READ
                ),
            },
            "write": {
                "core_auth_scopes": list(core_auth_scopes_for_capability(TelegramCapability.SEND_MESSAGE)),
                "requires_send_approval": True,
                "registered": False,
            },
        },
        "read_tool_ids": list(TELEGRAM_READ_TOOL_IDS),
        "canonical_tool_ids": list(TELEGRAM_CANONICAL_TOOL_IDS),
        "registered_write_tools": [],
        "bounds": {
            "max_chats": MAX_TELEGRAM_CHATS,
            "max_senders_per_chat": MAX_TELEGRAM_SENDERS_PER_CHAT,
            "max_message_chars": MAX_TELEGRAM_MESSAGE_CHARS,
            "max_file_bytes": MAX_TELEGRAM_FILE_BYTES,
            "max_files_per_update": MAX_TELEGRAM_FILES_PER_UPDATE,
            "provider_download_limit_bytes": TELEGRAM_PROVIDER_CLOUD_DOWNLOAD_LIMIT_BYTES,
            "provider_send_document_limit_bytes": TELEGRAM_PROVIDER_CLOUD_SEND_DOCUMENT_LIMIT_BYTES,
            "callback_data_max_bytes": TELEGRAM_CALLBACK_DATA_MAX_BYTES,
        },
        "official_bot_api_required": TELEGRAM_OFFICIAL_BOT_API_REQUIRED,
        "personal_mtproto_session_supported": TELEGRAM_PERSONAL_MTPROTO_SESSION_SUPPORTED,
        "webhook_and_getupdates_simultaneous": TELEGRAM_WEBHOOK_AND_GETUPDATES_SIMULTANEOUS,
        "callback_data_is_approval_authority": TELEGRAM_CALLBACK_DATA_IS_APPROVAL_AUTHORITY,
        "write_tools_present": TELEGRAM_WRITE_TOOLS_PRESENT,
        "raw_bot_token_in_core": TELEGRAM_RAW_BOT_TOKEN_IN_CORE,
        "production_send_authority_minted": TELEGRAM_PRODUCTION_SEND_AUTHORITY_MINTED,
        "mints_approval_authority": False,
        "live_provider_calls": TELEGRAM_LIVE_PROVIDER_CALLS,
        "production_activation": False,
    }


__all__ = [
    "MAX_PROVIDER_METADATA_BYTES",
    "MAX_TELEGRAM_CHATS",
    "MAX_TELEGRAM_FILE_BYTES",
    "MAX_TELEGRAM_FILES_PER_UPDATE",
    "MAX_TELEGRAM_MESSAGE_CHARS",
    "MAX_TELEGRAM_SENDERS_PER_CHAT",
    "TELEGRAM_API_HOST",
    "TELEGRAM_AUTONOMOUS_SPAM_SUPPORTED",
    "TELEGRAM_BASE_URL",
    "TELEGRAM_CALLBACK_DATA_IS_APPROVAL_AUTHORITY",
    "TELEGRAM_CALLBACK_DATA_MAX_BYTES",
    "TELEGRAM_CALLBACK_DURABLE_ATOMIC_CONSUME_REQUIRED",
    "TELEGRAM_CANONICAL_TOOL_IDS",
    "TELEGRAM_CONNECTOR_ID",
    "TELEGRAM_DESCRIPTOR",
    "TELEGRAM_GET_BOT_INFO_TOOL_ID",
    "TELEGRAM_GET_CHAT_INFO_TOOL_ID",
    "TELEGRAM_LIVE_PROVIDER_CALLS",
    "TELEGRAM_OFFICIAL_BOT_API_REQUIRED",
    "TELEGRAM_PERSONAL_MTPROTO_SESSION_SUPPORTED",
    "TELEGRAM_PRODUCTION_SEND_AUTHORITY_MINTED",
    "TELEGRAM_PROVIDER_CLOUD_DOWNLOAD_LIMIT_BYTES",
    "TELEGRAM_PROVIDER_CLOUD_SEND_DOCUMENT_LIMIT_BYTES",
    "TELEGRAM_RAW_BOT_TOKEN_IN_CORE",
    "TELEGRAM_READONLY_AUTH_SCOPE",
    "TELEGRAM_READ_TOOL_IDS",
    "TELEGRAM_SEND_AUTH_SCOPE",
    "TELEGRAM_UPDATE_ID_DEDUP_REQUIRED",
    "TELEGRAM_WEBHOOK_AND_GETUPDATES_SIMULTANEOUS",
    "TELEGRAM_WEBHOOK_SECRET_HEADER_SUPPORTED",
    "TELEGRAM_WEBHOOK_SECRET_IS_HMAC_SIGNATURE",
    "TELEGRAM_WRITE_TOOLS_PRESENT",
    "TelegramBotInfo",
    "TelegramCapability",
    "TelegramCapabilityClassification",
    "TelegramCapabilityGrant",
    "TelegramChatInfo",
    "TelegramContractError",
    "TelegramReadPort",
    "build_telegram_read_handlers",
    "capability_requires_send_approval",
    "classify_telegram_tool_id",
    "core_auth_scopes_for_capability",
    "register_telegram_read_tools",
    "telegram_capability_snapshot",
    "telegram_read_tool_specs",
]
