"""Trusted first-party Python client for Padiem AI Engine v1.

This module is Engine-owned transport code. Product/browser layers must not copy
its wire contract or mint approval authority. The caller identity/credential is
server-owned and every request is sent only through an injected internal
transport (normally a Cloudflare Service Binding adapter).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import re
from types import MappingProxyType
from typing import Any, AsyncIterator, Mapping, Protocol

from .orchestration_stream import EngineNdjsonContractError, EngineStreamError, decode_orchestration_ndjson

ENGINE_INTERNAL_ORIGIN = "https://padiem-ai-engine.internal"
ENGINE_CONTRACT_MAJOR = 1
ENGINE_CONTRACT_VERSION = "1.0"
ENGINE_EXECUTE_PATH = "/internal/v1/execute"
ENGINE_HEALTH_PATH = "/internal/v1/health"
ENGINE_ORCHESTRATE_PATH = "/internal/v1/orchestrate"
ENGINE_RESEARCH_PATH = "/internal/v1/research"
ENGINE_ORCHESTRATE_STREAM_PATH = "/internal/v1/orchestrate/stream"
ENGINE_ORCHESTRATE_RESUME_PATH = "/internal/v1/orchestrate/resume"
ENGINE_ORCHESTRATE_CANCEL_PATH = "/internal/v1/orchestrate/cancel"
ENGINE_MULTIMODAL_ATTACHMENTS_PATH = "/internal/v1/multimodal/attachments"
ENGINE_DOCUMENT_ADMISSION_PATH = "/internal/v1/documents"

_ENGINE_CALLER_HEADER = "X-Padiem-Engine-Caller"
_ENGINE_CREDENTIAL_HEADER = "X-Padiem-Engine-Credential"
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_CONTINUATION_RE = re.compile(r"^cont_[A-Za-z0-9_-]{8,123}$")
_ATTACHMENT_REF_RE = re.compile(r"^att_[A-Za-z0-9_-]{16,120}$")

# Canonical image attachment admission (#3210). Engine surfaces remain the
# single size/media/grammar authority; this client mirrors the same bounded
# contract so malformed requests fail before any network transport.
SUPPORTED_ATTACHMENT_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_ATTACHMENT_MAX_IMAGE_BYTES = 4 * 1024 * 1024  # == padiem_ai_core MAX_B14_IMAGE_BYTES
MAX_ATTACHMENT_IMAGE_BASE64_CHARS = ((_ATTACHMENT_MAX_IMAGE_BYTES + 2) // 3) * 4 + 4
_ATTACHMENT_ADMISSION_ALLOWED = frozenset(
    {"session_id", "media_type", "image_base64", "trace_id"}
)
_ATTACHMENT_ADMISSION_REQUIRED = frozenset({"session_id", "media_type", "image_base64"})
_ATTACHMENT_PROJECTION_FIELDS = ("attachment_ref", "media_type", "byte_size", "expires_at")

# COM2 document reference admission (#5881). The Engine route stays the single
# size/media/grammar authority; this client mirrors the bounded shape so a
# malformed reference fails before any transport, and it never rewrites the
# signed ticket values it carries for the product. Pinned against the Engine's
# own module by a drift test so the two copies cannot silently diverge.
FILE_TICKET_HEADER_NAMES = frozenset(
    {"X-Padiem-File-Ticket", "X-Padiem-File-Time", "X-Padiem-File-Proof"}
)
_DOCUMENT_FILE_ID_RE = re.compile(r"^file_[a-f0-9]{32}$")
_DOCUMENT_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_DOCUMENT_TICKET_VALUE_RE = re.compile(r"^[\x20-\x7e]+$")
_DOCUMENT_REF_RE = re.compile(r"^doc_[A-Za-z0-9_-]{16,120}$")
_DOCUMENT_ADMISSION_ALLOWED = frozenset(
    {"session_id", "file_id", "sha256", "file_ticket", "filename"}
)
_DOCUMENT_ADMISSION_REQUIRED = frozenset(
    {"session_id", "file_id", "sha256", "file_ticket"}
)
DOCUMENT_LANE_MEDIA_TYPE = "text/plain"
_DOCUMENT_PROJECTION_FIELDS = (
    "document_ref",
    "media_type",
    "byte_size",
    "expires_at",
    "total_chars",
    "next_offset",
    "window_eof",
)

_EXECUTION_ALLOWED = frozenset(
    {
        "agent",
        "messages",
        "session_id",
        "additional_system_context",
        "trace_id",
        "execution_context",
    }
)
_ORCHESTRATION_ALLOWED = _EXECUTION_ALLOWED | frozenset(
    {
        "subject_id",
        "user_credential_ref",
        "declared_plan",
        "pc_tools",
        "agent_plan",
        "tool_arguments",
        "recovery_policy",
        "max_retries",
        "require_evidence",
        "require_verification",
    }
)
_ORCHESTRATION_RESUME_ALLOWED = _EXECUTION_ALLOWED | frozenset(
    {
        "continuation_ref",
        "user_credential_ref",
        "decision",
        "subject_id",
        "agent_plan",
        "recovery_policy",
        "max_retries",
    }
)
_DEFERRED_AUTHORITY_FIELDS = frozenset(
    {
        "agent_definition",
        "compiled_agent_profile",
        "tool_authorization",
        "tool_runtime",
        "tool_arguments",
        "pause",
    }
)
_DECISION_FIELDS = frozenset(
    {"decision_id", "pause_id", "outcome", "authority_ref", "evidence_ref", "decided_at"}
)
_CANCEL_ALLOWED = frozenset({"continuation_ref", "reason"})

# #5015: the only authority-adjacent field this client may forward is the
# server-selected PC device hint on the two canonical PC plans. It is a closed
# shape, never a model-chosen device or a general tool argument surface.
_PC_PLAN_AGENT_IDS = frozenset({
    "agent:padiem:claw-pc-query@1",
    "agent:padiem:chat-pc-query@1",
})
_PC_PLAN_STEPS = MappingProxyType({
    "query_drives": (("query_drives", "claw.pc.query_drives"),),
    "files": (
        ("list_files", "claw.pc.list_files"),
        ("read_file", "claw.pc.read_file"),
    ),
    #: #5573: a listing-only request. The plan carries the list step alone, so
    #: the Engine is told not to read; the Engine still refuses ``read_file``
    #: for this hint. The table stays closed: any other shape is refused.
    "files_list": (("list_files", "claw.pc.list_files"),),
    #: #4434: the write lane. Its own shape, so a plan that may change a file is
    #: never also a plan that may read one.
    "files_write": (
        ("write_file", "claw.pc.write_file"),
        ("move_file", "claw.pc.move_file"),
        ("delete_file", "claw.pc.delete_file"),
    ),
})
#: Canonical PC device identity grammar (#5172). This client package has no
#: runtime dependency, so the two patterns are copied verbatim from
#: ``padiem_ai_core.pc_device_identity`` and a parity test proves the copies
#: stay identical to that single authority.
PC_DEVICE_ID_PATTERN = r"^[A-Za-z0-9_.:@+-]{1,128}$"
PC_MESH_NODE_ID_PATTERN = r"^node/[A-Za-z0-9._-]{0,64}/[A-Za-z0-9_.:@+-]{1,128}$"
_PC_DEVICE_ID_RE = re.compile(PC_DEVICE_ID_PATTERN)
_PC_MESH_NODE_ID_RE = re.compile(PC_MESH_NODE_ID_PATTERN)


def _is_pc_device_id(value: Any) -> bool:
    """True for the canonical bare or composed Mesh device identity."""
    if not isinstance(value, str) or not value:
        return False
    return bool(
        _PC_DEVICE_ID_RE.fullmatch(value) or _PC_MESH_NODE_ID_RE.fullmatch(value)
    )


def _trusted_pc_tool_arguments(agent_plan: Any, tool_arguments: Any) -> bool:
    """True only for the closed trusted-PC device hint on a canonical plan."""
    if not isinstance(agent_plan, Mapping) or not isinstance(tool_arguments, Mapping):
        return False
    if agent_plan.get("agent_id") not in _PC_PLAN_AGENT_IDS:
        return False
    if set(tool_arguments) not in ({"query_drives"}, {"files"}, {"files_list"}):
        return False
    key = next(iter(tool_arguments))
    steps = agent_plan.get("steps")
    expected = _PC_PLAN_STEPS[key]
    if not isinstance(steps, list) or len(steps) != len(expected):
        return False
    for step, (step_id, tool_id) in zip(steps, expected):
        if (
            not isinstance(step, Mapping)
            or step.get("step_id") != step_id
            or step.get("tool_id") != tool_id
        ):
            return False
    entry = tool_arguments[key]
    if not isinstance(entry, Mapping) or set(entry) != {"device_id"}:
        return False
    device_id = entry.get("device_id")
    return _is_pc_device_id(device_id)

ORCHESTRATION_FIELD_PARITY = MappingProxyType(
    {
        "app_id": "CLIENT_OWNED_AND_INJECTED",
        "agent": "SUPPORTED_AND_MAPPED",
        "messages": "SUPPORTED_AND_MAPPED",
        "session_id": "SUPPORTED_AND_MAPPED",
        "additional_system_context": "SUPPORTED_AND_MAPPED",
        "trace_id": "SUPPORTED_AND_MAPPED",
        "execution_context": "SUPPORTED_AND_MAPPED",
        "subject_id": "SUPPORTED_AND_MAPPED",
        "agent_plan": "SUPPORTED_AND_MAPPED",
        "declared_plan": "PC_REQUEST_SCOPE_DECLARATION_ONLY",
        "recovery_policy": "SUPPORTED_AND_MAPPED",
        "max_retries": "SUPPORTED_AND_MAPPED",
        "require_evidence": "SUPPORTED_AND_MAPPED",
        "require_verification": "SUPPORTED_AND_MAPPED",
        "continuation_ref": "RESUME_ONLY_SUPPORTED_AND_MAPPED",
        "decision": "RESUME_ONLY_SUPPORTED_AND_MAPPED",
        "reason": "CANCEL_ONLY_SUPPORTED_AND_MAPPED",
        "agent_definition": "EXPLICITLY_DEFERRED_AND_REJECTED",
        "compiled_agent_profile": "EXPLICITLY_DEFERRED_AND_REJECTED",
        "tool_authorization": "EXPLICITLY_DEFERRED_AND_REJECTED",
        "tool_runtime": "EXPLICITLY_DEFERRED_AND_REJECTED",
        "tool_arguments": "TRUSTED_PC_PLAN_DEVICE_HINT_ONLY",
        "pause": "UNSUPPORTED_AND_NOT_EXPOSED",
    }
)


class PadiemAiEngineClientError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = bool(retryable)
        self.metadata = dict(metadata) if isinstance(metadata, Mapping) else None


@dataclass(frozen=True, slots=True)
class EngineTransportResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.status, bool) or not isinstance(self.status, int) or not 100 <= self.status <= 599:
            raise ValueError("status must be an HTTP status integer")
        if not isinstance(self.body, bytes):
            raise ValueError("body must be bytes")
        if not isinstance(self.headers, Mapping):
            raise ValueError("headers must be a mapping")


@dataclass(frozen=True, slots=True)
class EngineStreamTransportResponse:
    status: int
    chunks: AsyncIterator[bytes]
    headers: Mapping[str, str] = field(default_factory=dict)


class EngineTransport(Protocol):
    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> EngineTransportResponse: ...


def _safe_identifier(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise PadiemAiEngineClientError(
            "invalid_client_configuration",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _credential(value: Any) -> str:
    if not isinstance(value, str) or not 32 <= len(value.encode("utf-8")) <= 512:
        raise PadiemAiEngineClientError(
            "invalid_client_configuration",
            "credential must contain 32 to 512 bytes",
        )
    return value


def _transport(value: Any) -> EngineTransport:
    if value is None or not callable(getattr(value, "request", None)):
        raise PadiemAiEngineClientError(
            "invalid_engine_transport",
            "Engine transport must provide async request()",
        )
    return value


def _execution_context(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "execution_context must be an object"
        )
    data = dict(value)
    allowed = {"trace_id", "idempotency_key", "timeout_seconds"}
    if set(data) - allowed:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "execution_context contains unsupported fields"
        )
    if "trace_id" not in data:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "execution_context.trace_id is required"
        )
    normalized: dict[str, Any] = {
        "trace_id": _safe_identifier("execution_context.trace_id", data["trace_id"])
    }
    if "idempotency_key" in data:
        key = data["idempotency_key"]
        if not isinstance(key, str) or not _IDEMPOTENCY_RE.fullmatch(key):
            raise PadiemAiEngineClientError(
                "invalid_engine_request",
                "execution_context.idempotency_key must be a bounded safe identifier",
            )
        normalized["idempotency_key"] = key
    if "timeout_seconds" in data:
        timeout = data["timeout_seconds"]
        # #4379: an explicit null means the execution carries no PADIEM deadline.
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 1 <= float(timeout) <= 3600
        ):
            raise PadiemAiEngineClientError(
                "invalid_engine_request",
                "execution_context.timeout_seconds must be a positive number or None",
            )
        normalized["timeout_seconds"] = timeout
    return normalized


def _decision(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PadiemAiEngineClientError("invalid_engine_request", "decision must be an object")
    data = dict(value)
    if set(data) != _DECISION_FIELDS:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "decision must contain the exact trusted decision fields"
        )
    for name in ("decision_id", "pause_id", "authority_ref", "evidence_ref"):
        _safe_identifier(f"decision.{name}", data[name])
    if data["outcome"] not in {"approved", "denied"}:
        raise PadiemAiEngineClientError("invalid_engine_request", "decision.outcome is invalid")
    decided_at = data["decided_at"]
    if not isinstance(decided_at, str):
        raise PadiemAiEngineClientError("invalid_engine_request", "decision.decided_at is invalid")
    try:
        parsed = datetime.fromisoformat(decided_at)
    except ValueError:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "decision.decided_at is invalid"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "decision.decided_at must be timezone-aware"
        )
    return data



def _pc_tools_context(data, app_id):
    value = data["pc_tools"]
    if (
        app_id not in {"padiem-chat", "b54-padiem-claw"}
        or not data.get("subject_id") or not data.get("session_id")
        or data.get("agent_plan") is not None
        or "tool_arguments" in data or "declared_plan" in data
        or not isinstance(value, Mapping) or set(value) != {"device_id", "allowed_scopes"}
        or not _is_pc_device_id(value.get("device_id"))
    ):
        raise PadiemAiEngineClientError("invalid_engine_request", "PC tools context is invalid")
    scopes = value["allowed_scopes"]
    if (not isinstance(scopes, list) or not scopes or len(scopes) > 3
        or any(not isinstance(v, str) or v not in {"query_drives", "files_list", "files"} for v in scopes)
        or len(set(scopes)) != len(scopes)):
        raise PadiemAiEngineClientError("invalid_engine_request", "PC tools scopes are invalid")
    return {"device_id": value["device_id"], "allowed_scopes": list(scopes)}


def _run_payload(app_id: str, request: Any, *, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise PadiemAiEngineClientError("invalid_engine_request", "Engine request must be an object")
    data = dict(request)
    deferred = set(data) & _DEFERRED_AUTHORITY_FIELDS
    if deferred:
        # The closed trusted-PC device hint is the one reviewed exception; every
        # other authority-bearing field stays rejected before transport.
        allowed_deferred = (
            {"tool_arguments"}
            if _trusted_pc_tool_arguments(
                data.get("agent_plan"), data.get("tool_arguments")
            )
            else set()
        )
        if deferred - allowed_deferred:
            raise PadiemAiEngineClientError(
                "unsupported_orchestration_field",
                "Engine authority-bearing fields are not client-supplied in this contract version",
            )
    if set(data) - allowed:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "Engine request contains unsupported fields"
        )
    if "declared_plan" in data:
        declared = data["declared_plan"]
        if not isinstance(declared, str) or declared not in _PC_PLAN_STEPS:
            raise PadiemAiEngineClientError(
                "invalid_engine_request", "declared_plan must be files_list, files, or query_drives"
            )
    if "agent" not in data or "messages" not in data:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "Engine request requires agent and messages"
        )
    payload: dict[str, Any] = {"app_id": app_id, "agent": data["agent"], "messages": data["messages"]}
    for name in (
        "session_id",
        "additional_system_context",
        "trace_id",
        "subject_id",
        "agent_plan",
        "declared_plan",
        "tool_arguments",
        "recovery_policy",
        "max_retries",
        "require_evidence",
        "require_verification",
        "continuation_ref",
    ):
        if name in data:
            payload[name] = data[name]
    if "user_credential_ref" in data:
        ref = data["user_credential_ref"]
        if app_id != "padiem-chat" or not isinstance(ref, str) or not ref:
            raise PadiemAiEngineClientError("invalid_engine_request", "User credential reference is invalid")
        payload["user_credential_ref"] = ref
    if "pc_tools" in data:
        payload["pc_tools"] = _pc_tools_context(data, app_id)
    if "execution_context" in data:
        payload["execution_context"] = _execution_context(data["execution_context"])
    if "decision" in data:
        payload["decision"] = _decision(data["decision"])
    return payload


def _cancel_payload(app_id: str, request: Any) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise PadiemAiEngineClientError("invalid_engine_request", "Engine cancel request must be an object")
    data = dict(request)
    if set(data) - _CANCEL_ALLOWED:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "Engine cancel request contains unsupported fields"
        )
    ref = data.get("continuation_ref")
    if not isinstance(ref, str) or not _CONTINUATION_RE.fullmatch(ref):
        raise PadiemAiEngineClientError("invalid_engine_request", "continuation_ref is required")
    payload = {"app_id": app_id, "continuation_ref": ref}
    if "reason" in data:
        reason = data["reason"]
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 256:
            raise PadiemAiEngineClientError(
                "invalid_engine_request", "cancel reason must be a bounded non-empty string"
            )
        payload["reason"] = reason
    return payload


def _attachment_admission_payload(app_id: str, request: Any) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "Engine attachment request must be an object"
        )
    data = dict(request)
    if set(data) - _ATTACHMENT_ADMISSION_ALLOWED:
        raise PadiemAiEngineClientError(
            "invalid_engine_request",
            "Engine attachment request contains unsupported fields",
        )
    if _ATTACHMENT_ADMISSION_REQUIRED - set(data):
        raise PadiemAiEngineClientError(
            "invalid_engine_request",
            "Engine attachment request is missing required fields",
        )
    session_id = _safe_identifier("session_id", data["session_id"])
    media_type = data["media_type"]
    if (
        not isinstance(media_type, str)
        or media_type.strip().lower() not in SUPPORTED_ATTACHMENT_MEDIA_TYPES
    ):
        raise PadiemAiEngineClientError(
            "invalid_engine_request",
            "Engine attachment media_type is not a supported image type",
        )
    image_base64 = data["image_base64"]
    if not isinstance(image_base64, str):
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "Engine attachment payload must be a base64 string"
        )
    if len(image_base64) > MAX_ATTACHMENT_IMAGE_BASE64_CHARS:
        raise PadiemAiEngineClientError(
            "invalid_engine_request",
            "Image attachment payload exceeds the bounded multimodal base64 size",
        )
    payload: dict[str, Any] = {
        "app_id": app_id,
        "session_id": session_id,
        "media_type": media_type.strip().lower(),
        "image_base64": image_base64,
    }
    if "trace_id" in data:
        payload["trace_id"] = _safe_identifier("trace_id", data["trace_id"])
    return payload


def _attachment_projection(body: dict[str, Any]) -> dict[str, Any]:
    if body.get("ok") is not True:
        raise PadiemAiEngineClientError(
            "invalid_engine_response", "Engine attachment admission response is invalid"
        )
    attachment = body.get("attachment")
    if not isinstance(attachment, Mapping):
        raise PadiemAiEngineClientError(
            "invalid_engine_response", "Engine attachment admission response is invalid"
        )
    attachment = dict(attachment)
    if set(attachment) != set(_ATTACHMENT_PROJECTION_FIELDS):
        raise PadiemAiEngineClientError(
            "invalid_engine_response", "Engine attachment admission response is invalid"
        )
    ref = attachment["attachment_ref"]
    if not isinstance(ref, str) or not _ATTACHMENT_REF_RE.fullmatch(ref):
        raise PadiemAiEngineClientError(
            "invalid_engine_response", "Engine attachment admission response is invalid"
        )
    media_type = attachment["media_type"]
    if not isinstance(media_type, str) or media_type not in SUPPORTED_ATTACHMENT_MEDIA_TYPES:
        raise PadiemAiEngineClientError(
            "invalid_engine_response", "Engine attachment admission response is invalid"
        )
    byte_size = attachment["byte_size"]
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 1:
        raise PadiemAiEngineClientError(
            "invalid_engine_response", "Engine attachment admission response is invalid"
        )
    expires_at = attachment["expires_at"]
    if expires_at is not None:
        if not isinstance(expires_at, str):
            raise PadiemAiEngineClientError(
                "invalid_engine_response", "Engine attachment admission response is invalid"
            )
        try:
            parsed = datetime.fromisoformat(expires_at)
        except ValueError:
            raise PadiemAiEngineClientError(
                "invalid_engine_response", "Engine attachment admission response is invalid"
            ) from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise PadiemAiEngineClientError(
                "invalid_engine_response", "Engine attachment admission response is invalid"
            )
    return {name: attachment[name] for name in _ATTACHMENT_PROJECTION_FIELDS}


def _document_admission_payload(app_id: str, request: Any) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "Engine document request must be an object"
        )
    data = dict(request)
    if set(data) - _DOCUMENT_ADMISSION_ALLOWED:
        raise PadiemAiEngineClientError(
            "invalid_engine_request",
            "Engine document request contains unsupported fields",
        )
    if _DOCUMENT_ADMISSION_REQUIRED - set(data):
        raise PadiemAiEngineClientError(
            "invalid_engine_request",
            "Engine document request is missing required fields",
        )
    file_id = data["file_id"]
    if not isinstance(file_id, str) or not _DOCUMENT_FILE_ID_RE.fullmatch(file_id):
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "Engine document file_id is invalid"
        )
    sha256 = data["sha256"]
    if not isinstance(sha256, str) or not _DOCUMENT_SHA256_RE.fullmatch(sha256):
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "Engine document sha256 is invalid"
        )
    ticket = data["file_ticket"]
    if not isinstance(ticket, Mapping) or set(ticket) != FILE_TICKET_HEADER_NAMES:
        raise PadiemAiEngineClientError(
            "invalid_engine_request", "Engine document file_ticket is invalid"
        )
    # The claim values are the product's own signed bytes: carried unchanged so
    # a second signature can never be minted here, and refused only when the
    # shape could not survive an HTTP header.
    headers = {name: ticket[name] for name in sorted(FILE_TICKET_HEADER_NAMES)}
    for name, value in headers.items():
        if not isinstance(value, str) or not _DOCUMENT_TICKET_VALUE_RE.fullmatch(value):
            raise PadiemAiEngineClientError(
                "invalid_engine_request",
                f"Engine document file_ticket {name} is invalid",
            )
    payload: dict[str, Any] = {
        "app_id": app_id,
        "session_id": _safe_identifier("session_id", data["session_id"]),
        "file_id": file_id,
        "sha256": sha256,
        "file_ticket": headers,
    }
    if "filename" in data:
        filename = data["filename"]
        if not isinstance(filename, str) or not filename.strip():
            raise PadiemAiEngineClientError(
                "invalid_engine_request", "Engine document filename is invalid"
            )
        payload["filename"] = filename.strip()
    return payload


def _document_projection(body: dict[str, Any]) -> dict[str, Any]:
    invalid = PadiemAiEngineClientError(
        "invalid_engine_response", "Engine document admission response is invalid"
    )
    if body.get("ok") is not True:
        raise invalid
    document = body.get("document")
    if not isinstance(document, Mapping) or set(document) != set(_DOCUMENT_PROJECTION_FIELDS):
        raise invalid
    projected = dict(document)
    if not isinstance(projected["document_ref"], str) or not _DOCUMENT_REF_RE.fullmatch(
        projected["document_ref"]
    ):
        raise invalid
    if projected["media_type"] != DOCUMENT_LANE_MEDIA_TYPE:
        raise invalid
    if projected["window_eof"] not in (True, False):
        raise invalid
    for name in ("byte_size", "total_chars", "next_offset"):
        value = projected[name]
        if name == "total_chars" and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise invalid
    if projected["byte_size"] < 1:
        raise invalid
    if projected["total_chars"] is not None and projected["total_chars"] < projected["next_offset"]:
        raise invalid
    expires_at = projected["expires_at"]
    if expires_at is not None:
        if not isinstance(expires_at, str):
            raise invalid
        try:
            parsed = datetime.fromisoformat(expires_at)
        except ValueError:
            raise invalid from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise invalid
    return {name: projected[name] for name in _DOCUMENT_PROJECTION_FIELDS}


def _json_body(response: EngineTransportResponse) -> dict[str, Any]:
    try:
        body = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PadiemAiEngineClientError(
            "invalid_engine_response",
            "Engine returned an invalid JSON response",
            status=response.status,
        ) from None
    if not isinstance(body, dict):
        raise PadiemAiEngineClientError(
            "invalid_engine_response", "Engine returned an invalid response object", status=response.status
        )
    if body.get("ok") is False:
        error = body.get("error") if isinstance(body.get("error"), Mapping) else {}
        raise PadiemAiEngineClientError(
            error.get("code") if isinstance(error.get("code"), str) else "engine_request_failed",
            error.get("message") if isinstance(error.get("message"), str) else "Padiem AI Engine request failed",
            status=response.status,
            retryable=error.get("retryable") is True,
            metadata=error.get("metadata") if isinstance(error.get("metadata"), Mapping) else None,
        )
    if not 200 <= response.status < 300:
        raise PadiemAiEngineClientError(
            "engine_http_error", "Padiem AI Engine request failed", status=response.status
        )
    return body


_JUDGEMENT_REASONS = frozenset(
    {
        "fresh_public_fact",
        "explicit_request",
        "volatile_business_fact",
        "stable_knowledge",
        "user_supplied_text",
        "clarify_context",
    }
)

class PadiemAiEngineClient:
    def __init__(self, *, transport: EngineTransport, app_id: str, caller_id: str, credential: str) -> None:
        self._transport = _transport(transport)
        self.app_id = _safe_identifier("app_id", app_id)
        self.caller_id = _safe_identifier("caller_id", caller_id)
        self._credential = _credential(credential)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            _ENGINE_CALLER_HEADER: self.caller_id,
            _ENGINE_CREDENTIAL_HEADER: self._credential,
        }

    async def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        response = await self._transport.request(
            method="POST",
            url=f"{ENGINE_INTERNAL_ORIGIN}{path}",
            headers=self._headers(),
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"),
        )
        return _json_body(response)

    async def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        body = await self._post(
            ENGINE_EXECUTE_PATH,
            _run_payload(self.app_id, request, allowed=_EXECUTION_ALLOWED),
        )
        if body.get("ok") is not True or not isinstance(body.get("answer"), str):
            raise PadiemAiEngineClientError(
                "invalid_engine_response", "Engine completed-run response is invalid"
            )
        return body

    async def search_evidence(self, *, query: str, agent: Mapping[str, Any]) -> dict[str, Any]:
        """Use the existing authenticated Engine research route with zero model calls.

        Product caller must first authorize a PUBLIC, minimized query. This
        generic Engine client cannot authorize browser text or claim consent.
        B14 model execution remains on the separate existing P01 lane.
        """
        if not isinstance(query, str) or not query.strip() or len(query) > 2_000:
            raise PadiemAiEngineClientError(
                "invalid_public_query", "Evidence query must be bounded public text",
            )
        if not isinstance(agent, Mapping):
            raise PadiemAiEngineClientError(
                "invalid_research_agent", "Research agent profile is required",
            )
        body = await self._post(ENGINE_RESEARCH_PATH, {
            "app_id": self.app_id,
            "operation": "search_evidence",
            "query": query.strip(),
            "agent": dict(agent),
        })
        sources = body.get("sources")
        context = body.get("grounding_context")
        if (
            body.get("ok") is not True
            or body.get("operation") != "search_evidence"
            or body.get("answer") is not None
            or not isinstance(sources, list)
            or not sources
            or not isinstance(context, str)
            or not context.startswith("웹 근거 사용 규칙:")
            or len(context) > 32_768
        ):
            raise PadiemAiEngineClientError(
                "invalid_engine_response", "Engine evidence-only response is invalid",
            )
        return {"sources": sources, "grounding_context": context}

    async def search_judgement(self, *, conversation: str, agent: Mapping[str, Any]) -> dict[str, Any]:
        """Ask the existing Engine research route to judge one conversation.

        Judgement only: zero retrieval, zero answer, zero provider authority, and the
        caller's selected answer model is untouched. The product still has to re-check
        the returned query before anything leaves Padiem.
        """
        if (
            not isinstance(conversation, str)
            or not conversation.strip()
            or len(conversation) > 4_000
        ):
            raise PadiemAiEngineClientError(
                "invalid_public_conversation", "Judgement input must be bounded conversation text",
            )
        if not isinstance(agent, Mapping):
            raise PadiemAiEngineClientError(
                "invalid_research_agent", "Research agent profile is required",
            )
        body = await self._post(ENGINE_RESEARCH_PATH, {
            "app_id": self.app_id,
            "operation": "search_judgement",
            "query": conversation.strip(),
            "agent": dict(agent),
        })
        reason = body.get("reason")
        needs_search = body.get("needs_search")
        if (
            body.get("ok") is not True
            or body.get("operation") != "search_judgement"
            or body.get("answer") is not None
            or not isinstance(needs_search, bool)
            or not isinstance(reason, str)
            or reason not in _JUDGEMENT_REASONS
            or (needs_search and not isinstance(body.get("query"), str))
        ):
            raise PadiemAiEngineClientError(
                "invalid_engine_response", "Engine search-judgement response is invalid",
            )
        return {
            "needs_search": needs_search,
            "query": body.get("query") if needs_search else None,
            "reason": reason,
        }

    async def orchestrate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        body = await self._post(
            ENGINE_ORCHESTRATE_PATH,
            _run_payload(self.app_id, request, allowed=_ORCHESTRATION_ALLOWED),
        )
        orchestration = body.get("orchestration")
        if body.get("ok") is not True or not isinstance(orchestration, Mapping):
            raise PadiemAiEngineClientError(
                "invalid_engine_response", "Engine orchestration response is invalid"
            )
        return dict(orchestration)

    async def stream_orchestration(
        self, request: Mapping[str, Any], *, pc_progress: bool = False
    ) -> AsyncIterator[dict[str, Any]]:
        """Opt-in Engine NDJSON transport; no implicit switch from orchestrate().

        The caller must validate P01 correlation and the terminal result before
        committing success. Partial event yields have no approval/dispatch power.
        """
        if type(pc_progress) is not bool:
            raise PadiemAiEngineClientError("invalid_engine_request", "pc_progress must be boolean")
        headers = self._headers()
        if pc_progress:
            headers["X-Padiem-PC-Progress"] = "1"
        payload = _run_payload(self.app_id, request, allowed=_ORCHESTRATION_ALLOWED)
        stream_request = getattr(self._transport, "stream_request", None)
        if not callable(stream_request):
            raise PadiemAiEngineClientError(
                "engine_stream_unavailable", "Engine streaming transport is not configured"
            )
        response = await stream_request(
            method="POST",
            url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_STREAM_PATH}",
            headers=headers,
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"),
        )
        if not isinstance(response, EngineStreamTransportResponse):
            raise PadiemAiEngineClientError("invalid_engine_stream", "Engine stream response is invalid")
        # A non-200 response is a JSON error, never stream events. Never retry.
        if response.status != 200 or response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/x-ndjson":
            close = getattr(response.chunks, "aclose", None)
            if callable(close):
                await close()
            raise PadiemAiEngineClientError(
                "engine_stream_unavailable" if response.status == 404 else "engine_http_error",
                "Padiem AI Engine stream request failed", status=response.status,
            )
        try:
            async for item in decode_orchestration_ndjson(response.chunks):
                yield item
        except EngineStreamError as exc:
            raise PadiemAiEngineClientError(exc.code, str(exc)) from exc
        except EngineNdjsonContractError as exc:
            metadata: dict[str, Any] = {
                "reason": exc.code, "record_kind": exc.record_kind,
            }
            raise PadiemAiEngineClientError(
                "invalid_engine_stream", "Engine streaming contract failed",
                metadata=metadata,
            ) from exc

    async def resume_orchestration(self, request: Mapping[str, Any]) -> dict[str, Any]:
        body = await self._post(
            ENGINE_ORCHESTRATE_RESUME_PATH,
            _run_payload(self.app_id, request, allowed=_ORCHESTRATION_RESUME_ALLOWED),
        )
        orchestration = body.get("orchestration")
        if body.get("ok") is not True or not isinstance(orchestration, Mapping):
            raise PadiemAiEngineClientError(
                "invalid_engine_response", "Engine orchestration resume response is invalid"
            )
        return dict(orchestration)

    async def cancel_orchestration_pause(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return await self._post(
            ENGINE_ORCHESTRATE_CANCEL_PATH,
            _cancel_payload(self.app_id, request),
        )

    async def admit_image_attachment(self, request: Mapping[str, Any]) -> dict[str, Any]:
        body = await self._post(
            ENGINE_MULTIMODAL_ATTACHMENTS_PATH,
            _attachment_admission_payload(self.app_id, request),
        )
        return _attachment_projection(body)

    async def admit_document_reference(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Admit one COM2 file reference: the lane keeps the bytes, Engine the text.

        The reference shape carries no document bytes, so the request stays far
        below the inline admission envelope. ``file_ticket`` is the product's own
        signed read claim, forwarded unchanged.
        """
        body = await self._post(
            ENGINE_DOCUMENT_ADMISSION_PATH,
            _document_admission_payload(self.app_id, request),
        )
        return _document_projection(body)

    async def health(self) -> dict[str, Any]:
        response = await self._transport.request(
            method="GET",
            url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_HEALTH_PATH}",
            headers={},
            body=None,
        )
        return _json_body(response)
