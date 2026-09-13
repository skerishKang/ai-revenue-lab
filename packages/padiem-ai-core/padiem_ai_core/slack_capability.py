"""Promoted Slack Web API READ capability contract (#2356, parent #2010).

Ports the already-reviewed B54 Slack contract surface
(``apps/korean-ai-code-agent/src/kagent/slack_contracts.py``) into canonical
Padiem AI Core as the fourth shared connector alongside Gmail, Drive and
Telegram. This module is a projection of reviewed logic, not a new design: the
B54 bounds, the workspace/team/app/channel scope rule, the explicit-private-
channel subset rule and the no-autonomous-write rule all come from B54, which
remains product-local compatibility evidence and is never mutated here.

Core owns no HTTP, no Slack token, no Events ingress and no provider client.
The host application supplies a trusted :class:`SlackReadPort`; Core only
shapes bounded, untrusted JSON projections. Slack Events ingestion, request
signature verification, replay/event-id handling, outbound writes and OAuth
installation are explicitly out of scope for this contract: no write tool is
registered, and the P01 approval/evidence authority for Slack outbound
actions is never minted here.

Fail-closed rules ported from the reviewed B54 contract:

* only the six promoted READ tool ids (and their canonical ids) classify as
  READ; every unknown or future Slack tool id — including chat.postMessage,
  conversations.replies send-side, conversations.mark and files.upload, which
  are NOT registered in Core — classifies as ``WRITE_OR_MATERIAL`` or
  ``UNKNOWN`` and never receives a READ grant;
* the official Slack Web API (``slack.com``) is the only supported transport:
  user-token impersonation and whole-workspace dumps are unsupported, and the
  READ surface is limited to the server-derived workspace/team/app/channel
  scope resolved outside Core by the trusted port;
* private channel access is never implicit: a private channel is readable only
  when it is explicitly listed in the server-derived private subset;
* the raw Slack bot token never appears in Core types, projections, grants or
  error messages.

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


class SlackContractError(ValueError):
    """Safe Slack projection contract failure (B54 ContractError port)."""


SLACK_CONNECTOR_ID = "connector:slack:workspace@1"

# Core ToolSpec auth-scope tokens. Slack has no provider OAuth scope string
# here: the bot token is resolved entirely outside Core by the trusted port.
SLACK_READONLY_AUTH_SCOPE = "slack.readonly"

# Recorded as contract evidence only: no send/write tool is registered in
# Core, so this scope is never requested by this contract.
SLACK_SEND_AUTH_SCOPE = "slack.send"

SLACK_API_HOST = "slack.com"
SLACK_BASE_URL = "https://slack.com"

# Reviewed B54 bounds (slack_contracts.py:19-23), ported verbatim.
MAX_SLACK_CHANNELS = 128
MAX_SLACK_MESSAGE_CHARS = 20_000
MAX_SLACK_FILE_BYTES = 10 * 1024 * 1024
MAX_SLACK_FILES_PER_ACTION = 8
SLACK_SIGNATURE_MAX_AGE_SECONDS = 300

REQUEST_TIMEOUT_SECONDS = 30

# Core-side output bounds (analogous to the Gmail/Drive/Telegram promotions).
MAX_PROVIDER_METADATA_BYTES = 128_000
MAX_NAME_CHARS = 512
MAX_SLACK_PROJECTION_ITEMS = 100

SLACK_GET_WORKSPACE_INFO_TOOL_ID = "slack.get_workspace_info"
SLACK_LIST_CHANNELS_TOOL_ID = "slack.list_channels"
SLACK_GET_CHANNEL_HISTORY_TOOL_ID = "slack.get_channel_history"
SLACK_GET_THREAD_REPLIES_TOOL_ID = "slack.get_thread_replies"
SLACK_GET_USER_INFO_TOOL_ID = "slack.get_user_info"
SLACK_GET_FILE_INFO_TOOL_ID = "slack.get_file_info"

SLACK_READ_TOOL_IDS = (
    SLACK_GET_WORKSPACE_INFO_TOOL_ID,
    SLACK_LIST_CHANNELS_TOOL_ID,
    SLACK_GET_CHANNEL_HISTORY_TOOL_ID,
    SLACK_GET_THREAD_REPLIES_TOOL_ID,
    SLACK_GET_USER_INFO_TOOL_ID,
    SLACK_GET_FILE_INFO_TOOL_ID,
)

SLACK_CANONICAL_TOOL_IDS = (
    "tool:slack:workspace.get_info@1",
    "tool:slack:channel.list@1",
    "tool:slack:channel.get_history@1",
    "tool:slack:thread.get_replies@1",
    "tool:slack:user.get_info@1",
    "tool:slack:file.get_info@1",
)

# B54 review-state mirrors (slack_contracts.py:541-552), kept fail-closed.
SLACK_REGISTERED_APP_REQUIRED = True
SLACK_CONFIDENTIAL_USER_OAUTH = True
SLACK_STATIC_READ_TOOL_ALLOWLIST_CONFIGURED = False
SLACK_LIVE_TOOLS_LIST_REQUIRED_FOR_READ_CLASSIFICATION = True
SLACK_UNKNOWN_MCP_TOOL_FAILS_CLOSED = True
SLACK_RAW_SIGNING_SECRET_IN_CORE = False
SLACK_RAW_OAUTH_TOKEN_IN_CORE = False
SLACK_AUTONOMOUS_BULK_MESSAGE_SUPPORTED = False
SLACK_USER_IMPERSONATION_SUPPORTED = False
SLACK_REAL_OAUTH_CONFIGURED = False
SLACK_REAL_MUTATION_CONFIGURED = False
SLACK_WRITE_TOOLS_PRESENT = False
SLACK_LIVE_PROVIDER_CALLS = 0
SLACK_PRODUCTION_SEND_AUTHORITY_MINTED = False


class SlackReadPort(Protocol):
    """Trusted Slack Web API HTTP boundary (B54 provider-port role).

    Callers pass only connector binding + actor refs and the exact readonly
    auth-scope requirement. ``path`` is a bare Web API method path such as
    ``/api/auth.test``; the implementation injects the bot token as a
    transport-only bearer credential outside Core state, enforces the
    server-derived workspace/team/app/channel scope (including the explicit
    private-channel subset), sanitizes every provider exception, enforces the
    response byte bound, and returns decoded provider JSON. Implementations
    may be sync or async; Core awaits when needed. Core never implements this
    port.
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


def slack_read_tool_specs() -> tuple[ToolSpec, ...]:
    """READ-only ToolSpecs for the promoted Slack surface."""

    return (
        ToolSpec(
            id=SLACK_GET_WORKSPACE_INFO_TOOL_ID,
            title="Slack get workspace info",
            description=(
                "Read the connected Slack workspace's bounded identity: team id, "
                "team name and the bot's own user id. No channels, messages or "
                "credentials are returned."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            auth_scope=(SLACK_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=SLACK_LIST_CHANNELS_TOOL_ID,
            title="Slack list channels",
            description=(
                "List bounded metadata for the server-derived allowed channels "
                "only: channel id, name and privacy flags. Private channels "
                "outside the explicit server-derived private subset are never "
                "listed, and message content is never returned."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            auth_scope=(SLACK_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=SLACK_GET_CHANNEL_HISTORY_TOOL_ID,
            title="Slack get channel history",
            description=(
                "Read a bounded page of message metadata for one allowed "
                "channel. Channels outside the server-derived allowlist are "
                "never readable; content is untrusted projection data only."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {
                    "channelId": {"type": "string", "description": "Slack channel id to read."},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Bounded page size (1..100).",
                    },
                },
                "required": ["channelId"],
                "additionalProperties": False,
            },
            auth_scope=(SLACK_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=SLACK_GET_THREAD_REPLIES_TOOL_ID,
            title="Slack get thread replies",
            description=(
                "Read a bounded page of reply metadata for one thread inside an "
                "allowed channel. Channels outside the server-derived allowlist "
                "are never readable."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {
                    "channelId": {"type": "string", "description": "Slack channel id to read."},
                    "threadTs": {
                        "type": "string",
                        "description": "Thread root message timestamp.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Bounded page size (1..100).",
                    },
                },
                "required": ["channelId", "threadTs"],
                "additionalProperties": False,
            },
            auth_scope=(SLACK_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=SLACK_GET_USER_INFO_TOOL_ID,
            title="Slack get user info",
            description=(
                "Read bounded metadata for one selected workspace member: user "
                "id, display name and bot flag. No profile links, email or "
                "token material are returned."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {
                    "userId": {"type": "string", "description": "Slack user id to inspect."},
                },
                "required": ["userId"],
                "additionalProperties": False,
            },
            auth_scope=(SLACK_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=SLACK_GET_FILE_INFO_TOOL_ID,
            title="Slack get file info",
            description=(
                "Read bounded metadata for one shared file reference: file id, "
                "name, mime type and size within the connector quarantine "
                "bound. Raw bytes and signed download URLs are never returned."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {
                    "fileId": {"type": "string", "description": "Slack file id to inspect."},
                },
                "required": ["fileId"],
                "additionalProperties": False,
            },
            auth_scope=(SLACK_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
    )


SLACK_DESCRIPTOR = ConnectorDescriptor(
    connector_id=SLACK_CONNECTOR_ID,
    title="Slack",
    canonical_tool_ids=SLACK_CANONICAL_TOOL_IDS,
    requires_authorization=True,
)


# --- bounded validation helpers (ported from B54 slack_contracts.py) ---

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CHANNEL_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{5,24}$")
_USER_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{5,24}$")
_FILE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{5,24}$")
_TS_RE = re.compile(r"^[0-9]+\.[0-9]{6}$")


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise SlackContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise SlackContractError(f"{field_name} must be a bounded safe reference")
    return normalized


def _bounded_text(value: Any, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise SlackContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if len(normalized) > limit:
        raise SlackContractError(f"{field_name} exceeds {limit} characters")
    return normalized


def _provider_id(value: Any, field_name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str):
        raise SlackContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not pattern.fullmatch(normalized):
        raise SlackContractError(f"{field_name} must be a bounded Slack identifier")
    return normalized


def _channel_id_value(value: Any, field_name: str = "channel_id") -> str:
    return _provider_id(value, field_name, _CHANNEL_ID_RE)


def _boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise SlackContractError(f"{field_name} must be boolean")
    return value


class SlackCapability(str, Enum):
    """Explicit Slack capability classes (B54 read + gated outbound write set)."""

    READ = "read"
    POST_MESSAGE = "post_message"
    REPLY_THREAD = "reply_thread"
    UPDATE_MESSAGE = "update_message"
    UPLOAD_FILE = "upload_file"


_WRITE_CAPABILITIES = (
    SlackCapability.POST_MESSAGE,
    SlackCapability.REPLY_THREAD,
    SlackCapability.UPDATE_MESSAGE,
    SlackCapability.UPLOAD_FILE,
)


class SlackCapabilityClassification(str, Enum):
    """Fail-closed classification result for an unclassified Slack tool id."""

    READ = "read"
    WRITE_OR_MATERIAL = "write_or_material"
    UNKNOWN = "unknown"


_WRITE_HINT_TOKENS = (
    "post",
    "send",
    "publish",
    "update",
    "edit",
    "delete",
    "upload",
    "invite",
    "kick",
    "leave",
    "join",
    "archive",
    "unarchive",
    "pin",
    "unpin",
    "set",
    "create",
    "approve",
    "refund",
    "webhook",
    "mark",
)


def classify_slack_tool_id(tool_id: str) -> SlackCapabilityClassification:
    """Classify a Slack tool id; everything unregistered fails closed."""

    if not isinstance(tool_id, str) or not tool_id.strip():
        raise SlackContractError("tool_id must be a non-empty string")
    normalized = tool_id.strip()
    if not _SAFE_ID_RE.fullmatch(normalized):
        raise SlackContractError("tool_id must be a bounded safe identifier")
    if normalized in SLACK_READ_TOOL_IDS or normalized in SLACK_CANONICAL_TOOL_IDS:
        return SlackCapabilityClassification.READ
    lowered = normalized.lower()
    if any(token in lowered for token in _WRITE_HINT_TOKENS):
        return SlackCapabilityClassification.WRITE_OR_MATERIAL
    return SlackCapabilityClassification.UNKNOWN


def core_auth_scopes_for_capability(capability: SlackCapability) -> tuple[str, ...]:
    """Bounded Core auth-scope tokens required by a capability."""

    if not isinstance(capability, SlackCapability):
        raise SlackContractError("capability must be SlackCapability")
    if capability is SlackCapability.READ:
        return (SLACK_READONLY_AUTH_SCOPE,)
    if capability in _WRITE_CAPABILITIES:
        # Recorded as contract evidence only: no write tool is registered in
        # Core, so this scope is never requested by this contract.
        return (SLACK_SEND_AUTH_SCOPE,)
    raise SlackContractError("unsupported Slack capability")


def capability_requires_send_approval(capability: SlackCapability) -> bool:
    """Whether a capability requires durable send-approval semantics.

    READ never requires approval. Every outbound write requires the reviewed
    B54/P01 approval authority, which this contract never mints.
    """

    if not isinstance(capability, SlackCapability):
        raise SlackContractError("capability must be SlackCapability")
    return capability in _WRITE_CAPABILITIES


@dataclass(frozen=True, slots=True)
class SlackWorkspaceScope:
    """Bounded server-derived workspace/team/app/channel scope (B54 port).

    ``allowed_channel_ids`` is a non-empty explicit allowlist (1..128) and
    ``explicitly_private_channel_ids`` must be a subset of it: a workspace
    connection never implies all-channel access and private channel access is
    never implicit. This value is resolved server-side only; caller or model
    payloads can never mint or widen it.
    """

    binding_ref: str
    workspace_ref: str
    slack_team_id: str
    slack_app_id: str
    allowed_channel_ids: tuple[str, ...]
    explicitly_private_channel_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("binding_ref", "workspace_ref", "slack_team_id", "slack_app_id"):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        if not self.allowed_channel_ids or len(self.allowed_channel_ids) > MAX_SLACK_CHANNELS:
            raise SlackContractError("Slack scope requires 1..128 explicit channels")
        channels = tuple(_channel_id_value(value) for value in self.allowed_channel_ids)
        if len(channels) != len(set(channels)):
            raise SlackContractError("Slack channel ids must be unique")
        private_channels = tuple(
            _channel_id_value(value, "private_channel_id")
            for value in self.explicitly_private_channel_ids
        )
        if len(private_channels) != len(set(private_channels)):
            raise SlackContractError("private Slack channel ids must be unique")
        if not set(private_channels).issubset(set(channels)):
            raise SlackContractError(
                "private Slack channels must also be present in the channel allowlist"
            )
        object.__setattr__(self, "allowed_channel_ids", channels)
        object.__setattr__(self, "explicitly_private_channel_ids", private_channels)

    def authorizes(self, *, channel_id: str, private_channel: bool = False) -> bool:
        channel = _channel_id_value(channel_id)
        if channel not in self.allowed_channel_ids:
            return False
        if private_channel and channel not in self.explicitly_private_channel_ids:
            return False
        return True

    def safe_dict(self) -> dict[str, object]:
        return {
            "contract_version": "padiem-slack-workspace-scope.v1",
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "slack_team_id": self.slack_team_id,
            "slack_app_id": self.slack_app_id,
            "allowed_channel_ids": list(self.allowed_channel_ids),
            "explicitly_private_channel_ids": list(self.explicitly_private_channel_ids),
            "workspace_connection_implies_all_channels": False,
            "private_channel_access_implicit": False,
            "bot_token_present": False,
        }


@dataclass(frozen=True, slots=True)
class SlackCapabilityGrant:
    """One bounded capability grant fact for a connector binding.

    ``granted_capabilities`` carries only explicit capability values resolved
    server-side from grant references; it is never derived from caller JSON.
    The raw bot token can never appear here — the grant carries capability
    facts only.
    """

    connector_id: str
    binding_ref: str
    granted_capabilities: tuple[SlackCapability, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.connector_id, str) or not _SAFE_ID_RE.fullmatch(
            self.connector_id.strip()
        ):
            raise SlackContractError("connector_id must be a bounded safe identifier")
        if not isinstance(self.binding_ref, str) or not _SAFE_ID_RE.fullmatch(
            self.binding_ref.strip()
        ):
            raise SlackContractError("binding_ref must be a bounded safe identifier")
        if not isinstance(self.granted_capabilities, tuple) or any(
            not isinstance(item, SlackCapability) for item in self.granted_capabilities
        ):
            raise SlackContractError("granted_capabilities must contain SlackCapability values")
        if len(self.granted_capabilities) != len(set(self.granted_capabilities)):
            raise SlackContractError("granted_capabilities must be unique")

    def allows(self, capability: SlackCapability) -> bool:
        if not isinstance(capability, SlackCapability):
            raise SlackContractError("capability must be SlackCapability")
        return capability in self.granted_capabilities

    def write_authority(self) -> bool:
        """Whether this grant carries any Slack send/update authority."""

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
class SlackWorkspaceInfo:
    """Bounded projection of the workspace's own identity (auth.test)."""

    team_id: str
    team_name: str
    bot_user_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "team_id", _safe_ref(self.team_id, "team_id"))
        object.__setattr__(self, "team_name", _bounded_text(self.team_name, "team_name", MAX_NAME_CHARS))
        object.__setattr__(self, "bot_user_id", _provider_id(self.bot_user_id, "bot_user_id", _USER_ID_RE))

    def safe_dict(self) -> dict[str, object]:
        return {
            "team_id": self.team_id,
            "team_name": self.team_name,
            "bot_user_id": self.bot_user_id,
            "user_impersonation": False,
            "bot_token_present": False,
        }


@dataclass(frozen=True, slots=True)
class SlackChannelInfo:
    """Bounded metadata projection for one server-derived allowed channel."""

    channel_id: str
    name: str
    is_private: bool = False
    is_archived: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel_id", _channel_id_value(self.channel_id))
        object.__setattr__(self, "name", _bounded_text(self.name, "name", MAX_NAME_CHARS))
        object.__setattr__(self, "is_private", _boolean(self.is_private, "is_private"))
        object.__setattr__(self, "is_archived", _boolean(self.is_archived, "is_archived"))

    def safe_dict(self) -> dict[str, object]:
        return {
            "channel_id": self.channel_id,
            "name": self.name,
            "is_private": self.is_private,
            "is_archived": self.is_archived,
            "message_content_present": False,
            "bot_token_present": False,
        }


@dataclass(frozen=True, slots=True)
class SlackFileManifest:
    """Bounded file metadata projection (B54 SlackFileManifest port, READ slice)."""

    file_ref: str
    filename: str
    mime_type: str
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_ref", _provider_id(self.file_ref, "file_ref", _FILE_ID_RE))
        object.__setattr__(self, "filename", _bounded_text(self.filename, "filename", MAX_NAME_CHARS))
        object.__setattr__(
            self, "mime_type", _bounded_text(self.mime_type, "mime_type", 255).lower() or "application/octet-stream"
        )
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise SlackContractError("Slack file size must be a non-negative integer")
        if self.size_bytes > MAX_SLACK_FILE_BYTES:
            raise SlackContractError("Slack file exceeds connector quarantine bound")

    def safe_dict(self) -> dict[str, object]:
        return {
            "file_ref": self.file_ref,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "model_usable": False,
            "raw_bytes_present": False,
            "download_url_present": False,
            "bot_token_present": False,
        }


@dataclass(frozen=True, slots=True)
class SlackMessageInfo:
    """Bounded message metadata projection (B54 SlackMessageProjection port)."""

    channel_id: str
    message_ts: str
    user_ref: str | None
    text: str
    thread_ts: str | None = None
    files: tuple[SlackFileManifest, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel_id", _channel_id_value(self.channel_id))
        object.__setattr__(self, "message_ts", _provider_id(self.message_ts, "message_ts", _TS_RE))
        object.__setattr__(
            self,
            "user_ref",
            None if self.user_ref is None else _provider_id(self.user_ref, "user_ref", _USER_ID_RE),
        )
        object.__setattr__(
            self, "text", _bounded_text(self.text, "Slack message text", MAX_SLACK_MESSAGE_CHARS)
        )
        object.__setattr__(
            self,
            "thread_ts",
            None if self.thread_ts is None else _provider_id(self.thread_ts, "thread_ts", _TS_RE),
        )
        if len(self.files) > MAX_SLACK_FILES_PER_ACTION:
            raise SlackContractError("Slack message file count exceeds bound")
        if any(not isinstance(item, SlackFileManifest) for item in self.files):
            raise SlackContractError("Slack message files must be SlackFileManifest values")

    def safe_dict(self) -> dict[str, object]:
        return {
            "channel_id": self.channel_id,
            "message_ts": self.message_ts,
            "thread_ts": self.thread_ts,
            "user_ref": self.user_ref,
            "text": self.text,
            "files": [item.safe_dict() for item in self.files],
            "message_content_trusted": False,
            "mention_grants_tool_authority": False,
            "bot_token_present": False,
        }


@dataclass(frozen=True, slots=True)
class SlackUserInfo:
    """Bounded projection for one selected workspace member (users.info)."""

    user_id: str
    display_name: str
    is_bot: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _provider_id(self.user_id, "user_id", _USER_ID_RE))
        object.__setattr__(
            self, "display_name", _bounded_text(self.display_name, "display_name", MAX_NAME_CHARS)
        )
        object.__setattr__(self, "is_bot", _boolean(self.is_bot, "is_bot"))

    def safe_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "is_bot": self.is_bot,
            "email_present": False,
            "profile_url_present": False,
            "bot_token_present": False,
        }


def _project_workspace_info(body: Mapping[str, Any]) -> SlackWorkspaceInfo:
    return SlackWorkspaceInfo(
        team_id=_safe_ref(str(body.get("team_id", "")), "team_id"),
        team_name=_bounded_text(body.get("team"), "team_name", MAX_NAME_CHARS),
        bot_user_id=_provider_id(body.get("user_id"), "bot_user_id", _USER_ID_RE),
    )


def _project_channel(raw: Any) -> SlackChannelInfo:
    if not isinstance(raw, Mapping):
        raise SlackContractError("Slack channel entry must be an object")
    return SlackChannelInfo(
        channel_id=_channel_id_value(raw.get("id")),
        name=_bounded_text(raw.get("name", ""), "name", MAX_NAME_CHARS) or "unnamed",
        is_private=_boolean(raw.get("is_private", False), "is_private"),
        is_archived=_boolean(raw.get("is_archived", False), "is_archived"),
    )


def _project_file_manifest(raw: Any) -> SlackFileManifest:
    if not isinstance(raw, Mapping):
        raise SlackContractError("Slack file entry must be an object")
    return SlackFileManifest(
        file_ref=_provider_id(raw.get("id"), "file_ref", _FILE_ID_RE),
        filename=_bounded_text(raw.get("name", ""), "filename", MAX_NAME_CHARS) or "unnamed",
        mime_type=_bounded_text(raw.get("mimetype", ""), "mime_type", 255) or "application/octet-stream",
        size_bytes=raw.get("size", 0),
    )


def _project_message(raw: Any, channel_id: str) -> SlackMessageInfo:
    if not isinstance(raw, Mapping):
        raise SlackContractError("Slack message entry must be an object")
    raw_files = raw.get("files") or ()
    if not isinstance(raw_files, (list, tuple)):
        raise SlackContractError("Slack message files must be a list")
    if len(raw_files) > MAX_SLACK_FILES_PER_ACTION:
        raise SlackContractError("Slack message file count exceeds bound")
    thread_ts = raw.get("thread_ts")
    return SlackMessageInfo(
        channel_id=channel_id,
        message_ts=_provider_id(raw.get("ts"), "message_ts", _TS_RE),
        user_ref=raw.get("user"),
        text=_bounded_text(raw.get("text", ""), "Slack message text", MAX_SLACK_MESSAGE_CHARS),
        thread_ts=thread_ts,
        files=tuple(_project_file_manifest(item) for item in raw_files),
    )


def _project_user(raw: Any) -> SlackUserInfo:
    if not isinstance(raw, Mapping):
        raise SlackContractError("Slack user entry must be an object")
    return SlackUserInfo(
        user_id=_provider_id(raw.get("id"), "user_id", _USER_ID_RE),
        display_name=_bounded_text(raw.get("real_name") or raw.get("name") or "", "display_name", MAX_NAME_CHARS)
        or "unnamed",
        is_bot=_boolean(raw.get("is_bot", False), "is_bot"),
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
        "provider": "slack",
        "operation": envelope.get("operation"),
        "result_status": "REVIEW_REQUIRED",
        "truncated": True,
        "reason": "bounded Slack projection exceeded the Core tool output bound",
        "result_sha256": hashlib.sha256(encoded).hexdigest(),
        "slack_content_trusted": False,
        "bot_token_present": False,
    }


async def _port_json(
    port: SlackReadPort,
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
            required_scopes=(SLACK_READONLY_AUTH_SCOPE,),
            base_url=SLACK_BASE_URL,
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
        # cause chain, or the implicit context chain. The raw bot token must
        # never reach Core-visible errors.
        sanitized = SlackContractError("The Slack provider port failed.")
    else:
        if not isinstance(result, dict):
            raise SlackContractError("The Slack provider port returned an invalid body.")
        return result

    raise sanitized


def _provider_ok(body: Mapping[str, Any]) -> None:
    """Check the flat Slack ``ok`` envelope without echoing provider text."""

    if body.get("ok") is not True:
        raise SlackContractError("The Slack provider returned an error.")


def _bounded_limit(arguments: Mapping[str, Any]) -> int:
    limit = arguments.get("limit", MAX_SLACK_PROJECTION_ITEMS)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_SLACK_PROJECTION_ITEMS:
        raise SlackContractError("limit must be an integer between 1 and 100")
    return limit


def build_slack_read_handlers(
    port: SlackReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
    allowed_channel_ids: tuple[str, ...] = (),
    explicitly_private_channel_ids: tuple[str, ...] = (),
) -> dict[str, ToolHandler]:
    """Bind the promoted readonly projections to one trusted port instance.

    binding_ref/actor_ref are forwarded only to the trusted port and never
    appear in the returned output or in SlackContractError messages.
    ``allowed_channel_ids``/``explicitly_private_channel_ids`` are a
    server-derived allowlist re-checked in Core as defense in depth; the port
    remains the scope authority.
    """

    allowed = {_channel_id_value(item) for item in allowed_channel_ids}
    private_explicit = {_channel_id_value(item) for item in explicitly_private_channel_ids}
    if allowed and not private_explicit.issubset(allowed):
        # Core defense-in-depth mirrors the B54 subset rule; with no Core-side
        # allowlist the port remains the sole scope authority.
        raise SlackContractError(
            "private Slack channels must also be present in the channel allowlist"
        )

    def _require_channel(arguments: Mapping[str, Any]) -> str:
        channel_id = _channel_id_value(arguments.get("channelId"), "channelId")
        if allowed and channel_id not in allowed:
            raise SlackContractError("channel is not server-derived allowed.")
        return channel_id

    async def get_workspace_info(arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, Mapping) or arguments:
            raise SlackContractError("slack.get_workspace_info accepts no arguments.")
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path="/api/auth.test",
            query={},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        _provider_ok(body)
        workspace = _project_workspace_info(body)
        return _bounded_envelope(
            {
                "provider": "slack",
                "operation": SLACK_GET_WORKSPACE_INFO_TOOL_ID,
                "result_status": "OK",
                "workspace": workspace.safe_dict(),
                "slack_content_trusted": False,
                "bot_token_present": False,
                "mints_approval_authority": False,
                "write_capability_granted": False,
            }
        )

    async def list_channels(arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, Mapping) or arguments:
            raise SlackContractError("slack.list_channels accepts no arguments.")
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path="/api/conversations.list",
            query={"types": "public_channel,private_channel", "exclude_archived": "true", "limit": "200"},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        _provider_ok(body)
        raw_channels = body.get("channels")
        if not isinstance(raw_channels, (list, tuple)):
            raise SlackContractError("The Slack provider returned an invalid channel list.")
        channels: list[SlackChannelInfo] = []
        for raw in raw_channels[: MAX_SLACK_CHANNELS + 1]:
            channel = _project_channel(raw)
            if channel.is_private and channel.channel_id not in private_explicit:
                continue
            if allowed and channel.channel_id not in allowed:
                continue
            channels.append(channel)
        if len(channels) > MAX_SLACK_CHANNELS:
            raise SlackContractError("Slack channel list exceeds the bounded channel count")
        return _bounded_envelope(
            {
                "provider": "slack",
                "operation": SLACK_LIST_CHANNELS_TOOL_ID,
                "result_status": "OK",
                "channels": [channel.safe_dict() for channel in channels],
                "channel_count": len(channels),
                "whole_workspace_dump": False,
                "private_channel_access_implicit": False,
                "slack_content_trusted": False,
                "bot_token_present": False,
                "mints_approval_authority": False,
                "write_capability_granted": False,
            }
        )

    async def get_channel_history(arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, Mapping):
            raise SlackContractError("slack.get_channel_history requires an arguments object.")
        extra = set(arguments) - {"channelId", "limit"}
        if extra:
            raise SlackContractError("slack.get_channel_history accepts only channelId and limit.")
        channel_id = _require_channel(arguments)
        limit = _bounded_limit(arguments)
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path="/api/conversations.history",
            query={"channel": channel_id, "limit": str(limit)},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        _provider_ok(body)
        raw_messages = body.get("messages")
        if not isinstance(raw_messages, (list, tuple)):
            raise SlackContractError("The Slack provider returned an invalid message list.")
        messages = [_project_message(raw, channel_id) for raw in raw_messages[:limit]]
        return _bounded_envelope(
            {
                "provider": "slack",
                "operation": SLACK_GET_CHANNEL_HISTORY_TOOL_ID,
                "result_status": "OK",
                "channel_id": channel_id,
                "messages": [message.safe_dict() for message in messages],
                "message_count": len(messages),
                "whole_workspace_dump": False,
                "slack_content_trusted": False,
                "bot_token_present": False,
                "mints_approval_authority": False,
                "write_capability_granted": False,
            }
        )

    async def get_thread_replies(arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, Mapping):
            raise SlackContractError("slack.get_thread_replies requires an arguments object.")
        extra = set(arguments) - {"channelId", "threadTs", "limit"}
        if extra:
            raise SlackContractError(
                "slack.get_thread_replies accepts only channelId, threadTs and limit."
            )
        channel_id = _require_channel(arguments)
        thread_ts = _provider_id(arguments.get("threadTs"), "threadTs", _TS_RE)
        limit = _bounded_limit(arguments)
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path="/api/conversations.replies",
            query={"channel": channel_id, "ts": thread_ts, "limit": str(limit)},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        _provider_ok(body)
        raw_messages = body.get("messages")
        if not isinstance(raw_messages, (list, tuple)):
            raise SlackContractError("The Slack provider returned an invalid message list.")
        messages = [_project_message(raw, channel_id) for raw in raw_messages[:limit]]
        return _bounded_envelope(
            {
                "provider": "slack",
                "operation": SLACK_GET_THREAD_REPLIES_TOOL_ID,
                "result_status": "OK",
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "replies": [message.safe_dict() for message in messages],
                "reply_count": len(messages),
                "whole_workspace_dump": False,
                "slack_content_trusted": False,
                "bot_token_present": False,
                "mints_approval_authority": False,
                "write_capability_granted": False,
            }
        )

    async def get_user_info(arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, Mapping):
            raise SlackContractError("slack.get_user_info requires an arguments object.")
        extra = set(arguments) - {"userId"}
        if extra:
            raise SlackContractError("slack.get_user_info accepts only userId.")
        user_id = _provider_id(arguments.get("userId"), "userId", _USER_ID_RE)
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path="/api/users.info",
            query={"user": user_id},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        _provider_ok(body)
        user = _project_user(body.get("user"))
        if user.user_id != user_id:
            raise SlackContractError("Slack provider returned mismatched user identity.")
        return _bounded_envelope(
            {
                "provider": "slack",
                "operation": SLACK_GET_USER_INFO_TOOL_ID,
                "result_status": "OK",
                "user": user.safe_dict(),
                "slack_content_trusted": False,
                "bot_token_present": False,
                "mints_approval_authority": False,
                "write_capability_granted": False,
            }
        )

    async def get_file_info(arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, Mapping):
            raise SlackContractError("slack.get_file_info requires an arguments object.")
        extra = set(arguments) - {"fileId"}
        if extra:
            raise SlackContractError("slack.get_file_info accepts only fileId.")
        file_id = _provider_id(arguments.get("fileId"), "fileId", _FILE_ID_RE)
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path="/api/files.info",
            query={"file": file_id},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        _provider_ok(body)
        raw_file = body.get("file")
        if not isinstance(raw_file, Mapping):
            raise SlackContractError("The Slack provider returned an invalid file object.")
        manifest = _project_file_manifest(raw_file)
        if manifest.file_ref != file_id:
            raise SlackContractError("Slack provider returned mismatched file identity.")
        return _bounded_envelope(
            {
                "provider": "slack",
                "operation": SLACK_GET_FILE_INFO_TOOL_ID,
                "result_status": "OK",
                "file": manifest.safe_dict(),
                "slack_content_trusted": False,
                "bot_token_present": False,
                "mints_approval_authority": False,
                "write_capability_granted": False,
            }
        )

    return {
        SLACK_GET_WORKSPACE_INFO_TOOL_ID: get_workspace_info,
        SLACK_LIST_CHANNELS_TOOL_ID: list_channels,
        SLACK_GET_CHANNEL_HISTORY_TOOL_ID: get_channel_history,
        SLACK_GET_THREAD_REPLIES_TOOL_ID: get_thread_replies,
        SLACK_GET_USER_INFO_TOOL_ID: get_user_info,
        SLACK_GET_FILE_INFO_TOOL_ID: get_file_info,
    }


def register_slack_read_tools(
    runtime: ToolRuntime,
    port: SlackReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
    allowed_channel_ids: tuple[str, ...] = (),
    explicitly_private_channel_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Register the readonly Slack tools on a ToolRuntime and return their ids."""

    handlers = build_slack_read_handlers(
        port,
        binding_ref=binding_ref,
        actor_ref=actor_ref,
        allowed_channel_ids=allowed_channel_ids,
        explicitly_private_channel_ids=explicitly_private_channel_ids,
    )
    registered: list[str] = []
    for spec in slack_read_tool_specs():
        runtime.register(spec, handlers[spec.id])
        registered.append(spec.id)
    return tuple(registered)


def slack_capability_snapshot() -> dict[str, object]:
    """Deterministic, network-free snapshot of the promoted Slack READ contract."""

    return {
        "contract_version": "padiem-slack-capability.v1",
        "connector_id": SLACK_CONNECTOR_ID,
        "capabilities": {
            "read": {
                "core_auth_scopes": list(core_auth_scopes_for_capability(SlackCapability.READ)),
                "requires_send_approval": capability_requires_send_approval(
                    SlackCapability.READ
                ),
            },
            "write": {
                "core_auth_scopes": list(core_auth_scopes_for_capability(SlackCapability.POST_MESSAGE)),
                "requires_send_approval": True,
                "registered": False,
            },
        },
        "read_tool_ids": list(SLACK_READ_TOOL_IDS),
        "canonical_tool_ids": list(SLACK_CANONICAL_TOOL_IDS),
        "registered_write_tools": [],
        "bounds": {
            "max_channels": MAX_SLACK_CHANNELS,
            "max_message_chars": MAX_SLACK_MESSAGE_CHARS,
            "max_file_bytes": MAX_SLACK_FILE_BYTES,
            "max_files_per_action": MAX_SLACK_FILES_PER_ACTION,
            "signature_max_age_seconds": SLACK_SIGNATURE_MAX_AGE_SECONDS,
            "max_projection_items": MAX_SLACK_PROJECTION_ITEMS,
        },
        "registered_app_required": SLACK_REGISTERED_APP_REQUIRED,
        "events_ingress_in_scope": False,
        "private_channel_access_implicit": False,
        "whole_workspace_dump_supported": False,
        "user_impersonation_supported": SLACK_USER_IMPERSONATION_SUPPORTED,
        "write_tools_present": SLACK_WRITE_TOOLS_PRESENT,
        "raw_bot_token_in_core": SLACK_RAW_OAUTH_TOKEN_IN_CORE,
        "production_send_authority_minted": SLACK_PRODUCTION_SEND_AUTHORITY_MINTED,
        "mints_approval_authority": False,
        "live_provider_calls": SLACK_LIVE_PROVIDER_CALLS,
        "production_activation": False,
    }


__all__ = [
    "MAX_PROVIDER_METADATA_BYTES",
    "MAX_SLACK_CHANNELS",
    "MAX_SLACK_FILE_BYTES",
    "MAX_SLACK_FILES_PER_ACTION",
    "MAX_SLACK_MESSAGE_CHARS",
    "MAX_SLACK_PROJECTION_ITEMS",
    "SLACK_API_HOST",
    "SLACK_AUTONOMOUS_BULK_MESSAGE_SUPPORTED",
    "SLACK_BASE_URL",
    "SLACK_CANONICAL_TOOL_IDS",
    "SLACK_CONNECTOR_ID",
    "SLACK_DESCRIPTOR",
    "SLACK_GET_CHANNEL_HISTORY_TOOL_ID",
    "SLACK_GET_FILE_INFO_TOOL_ID",
    "SLACK_GET_THREAD_REPLIES_TOOL_ID",
    "SLACK_GET_USER_INFO_TOOL_ID",
    "SLACK_GET_WORKSPACE_INFO_TOOL_ID",
    "SLACK_LIST_CHANNELS_TOOL_ID",
    "SLACK_LIVE_PROVIDER_CALLS",
    "SLACK_LIVE_TOOLS_LIST_REQUIRED_FOR_READ_CLASSIFICATION",
    "SLACK_PRODUCTION_SEND_AUTHORITY_MINTED",
    "SLACK_RAW_OAUTH_TOKEN_IN_CORE",
    "SLACK_RAW_SIGNING_SECRET_IN_CORE",
    "SLACK_READONLY_AUTH_SCOPE",
    "SLACK_READ_TOOL_IDS",
    "SLACK_REAL_MUTATION_CONFIGURED",
    "SLACK_REAL_OAUTH_CONFIGURED",
    "SLACK_REGISTERED_APP_REQUIRED",
    "SLACK_SEND_AUTH_SCOPE",
    "SLACK_SIGNATURE_MAX_AGE_SECONDS",
    "SLACK_STATIC_READ_TOOL_ALLOWLIST_CONFIGURED",
    "SLACK_UNKNOWN_MCP_TOOL_FAILS_CLOSED",
    "SLACK_USER_IMPERSONATION_SUPPORTED",
    "SLACK_WRITE_TOOLS_PRESENT",
    "SlackCapability",
    "SlackCapabilityClassification",
    "SlackCapabilityGrant",
    "SlackChannelInfo",
    "SlackContractError",
    "SlackFileManifest",
    "SlackMessageInfo",
    "SlackReadPort",
    "SlackUserInfo",
    "SlackWorkspaceInfo",
    "SlackWorkspaceScope",
    "build_slack_read_handlers",
    "capability_requires_send_approval",
    "classify_slack_tool_id",
    "core_auth_scopes_for_capability",
    "register_slack_read_tools",
    "slack_capability_snapshot",
    "slack_read_tool_specs",
]
