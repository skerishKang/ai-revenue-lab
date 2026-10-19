from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .connector_trust import (
    ConnectorInboundEvent,
    ConnectorWriteIntent,
    ConnectorWriteReceipt,
)
from .contracts import ContractError
from .security import redact_secrets

MAX_SLACK_CHANNELS = 128
MAX_SLACK_MESSAGE_CHARS = 20_000
MAX_SLACK_FILE_BYTES = 10 * 1024 * 1024
MAX_SLACK_FILES_PER_ACTION = 8
SLACK_SIGNATURE_MAX_AGE_SECONDS = 300
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    if redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must not contain credential material")
    return normalized


def _optional_ref(value: str | None, field_name: str) -> str | None:
    return None if value is None else _safe_ref(value, field_name)


def _bounded_text(value: str, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
    normalized = redact_secrets(value.strip())
    if len(normalized) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    return normalized


def _fingerprint(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip().lower()):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value.strip().lower()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class SlackWorkspaceScope:
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
            raise ContractError("Slack scope requires 1..128 explicit channels")
        channels = tuple(_safe_ref(value, "channel_id") for value in self.allowed_channel_ids)
        if len(channels) != len(set(channels)):
            raise ContractError("Slack channel ids must be unique")
        private_channels = tuple(
            _safe_ref(value, "private_channel_id") for value in self.explicitly_private_channel_ids
        )
        if len(private_channels) != len(set(private_channels)):
            raise ContractError("private Slack channel ids must be unique")
        if not set(private_channels).issubset(set(channels)):
            raise ContractError("private Slack channels must also be present in the channel allowlist")
        object.__setattr__(self, "allowed_channel_ids", channels)
        object.__setattr__(self, "explicitly_private_channel_ids", private_channels)

    def authorizes(
        self,
        *,
        binding_ref: str,
        workspace_ref: str,
        slack_team_id: str,
        slack_app_id: str,
        channel_id: str,
        private_channel: bool = False,
    ) -> bool:
        channel = _safe_ref(channel_id, "channel_id")
        if private_channel and channel not in self.explicitly_private_channel_ids:
            return False
        return (
            _safe_ref(binding_ref, "binding_ref") == self.binding_ref
            and _safe_ref(workspace_ref, "workspace_ref") == self.workspace_ref
            and _safe_ref(slack_team_id, "slack_team_id") == self.slack_team_id
            and _safe_ref(slack_app_id, "slack_app_id") == self.slack_app_id
            and channel in self.allowed_channel_ids
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-slack-workspace-scope.v1",
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "slack_team_id": self.slack_team_id,
            "slack_app_id": self.slack_app_id,
            "allowed_channel_ids": list(self.allowed_channel_ids),
            "explicitly_private_channel_ids": list(self.explicitly_private_channel_ids),
            "workspace_connection_implies_all_channels": False,
            "private_channel_access_implicit": False,
        }


class SlackFileQuarantineState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class SlackFileManifest:
    file_ref: str
    channel_id: str
    filename: str
    mime_type: str
    size_bytes: int
    quarantine_state: SlackFileQuarantineState = SlackFileQuarantineState.PENDING
    sha256: str | None = None
    quarantine_evidence_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_ref", _safe_ref(self.file_ref, "file_ref"))
        object.__setattr__(self, "channel_id", _safe_ref(self.channel_id, "channel_id"))
        object.__setattr__(self, "filename", _bounded_text(self.filename, "filename", 512))
        object.__setattr__(self, "mime_type", _bounded_text(self.mime_type, "mime_type", 255).lower())
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ContractError("Slack file size must be a non-negative integer")
        if self.size_bytes > MAX_SLACK_FILE_BYTES:
            raise ContractError("Slack file exceeds connector quarantine bound")
        if not isinstance(self.quarantine_state, SlackFileQuarantineState):
            try:
                object.__setattr__(
                    self, "quarantine_state", SlackFileQuarantineState(self.quarantine_state)
                )
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Slack file quarantine state") from exc
        if self.sha256 is not None:
            object.__setattr__(self, "sha256", _fingerprint(self.sha256, "sha256"))
        object.__setattr__(
            self,
            "quarantine_evidence_ref",
            _optional_ref(self.quarantine_evidence_ref, "quarantine_evidence_ref"),
        )
        if self.quarantine_state is SlackFileQuarantineState.ACCEPTED:
            if self.sha256 is None or self.quarantine_evidence_ref is None:
                raise ContractError("accepted Slack file requires SHA-256 and quarantine evidence")
        elif self.quarantine_evidence_ref is not None:
            raise ContractError("non-accepted Slack file cannot carry accepted quarantine evidence")

    def model_usable(self) -> bool:
        return (
            self.quarantine_state is SlackFileQuarantineState.ACCEPTED
            and self.sha256 is not None
            and self.quarantine_evidence_ref is not None
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "file_ref": self.file_ref,
            "channel_id": self.channel_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "quarantine_state": self.quarantine_state.value,
            "sha256": self.sha256,
            "quarantine_evidence_ref": self.quarantine_evidence_ref,
            "model_usable": self.model_usable(),
            "raw_bytes_present": False,
        }


@dataclass(frozen=True, slots=True)
class SlackMessageProjection:
    workspace_ref: str
    channel_id: str
    message_ts: str
    user_ref: str
    text: str
    thread_ts: str | None = None
    files: tuple[SlackFileManifest, ...] = ()
    private_channel: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_ref", _safe_ref(self.workspace_ref, "workspace_ref"))
        object.__setattr__(self, "channel_id", _safe_ref(self.channel_id, "channel_id"))
        object.__setattr__(self, "message_ts", _safe_ref(self.message_ts, "message_ts"))
        object.__setattr__(self, "user_ref", _safe_ref(self.user_ref, "user_ref"))
        object.__setattr__(self, "text", _bounded_text(self.text, "Slack message text", MAX_SLACK_MESSAGE_CHARS))
        object.__setattr__(self, "thread_ts", _optional_ref(self.thread_ts, "thread_ts"))
        if len(self.files) > MAX_SLACK_FILES_PER_ACTION:
            raise ContractError("Slack message file count exceeds bound")
        if any(not isinstance(item, SlackFileManifest) for item in self.files):
            raise ContractError("Slack message files must be SlackFileManifest values")
        if any(item.channel_id != self.channel_id for item in self.files):
            raise ContractError("Slack file manifest channel must match message channel")
        if not isinstance(self.private_channel, bool):
            raise ContractError("private_channel must be boolean")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "workspace_ref": self.workspace_ref,
            "channel_id": self.channel_id,
            "message_ts": self.message_ts,
            "thread_ts": self.thread_ts,
            "user_ref": self.user_ref,
            "text": self.text,
            "files": [item.safe_dict() for item in self.files],
            "private_channel": self.private_channel,
            "message_content_trusted": False,
            "mention_grants_tool_authority": False,
            "whole_workspace_dump": False,
        }


@dataclass(frozen=True, slots=True)
class SlackInboundEventProjection:
    connector_event: ConnectorInboundEvent
    slack_team_id: str
    slack_app_id: str
    event_type: str
    channel_id: str | None = None
    private_channel: bool = False
    retry_num: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.connector_event, ConnectorInboundEvent):
            raise ContractError("connector_event must be ConnectorInboundEvent")
        if self.connector_event.connector_id != "slack":
            raise ContractError("Slack ingress requires slack connector event")
        if not self.connector_event.signature_required:
            raise ContractError("Slack HTTP ingress requires signature verification")
        if self.connector_event.signature_max_age_seconds > SLACK_SIGNATURE_MAX_AGE_SECONDS:
            raise ContractError("Slack signature replay window cannot exceed five minutes")
        object.__setattr__(self, "slack_team_id", _safe_ref(self.slack_team_id, "slack_team_id"))
        object.__setattr__(self, "slack_app_id", _safe_ref(self.slack_app_id, "slack_app_id"))
        object.__setattr__(self, "event_type", _safe_ref(self.event_type, "event_type"))
        object.__setattr__(self, "channel_id", _optional_ref(self.channel_id, "channel_id"))
        if not isinstance(self.private_channel, bool):
            raise ContractError("private_channel must be boolean")
        if isinstance(self.retry_num, bool) or not isinstance(self.retry_num, int) or not 0 <= self.retry_num <= 3:
            raise ContractError("Slack retry_num must be between 0 and 3")

    def accepted_by(self, scope: SlackWorkspaceScope) -> bool:
        if not isinstance(scope, SlackWorkspaceScope):
            raise ContractError("scope must be SlackWorkspaceScope")
        if not self.connector_event.accepted():
            return False
        if self.connector_event.binding_ref != scope.binding_ref:
            return False
        if self.connector_event.workspace_ref != scope.workspace_ref:
            return False
        if self.slack_team_id != scope.slack_team_id or self.slack_app_id != scope.slack_app_id:
            return False
        if self.channel_id is None:
            return True
        return scope.authorizes(
            binding_ref=self.connector_event.binding_ref,
            workspace_ref=self.connector_event.workspace_ref,
            slack_team_id=self.slack_team_id,
            slack_app_id=self.slack_app_id,
            channel_id=self.channel_id,
            private_channel=self.private_channel,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "connector_event": self.connector_event.safe_dict(),
            "slack_team_id": self.slack_team_id,
            "slack_app_id": self.slack_app_id,
            "event_type": self.event_type,
            "channel_id": self.channel_id,
            "private_channel": self.private_channel,
            "retry_num": self.retry_num,
            "event_id_dedupe_required": True,
            "event_content_trusted": False,
            "mention_grants_tool_authority": False,
        }


class SlackOutboundCapability(str, Enum):
    POST_MESSAGE = "slack.post_message"
    REPLY_THREAD = "slack.reply_thread"
    UPDATE_MESSAGE = "slack.update_message"
    UPLOAD_FILE = "slack.upload_file"


@dataclass(frozen=True, slots=True)
class SlackApprovedFile:
    file_ref: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    quarantine_evidence_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_ref", _safe_ref(self.file_ref, "file_ref"))
        object.__setattr__(self, "filename", _bounded_text(self.filename, "filename", 512))
        object.__setattr__(self, "mime_type", _bounded_text(self.mime_type, "mime_type", 255).lower())
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or not 0 <= self.size_bytes <= MAX_SLACK_FILE_BYTES:
            raise ContractError("approved Slack file size exceeds bound")
        object.__setattr__(self, "sha256", _fingerprint(self.sha256, "sha256"))
        object.__setattr__(
            self,
            "quarantine_evidence_ref",
            _safe_ref(self.quarantine_evidence_ref, "quarantine_evidence_ref"),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "file_ref": self.file_ref,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "quarantine_evidence_ref": self.quarantine_evidence_ref,
        }


@dataclass(frozen=True, slots=True)
class SlackOutboundMaterial:
    binding_ref: str
    workspace_ref: str
    slack_team_id: str
    slack_app_id: str
    capability: SlackOutboundCapability
    channel_id: str
    text_sha256: str
    thread_ts: str | None = None
    message_ts: str | None = None
    files: tuple[SlackApprovedFile, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("binding_ref", "workspace_ref", "slack_team_id", "slack_app_id", "channel_id"):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        if not isinstance(self.capability, SlackOutboundCapability):
            try:
                object.__setattr__(self, "capability", SlackOutboundCapability(self.capability))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Slack outbound capability") from exc
        object.__setattr__(self, "text_sha256", _fingerprint(self.text_sha256, "text_sha256"))
        object.__setattr__(self, "thread_ts", _optional_ref(self.thread_ts, "thread_ts"))
        object.__setattr__(self, "message_ts", _optional_ref(self.message_ts, "message_ts"))
        if len(self.files) > MAX_SLACK_FILES_PER_ACTION or any(
            not isinstance(item, SlackApprovedFile) for item in self.files
        ):
            raise ContractError("Slack outbound files exceed bounded approved contract")
        if self.capability is SlackOutboundCapability.POST_MESSAGE:
            if self.thread_ts is not None or self.message_ts is not None or self.files:
                raise ContractError("post_message cannot carry thread/message/file mutation identity")
        elif self.capability is SlackOutboundCapability.REPLY_THREAD:
            if self.thread_ts is None or self.message_ts is not None or self.files:
                raise ContractError("reply_thread requires exact thread and no update/file identity")
        elif self.capability is SlackOutboundCapability.UPDATE_MESSAGE:
            if self.message_ts is None or self.files:
                raise ContractError("update_message requires exact message and no file upload")
        elif self.capability is SlackOutboundCapability.UPLOAD_FILE:
            if not self.files or self.message_ts is not None:
                raise ContractError("upload_file requires approved files and no message update identity")

    @property
    def target_ref(self) -> str:
        prefix = f"slack:{self.workspace_ref}:channel:{self.channel_id}"
        if self.capability is SlackOutboundCapability.POST_MESSAGE:
            return f"{prefix}:new-message"
        if self.capability is SlackOutboundCapability.REPLY_THREAD:
            return f"{prefix}:thread:{self.thread_ts}:reply"
        if self.capability is SlackOutboundCapability.UPDATE_MESSAGE:
            return f"{prefix}:message:{self.message_ts}"
        return f"{prefix}:upload"

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "slack_team_id": self.slack_team_id,
            "slack_app_id": self.slack_app_id,
            "capability": self.capability.value,
            "channel_id": self.channel_id,
            "text_sha256": self.text_sha256,
            "thread_ts": self.thread_ts,
            "message_ts": self.message_ts,
            "files": [item.canonical_dict() for item in self.files],
            "authenticated_actor_only": True,
            "bulk_send": False,
        }

    @property
    def material_fingerprint(self) -> str:
        encoded = json.dumps(
            self.canonical_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def version_ref(self) -> str:
        return f"slack-material:{self.material_fingerprint}"


@dataclass(frozen=True, slots=True)
class SlackOutboundApproval:
    approval_ref: str
    evidence_ref: str
    material_fingerprint: str
    approved_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_ref", _safe_ref(self.approval_ref, "approval_ref"))
        object.__setattr__(self, "evidence_ref", _safe_ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(
            self,
            "material_fingerprint",
            _fingerprint(self.material_fingerprint, "material_fingerprint"),
        )
        object.__setattr__(self, "approved_at", _aware(self.approved_at, "approved_at"))


class SlackOutboundPreflightDecision(str, Enum):
    ALLOW = "allow"
    OUT_OF_SCOPE = "out_of_scope"
    WRONG_CONNECTOR_OR_TOOL = "wrong_connector_or_tool"
    TARGET_MISMATCH = "target_mismatch"
    APPROVAL_MISMATCH = "approval_mismatch"
    MATERIAL_CHANGED = "material_changed"
    VERSION_BINDING_MISMATCH = "version_binding_mismatch"


def slack_outbound_preflight(
    *,
    scope: SlackWorkspaceScope,
    material: SlackOutboundMaterial,
    approval: SlackOutboundApproval,
    intent: ConnectorWriteIntent,
    private_channel: bool = False,
) -> SlackOutboundPreflightDecision:
    if not all(
        [
            isinstance(scope, SlackWorkspaceScope),
            isinstance(material, SlackOutboundMaterial),
            isinstance(approval, SlackOutboundApproval),
            isinstance(intent, ConnectorWriteIntent),
        ]
    ):
        raise ContractError("invalid Slack outbound preflight contract")
    if not scope.authorizes(
        binding_ref=material.binding_ref,
        workspace_ref=material.workspace_ref,
        slack_team_id=material.slack_team_id,
        slack_app_id=material.slack_app_id,
        channel_id=material.channel_id,
        private_channel=private_channel,
    ):
        return SlackOutboundPreflightDecision.OUT_OF_SCOPE
    if intent.connector_id != "slack" or intent.tool_name != material.capability.value:
        return SlackOutboundPreflightDecision.WRONG_CONNECTOR_OR_TOOL
    if intent.binding_ref != material.binding_ref or intent.target_ref != material.target_ref:
        return SlackOutboundPreflightDecision.TARGET_MISMATCH
    if intent.approval_ref != approval.approval_ref or intent.evidence_ref != approval.evidence_ref:
        return SlackOutboundPreflightDecision.APPROVAL_MISMATCH
    if approval.material_fingerprint != material.material_fingerprint:
        return SlackOutboundPreflightDecision.MATERIAL_CHANGED
    if intent.payload_fingerprint != material.material_fingerprint:
        return SlackOutboundPreflightDecision.MATERIAL_CHANGED
    if intent.expected_version_ref != material.version_ref:
        return SlackOutboundPreflightDecision.VERSION_BINDING_MISMATCH
    return SlackOutboundPreflightDecision.ALLOW


@dataclass(frozen=True, slots=True)
class SlackOutboundReceipt:
    connector_receipt: ConnectorWriteReceipt
    capability: SlackOutboundCapability
    approved_target_ref: str
    result_message_ts: str | None = None
    result_file_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.connector_receipt, ConnectorWriteReceipt):
            raise ContractError("connector_receipt must be ConnectorWriteReceipt")
        if self.connector_receipt.connector_id != "slack":
            raise ContractError("Slack receipt requires slack connector receipt")
        if not isinstance(self.capability, SlackOutboundCapability):
            try:
                object.__setattr__(self, "capability", SlackOutboundCapability(self.capability))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Slack receipt capability") from exc
        object.__setattr__(
            self, "approved_target_ref", _safe_ref(self.approved_target_ref, "approved_target_ref")
        )
        if self.connector_receipt.target_ref != self.approved_target_ref:
            raise ContractError("Slack receipt target does not match approved target")
        object.__setattr__(self, "result_message_ts", _optional_ref(self.result_message_ts, "result_message_ts"))
        refs = tuple(_safe_ref(value, "result_file_ref") for value in self.result_file_refs)
        if len(refs) != len(set(refs)) or len(refs) > MAX_SLACK_FILES_PER_ACTION:
            raise ContractError("Slack receipt file refs are invalid")
        object.__setattr__(self, "result_file_refs", refs)
        if self.capability is SlackOutboundCapability.UPLOAD_FILE:
            if not self.result_file_refs:
                raise ContractError("upload_file receipt requires provider file refs")
        elif self.result_message_ts is None:
            raise ContractError("Slack message mutation receipt requires result message timestamp")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "connector_receipt": self.connector_receipt.safe_dict(),
            "capability": self.capability.value,
            "approved_target_ref": self.approved_target_ref,
            "result_message_ts": self.result_message_ts,
            "result_file_refs": list(self.result_file_refs),
            "trusted_provider_receipt": True,
            "model_text_counts_as_delivery": False,
        }


SLACK_MCP_ENDPOINT = "https://mcp.slack.com/mcp"
SLACK_REGISTERED_APP_REQUIRED = True
SLACK_CONFIDENTIAL_USER_OAUTH = True
SLACK_STATIC_READ_TOOL_ALLOWLIST_CONFIGURED = False
SLACK_LIVE_TOOLS_LIST_REQUIRED_FOR_READ_CLASSIFICATION = True
SLACK_UNKNOWN_MCP_TOOL_FAILS_CLOSED = True
SLACK_RAW_SIGNING_SECRET_IN_B54 = False
SLACK_RAW_OAUTH_TOKEN_IN_B54 = False
SLACK_AUTONOMOUS_BULK_MESSAGE_SUPPORTED = False
SLACK_USER_IMPERSONATION_SUPPORTED = False
REAL_SLACK_OAUTH_CONFIGURED = False
REAL_SLACK_MUTATION_CONFIGURED = False
