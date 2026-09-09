"""Promoted Google Drive READ capability contract (#2166, parent #2010).

Ports the already-reviewed B54 Google Drive READ surface
(``apps/korean-ai-code-agent/src/kagent/google_drive_connector.py`` and
``google_drive_scope.py``) into canonical Padiem AI Core. This module is a
projection of reviewed logic, not a new design: the four reviewed READ tools,
the Google-native export table, the shortcut/trashed/binary bounds and the
Shared Drive identity handling all come from B54, which remains compatibility
evidence only and is never mutated here.

Core owns no HTTP, no OAuth flow, no credential value, no token refresh and no
Production client. The host application supplies a trusted
:class:`DriveReadPort`; Core only shapes bounded, untrusted JSON projections.

Fail-closed rules ported from the reviewed B54 contract:

* only the four promoted READ tool ids (and their canonical ids) classify as
  READ; every unknown or future Drive tool id — including create, update, move,
  share and delete tools that do not exist in Core — classifies as
  ``WRITE_OR_MATERIAL`` or ``UNKNOWN`` and never receives a READ grant;
* trashed resources are never readable: a trashed resource fails closed instead
  of leaking content through a stale link;
* shortcut resources stay metadata-only — the shortcut target is never
  auto-followed and requires independently authorized target resolution;
* binary/non-text resources are never silently ingested: content reads fail
  closed while metadata and link remain usable;
* Shared Drive identity (``driveId``) stays distinguishable from My Drive;
* provider OAuth scope strings never become Core authorization facts — only
  bounded Core auth-scope tokens cross this contract, and raw OAuth tokens can
  never appear in any projection.

This module is deterministic and network-free. It performs zero provider calls
on its own: every provider read goes through the injected trusted port.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import inspect
import json
import re
from typing import Any, Awaitable, Mapping, Protocol
from urllib.parse import quote

from .connector_registry import ConnectorDescriptor
from .contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from .tool_runtime import MAX_TOOL_OUTPUT_BYTES, ToolHandler, ToolRuntime


class DriveContractError(ValueError):
    """Safe Google Drive projection contract failure (B54 ContractError port)."""


DRIVE_CONNECTOR_ID = "connector:google:drive@1"

# Provider OAuth scope (trusted port boundary only; never a Core identifier).
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

# Core ToolSpec auth_scope token. contracts._IDENTIFIER_RE rejects "/" so the
# provider URL cannot be a ToolSpec scope; the port still receives the exact
# provider scope above as required_scopes.
DRIVE_READONLY_AUTH_SCOPE = "drive.readonly"

# The full provider Drive scope is broader than any Padiem authority: it is
# recorded as review evidence only and is never registered in Core.
DRIVE_FULL_SCOPE = "https://www.googleapis.com/auth/drive"
DRIVE_FULL_AUTH_SCOPE = "drive.full"

DRIVE_BASE_URL = "https://www.googleapis.com/drive/v3"

# Reviewed B54 bounds (google_drive_connector.py:14-27).
REQUEST_TIMEOUT_SECONDS = 30
PAGE_SIZE = 25
MAX_DRIVE_QUERY_CHARS = 1_000
FILE_FIELDS = (
    "id,name,mimeType,driveId,parents,trashed,modifiedTime,version,"
    "md5Checksum,sha256Checksum,headRevisionId,resourceKey,"
    "shortcutDetails(targetId,targetMimeType,targetResourceKey),"
    "webViewLink,size,owners(emailAddress)"
)
CONTENT_METADATA_FIELDS = (
    "id,name,mimeType,trashed,driveId,version,"
    "shortcutDetails(targetId,targetMimeType,targetResourceKey)"
)

EXPORTABLE_MIME: dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
GOOGLE_SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

_TEXTUAL_APPLICATION_MIME = frozenset(
    {
        "application/json",
        "application/xml",
        "application/xhtml+xml",
        "application/javascript",
        "application/x-ndjson",
        "application/yaml",
        "application/x-yaml",
        "application/sql",
        "application/toml",
    }
)

# Core-side output bounds (analogous to the Gmail promotion).
MAX_FILE_CONTENT_CHARS = 20_000
MAX_FILE_REFS = PAGE_SIZE
MAX_NAME_CHARS = 512
MAX_MIME_CHARS = 255
MAX_PROVIDER_LIST_BYTES = 256_000
MAX_PROVIDER_METADATA_BYTES = 128_000
MAX_PROVIDER_CONTENT_BYTES = 1_000_000

DRIVE_SEARCH_FILES_TOOL_ID = "drive.search_files"
DRIVE_LIST_RECENT_FILES_TOOL_ID = "drive.list_recent_files"
DRIVE_GET_FILE_METADATA_TOOL_ID = "drive.get_file_metadata"
DRIVE_READ_FILE_CONTENT_TOOL_ID = "drive.read_file_content"

DRIVE_READ_TOOL_IDS = (
    DRIVE_SEARCH_FILES_TOOL_ID,
    DRIVE_LIST_RECENT_FILES_TOOL_ID,
    DRIVE_GET_FILE_METADATA_TOOL_ID,
    DRIVE_READ_FILE_CONTENT_TOOL_ID,
)

DRIVE_CANONICAL_TOOL_IDS = (
    "tool:google:drive.search_files@1",
    "tool:google:drive.list_recent_files@1",
    "tool:google:drive.get_file_metadata@1",
    "tool:google:drive.read_file_content@1",
)


class DriveReadPort(Protocol):
    """Trusted Google Drive HTTP/OAuth boundary (B54 AuthorizedGoogleDriveHttpPort).

    Callers pass only connector binding + actor refs and the exact readonly
    scope requirement. Implementations resolve/refresh credentials outside
    model/task state, verify the required scope, enforce the response byte
    bound, and return decoded provider JSON/text. Implementations may be sync or
    async; Core awaits when needed. Core never implements this port.
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

    def get_text(
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
    ) -> str | Awaitable[str]:
        ...


def drive_read_tool_specs() -> tuple[ToolSpec, ...]:
    """READ-only ToolSpecs mirroring the reviewed B54 DRIVE_TOOLS surface."""

    return (
        ToolSpec(
            id=DRIVE_SEARCH_FILES_TOOL_ID,
            title="Drive search files",
            description=(
                "Search the connected Google Drive by name and full text. Returns only bounded file "
                "references with names, types, modified times and links; trashed resources are never "
                "returned."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to search for."}},
                "required": ["query"],
                "additionalProperties": False,
            },
            auth_scope=(DRIVE_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=DRIVE_LIST_RECENT_FILES_TOOL_ID,
            title="Drive list recent files",
            description=(
                "List the most recently modified files, newest first. Returns bounded file references "
                "only; trashed resources are never returned."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            auth_scope=(DRIVE_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=DRIVE_GET_FILE_METADATA_TOOL_ID,
            title="Drive get file metadata",
            description=(
                "Read bounded metadata for one file: Drive location, modified time, server version, "
                "checksums and shortcut target metadata when present. Content is never returned."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {"fileId": {"type": "string", "description": "Google Drive file id."}},
                "required": ["fileId"],
                "additionalProperties": False,
            },
            auth_scope=(DRIVE_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=DRIVE_READ_FILE_CONTENT_TOOL_ID,
            title="Drive read file content",
            description=(
                "Read bounded text from one file. Google Docs, Sheets and Slides are exported to "
                "text-compatible formats. Shortcuts are metadata-only, trashed resources fail closed, "
                "and binary files are never silently ingested."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {"fileId": {"type": "string", "description": "Google Drive file id."}},
                "required": ["fileId"],
                "additionalProperties": False,
            },
            auth_scope=(DRIVE_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
    )


DRIVE_DESCRIPTOR = ConnectorDescriptor(
    connector_id=DRIVE_CONNECTOR_ID,
    title="Google Drive",
    canonical_tool_ids=DRIVE_CANONICAL_TOOL_IDS,
    requires_authorization=True,
)


# --- bounded validation helpers (ported from B54 google_drive_scope.py) ---

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CHECKSUM_RE = re.compile(r"^[0-9a-fA-F]{16,128}$")


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise DriveContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise DriveContractError(f"{field_name} must be a bounded safe reference")
    return normalized


def _optional_ref(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _safe_ref(value, field_name)


def _bounded_text(value: str, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise DriveContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if len(normalized) > limit:
        raise DriveContractError(f"{field_name} exceeds {limit} characters")
    return normalized


def _optional_checksum(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _CHECKSUM_RE.fullmatch(value.strip()):
        raise DriveContractError(f"{field_name} must be a hexadecimal checksum")
    return value.strip().lower()


def _optional_version(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise DriveContractError(f"{field_name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise DriveContractError(f"{field_name} must be a positive integer") from exc
    if parsed < 1:
        raise DriveContractError(f"{field_name} must be a positive integer")
    return parsed


def _optional_timestamp(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DriveContractError(f"{field_name} must be an RFC3339 timestamp")
    normalized = value.strip()
    candidate = normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise DriveContractError(f"{field_name} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DriveContractError(f"{field_name} must include timezone information")
    return normalized


def _optional_size(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise DriveContractError(f"{field_name} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise DriveContractError(f"{field_name} must be a non-negative integer") from exc
    if parsed < 0:
        raise DriveContractError(f"{field_name} must be a non-negative integer")
    return parsed


def is_textual_mime(mime_type: str | None) -> bool:
    """Whether a provider mime type is readable as bounded text (B54 port)."""

    if not mime_type:
        return False
    normalized = mime_type.split(";", 1)[0].strip().lower()
    return normalized.startswith("text/") or normalized in _TEXTUAL_APPLICATION_MIME


def export_mime_for(mime_type: str | None) -> str | None:
    """Google-native export target for a provider mime type, when reviewed."""

    if not mime_type:
        return None
    return EXPORTABLE_MIME.get(mime_type.split(";", 1)[0].strip().lower())


def drive_search_query(value: str) -> str:
    """Build the reviewed B54 Drive search query with escaped user input."""

    if not isinstance(value, str) or not value.strip():
        raise DriveContractError("Drive search query is required")
    normalized = value.strip()
    if len(normalized) > MAX_DRIVE_QUERY_CHARS:
        raise DriveContractError(f"Drive search query exceeds {MAX_DRIVE_QUERY_CHARS} characters")
    escaped = normalized.replace("\\", "\\\\").replace("'", "\\'")
    return f"name contains '{escaped}' or fullText contains '{escaped}'"


class DriveResourceClassification(str, Enum):
    """Fail-closed classification of one Drive resource before any read."""

    TEXT_READ = "text_read"
    GOOGLE_NATIVE_EXPORT = "google_native_export"
    SHORTCUT_TARGET_REQUIRED = "shortcut_target_required"
    TRASHED_FAIL_CLOSED = "trashed_fail_closed"
    BINARY_NOT_INGESTED = "binary_not_ingested"


def classify_drive_resource(metadata: Mapping[str, Any]) -> DriveResourceClassification:
    """Classify bounded provider metadata; content is never assumed readable."""

    if not isinstance(metadata, Mapping):
        raise DriveContractError("Drive metadata must be a mapping")
    if metadata.get("trashed") is True:
        return DriveResourceClassification.TRASHED_FAIL_CLOSED
    mime = metadata.get("mimeType")
    mime_value = mime if isinstance(mime, str) else None
    if mime_value is not None and mime_value.split(";", 1)[0].strip().lower() == GOOGLE_SHORTCUT_MIME:
        return DriveResourceClassification.SHORTCUT_TARGET_REQUIRED
    if export_mime_for(mime_value) is not None:
        return DriveResourceClassification.GOOGLE_NATIVE_EXPORT
    if is_textual_mime(mime_value):
        return DriveResourceClassification.TEXT_READ
    return DriveResourceClassification.BINARY_NOT_INGESTED


@dataclass(frozen=True, slots=True)
class DriveFileProjection:
    """Bounded metadata-only projection of one Drive resource.

    Shared Drive identity (``drive_id``) and version evidence (``version``,
    ``modified_time``, checksums, ``head_revision_id``) are preserved when the
    provider returns them. Content is never carried by this projection: a
    shortcut target stays a reference that must be independently authorized,
    and no trashed resource may ever be projected.
    """

    file_id: str
    name: str
    mime_type: str
    drive_id: str | None = None
    version: int | None = None
    modified_time: str | None = None
    md5_checksum: str | None = None
    sha256_checksum: str | None = None
    head_revision_id: str | None = None
    resource_key: str | None = None
    web_view_link: str | None = None
    size_bytes: int | None = None
    shortcut_target_id: str | None = None
    shortcut_target_mime_type: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_id", _safe_ref(self.file_id, "file_id"))
        object.__setattr__(self, "name", _bounded_text(self.name, "name", MAX_NAME_CHARS))
        object.__setattr__(self, "mime_type", _bounded_text(self.mime_type, "mime_type", MAX_MIME_CHARS))
        object.__setattr__(self, "drive_id", _optional_ref(self.drive_id, "drive_id"))
        object.__setattr__(self, "version", _optional_version(self.version, "version"))
        object.__setattr__(
            self, "modified_time", _optional_timestamp(self.modified_time, "modified_time")
        )
        object.__setattr__(self, "md5_checksum", _optional_checksum(self.md5_checksum, "md5_checksum"))
        object.__setattr__(
            self, "sha256_checksum", _optional_checksum(self.sha256_checksum, "sha256_checksum")
        )
        object.__setattr__(
            self, "head_revision_id", _optional_ref(self.head_revision_id, "head_revision_id")
        )
        object.__setattr__(self, "resource_key", _optional_ref(self.resource_key, "resource_key"))
        object.__setattr__(self, "web_view_link", _optional_ref(self.web_view_link, "web_view_link"))
        object.__setattr__(self, "size_bytes", _optional_size(self.size_bytes, "size_bytes"))
        object.__setattr__(
            self, "shortcut_target_id", _optional_ref(self.shortcut_target_id, "shortcut_target_id")
        )
        object.__setattr__(
            self,
            "shortcut_target_mime_type",
            _optional_ref(self.shortcut_target_mime_type, "shortcut_target_mime_type"),
        )

    @property
    def space_kind(self) -> str:
        return "shared_drive" if self.drive_id else "my_drive"

    def version_evidence(self) -> dict[str, object]:
        """Version/checksum/modified evidence preserved for downstream review."""

        return {
            "version": self.version,
            "modified_time": self.modified_time,
            "md5_checksum": self.md5_checksum,
            "sha256_checksum": self.sha256_checksum,
            "head_revision_id": self.head_revision_id,
            "resource_key": self.resource_key,
        }

    def safe_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "name": self.name,
            "mime_type": self.mime_type,
            "space_kind": self.space_kind,
            "shared_drive_id": self.drive_id,
            "size_bytes": self.size_bytes,
            "web_view_link": self.web_view_link,
            "version_evidence": self.version_evidence(),
            "shortcut_target_id": self.shortcut_target_id,
            "shortcut_target_mime_type": self.shortcut_target_mime_type,
            "shortcut_target_escape": False,
            "content_ingested": False,
            "binary_auto_ingested": False,
            "trashed": False,
            "drive_content_trusted": False,
            "raw_credentials_present": False,
        }


def project_drive_file(metadata: Mapping[str, Any]) -> DriveFileProjection:
    """Project bounded provider metadata; trashed resources fail closed."""

    if not isinstance(metadata, Mapping):
        raise DriveContractError("Drive metadata must be a mapping")
    if metadata.get("trashed") is True:
        raise DriveContractError("Drive resource is trashed and is not readable")
    file_id = metadata.get("id")
    if not isinstance(file_id, str) or not file_id.strip():
        raise DriveContractError("Drive provider file is missing id")
    name = metadata.get("name")
    mime = metadata.get("mimeType")
    shortcut = metadata.get("shortcutDetails")
    shortcut_target_id = None
    shortcut_target_mime = None
    if isinstance(shortcut, Mapping):
        target_id = shortcut.get("targetId")
        target_mime = shortcut.get("targetMimeType")
        if isinstance(target_id, str) and target_id.strip():
            shortcut_target_id = target_id.strip()
        if isinstance(target_mime, str) and target_mime.strip():
            shortcut_target_mime = target_mime.strip()
    return DriveFileProjection(
        file_id=file_id.strip(),
        name=name if isinstance(name, str) and name.strip() else "(untitled)",
        mime_type=mime if isinstance(mime, str) and mime.strip() else "application/octet-stream",
        drive_id=metadata.get("driveId") if isinstance(metadata.get("driveId"), str) else None,
        version=metadata.get("version"),
        modified_time=metadata.get("modifiedTime") if isinstance(metadata.get("modifiedTime"), str) else None,
        md5_checksum=metadata.get("md5Checksum") if isinstance(metadata.get("md5Checksum"), str) else None,
        sha256_checksum=(
            metadata.get("sha256Checksum") if isinstance(metadata.get("sha256Checksum"), str) else None
        ),
        head_revision_id=(
            metadata.get("headRevisionId") if isinstance(metadata.get("headRevisionId"), str) else None
        ),
        resource_key=metadata.get("resourceKey") if isinstance(metadata.get("resourceKey"), str) else None,
        web_view_link=metadata.get("webViewLink") if isinstance(metadata.get("webViewLink"), str) else None,
        size_bytes=metadata.get("size"),
        shortcut_target_id=shortcut_target_id,
        shortcut_target_mime_type=shortcut_target_mime,
    )


class DriveCapability(str, Enum):
    """Explicit Drive capability classes (reviewed B54 READ + unsupported write)."""

    READ = "read"
    MUTATION = "mutation"


class DriveCapabilityClassification(str, Enum):
    """Fail-closed classification result for an unclassified Drive tool id."""

    READ = "read"
    WRITE_OR_MATERIAL = "write_or_material"
    UNKNOWN = "unknown"


_WRITE_HINT_TOKENS = ("create", "update", "upload", "delete", "move", "trash", "share", "permission")


def classify_drive_tool_id(tool_id: str) -> DriveCapabilityClassification:
    """Classify a Drive tool id; everything unregistered fails closed."""

    if not isinstance(tool_id, str) or not tool_id.strip():
        raise DriveContractError("tool_id must be a non-empty string")
    normalized = tool_id.strip()
    if not _SAFE_ID_RE.fullmatch(normalized):
        raise DriveContractError("tool_id must be a bounded safe identifier")
    if normalized in DRIVE_READ_TOOL_IDS or normalized in DRIVE_CANONICAL_TOOL_IDS:
        return DriveCapabilityClassification.READ
    lowered = normalized.lower()
    if any(token in lowered for token in _WRITE_HINT_TOKENS):
        return DriveCapabilityClassification.WRITE_OR_MATERIAL
    return DriveCapabilityClassification.UNKNOWN


def provider_scopes_for_capability(capability: DriveCapability) -> tuple[str, ...]:
    """Provider OAuth scopes required by a capability (trusted port boundary only)."""

    if not isinstance(capability, DriveCapability):
        raise DriveContractError("capability must be DriveCapability")
    if capability is DriveCapability.READ:
        return (DRIVE_READONLY_SCOPE,)
    if capability is DriveCapability.MUTATION:
        # Recorded as review evidence only: no mutation tool is registered in
        # Core, so this scope is never requested by this contract.
        return (DRIVE_FULL_SCOPE,)
    raise DriveContractError("unsupported Drive capability")


def core_auth_scopes_for_capability(capability: DriveCapability) -> tuple[str, ...]:
    """Bounded Core auth-scope tokens required by a capability."""

    if not isinstance(capability, DriveCapability):
        raise DriveContractError("capability must be DriveCapability")
    if capability is DriveCapability.READ:
        return (DRIVE_READONLY_AUTH_SCOPE,)
    if capability is DriveCapability.MUTATION:
        return (DRIVE_FULL_AUTH_SCOPE,)
    raise DriveContractError("unsupported Drive capability")


def capability_requires_p01_approval(capability: DriveCapability) -> bool:
    """Whether a capability requires existing P01 approval semantics.

    READ never requires approval. Any mutation requires existing P01
    approval/evidence semantics, which this contract never mints.
    """

    if not isinstance(capability, DriveCapability):
        raise DriveContractError("capability must be DriveCapability")
    return capability is DriveCapability.MUTATION


@dataclass(frozen=True, slots=True)
class DriveCapabilityGrant:
    """One bounded capability grant fact for a connector binding.

    ``granted_capabilities`` carries only explicit capability values resolved
    server-side from grant references; it is never derived from caller JSON.
    Raw OAuth/access/refresh tokens can never appear here — the grant carries
    capability facts only.
    """

    connector_id: str
    binding_ref: str
    granted_capabilities: tuple[DriveCapability, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.connector_id, str) or not _SAFE_ID_RE.fullmatch(self.connector_id.strip()):
            raise DriveContractError("connector_id must be a bounded safe identifier")
        if not isinstance(self.binding_ref, str) or not _SAFE_ID_RE.fullmatch(self.binding_ref.strip()):
            raise DriveContractError("binding_ref must be a bounded safe identifier")
        if not isinstance(self.granted_capabilities, tuple) or any(
            not isinstance(item, DriveCapability) for item in self.granted_capabilities
        ):
            raise DriveContractError("granted_capabilities must contain DriveCapability values")
        if len(self.granted_capabilities) != len(set(self.granted_capabilities)):
            raise DriveContractError("granted_capabilities must be unique")

    def allows(self, capability: DriveCapability) -> bool:
        if not isinstance(capability, DriveCapability):
            raise DriveContractError("capability must be DriveCapability")
        return capability in self.granted_capabilities

    def mutation_authority(self) -> bool:
        """Whether this grant carries any Drive write authority."""

        return self.allows(DriveCapability.MUTATION)

    def safe_dict(self) -> dict[str, object]:
        return {
            "connector_id": self.connector_id,
            "binding_ref": self.binding_ref,
            "granted_capabilities": sorted(item.value for item in self.granted_capabilities),
            "mutation_authority": self.mutation_authority(),
            "raw_credentials_present": False,
            "oauth_token_present": False,
            "mints_approval_authority": False,
            "shortcut_target_escape": False,
        }


# Review-state mirrors of the B54 compatibility contract, kept fail-closed.
DRIVE_SHORTCUT_AUTO_ESCAPE = False
DRIVE_TRASHED_RESOURCE_READABLE = False
DRIVE_BINARY_AUTO_INGEST = False
DRIVE_SHARED_DRIVE_IDENTITY_PRESERVED = True
DRIVE_VERSION_EVIDENCE_PRESERVED = True
DRIVE_WRITE_TOOLS_PRESENT = False
DRIVE_RAW_CREDENTIAL_IN_CORE = False
DRIVE_OAUTH_FLOW_IMPLEMENTED = False
DRIVE_LIVE_PROVIDER_CALLS = 0


def drive_capability_snapshot() -> dict[str, object]:
    """Deterministic, network-free snapshot of the promoted Drive READ contract."""

    return {
        "contract_version": "padiem-drive-capability.v1",
        "connector_id": DRIVE_CONNECTOR_ID,
        "capabilities": {
            "read": {
                "core_auth_scopes": list(core_auth_scopes_for_capability(DriveCapability.READ)),
                "requires_p01_approval": capability_requires_p01_approval(DriveCapability.READ),
            },
            "mutation": {
                "core_auth_scopes": list(core_auth_scopes_for_capability(DriveCapability.MUTATION)),
                "requires_p01_approval": capability_requires_p01_approval(DriveCapability.MUTATION),
            },
        },
        "read_tool_ids": list(DRIVE_READ_TOOL_IDS),
        "canonical_tool_ids": list(DRIVE_CANONICAL_TOOL_IDS),
        "registered_write_tools": [],
        "google_native_export_mimes": dict(sorted(EXPORTABLE_MIME.items())),
        "search_list_metadata_read": True,
        "shortcut_escape": DRIVE_SHORTCUT_AUTO_ESCAPE,
        "trashed_resource_failclosed": not DRIVE_TRASHED_RESOURCE_READABLE,
        "binary_auto_ingest": DRIVE_BINARY_AUTO_INGEST,
        "shared_drive_identity_preserved": DRIVE_SHARED_DRIVE_IDENTITY_PRESERVED,
        "version_evidence_preserved": DRIVE_VERSION_EVIDENCE_PRESERVED,
        "provider_scope_grants_padiem_authority": False,
        "mints_second_approval_authority": False,
        "raw_credentials_present": False,
        "oauth_flow_implemented": DRIVE_OAUTH_FLOW_IMPLEMENTED,
        "live_provider_calls": DRIVE_LIVE_PROVIDER_CALLS,
        "production_activation": False,
    }


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
        "provider": "google_drive",
        "operation": envelope.get("operation"),
        "result_status": "REVIEW_REQUIRED",
        "truncated": True,
        "reason": "bounded Drive projection exceeded the Core tool output bound",
        "result_sha256": hashlib.sha256(encoded).hexdigest(),
        "drive_content_trusted": False,
        "raw_credentials_present": False,
    }


async def _port_json(
    port: DriveReadPort,
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
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url=DRIVE_BASE_URL,
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
        # cause chain, or the implicit context chain.
        sanitized = DriveContractError("The Google Drive provider port failed.")
    else:
        if not isinstance(result, dict):
            raise DriveContractError("The Google Drive provider port returned an invalid body.")
        return result

    raise sanitized


async def _port_text(
    port: DriveReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
    path: str,
    query: dict[str, str],
    max_response_bytes: int,
) -> str:
    def _call() -> str | Awaitable[str]:
        return port.get_text(
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url=DRIVE_BASE_URL,
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
        sanitized = DriveContractError("The Google Drive provider port failed.")
    else:
        if not isinstance(result, str):
            raise DriveContractError("The Google Drive provider port returned an invalid body.")
        return result

    raise sanitized


def _string_arg(args: dict[str, Any], key: str, *, limit: int = 1_024) -> str | None:
    value = args.get(key)
    if isinstance(value, str) and value.strip():
        normalized = value.strip()
        if len(normalized) > limit:
            raise DriveContractError(f"{key} exceeds {limit} characters")
        return normalized
    return None


def _bounded_content(value: str) -> tuple[str, bool]:
    if len(value) > MAX_FILE_CONTENT_CHARS:
        return value[:MAX_FILE_CONTENT_CHARS], True
    return value, False


def _list_envelope(
    *,
    operation: str,
    files: list[dict[str, Any]],
    more: bool,
    trashed_omitted: int,
) -> dict[str, Any]:
    status = "UNKNOWN" if not files else ("REVIEW_REQUIRED" if more else "OK")
    return _bounded_envelope(
        {
            "provider": "google_drive",
            "operation": operation,
            "result_status": status,
            "files": files,
            "result_count": len(files),
            "more_results_available": more,
            "page_followed": False,
            "trashed_omitted_count": trashed_omitted,
            "drive_content_trusted": False,
            "raw_credentials_present": False,
        }
    )


def build_drive_read_handlers(
    port: DriveReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
) -> dict[str, ToolHandler]:
    """Bind the reviewed readonly projections to one trusted port instance.

    binding_ref/actor_ref are forwarded only to the trusted port and never
    appear in the returned output or in DriveContractError messages.
    """

    async def _list_files(
        arguments: dict[str, Any],
        *,
        operation: str,
        query_text: str | None,
    ) -> Any:
        params = {
            "pageSize": str(PAGE_SIZE),
            "fields": f"files({FILE_FIELDS})",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if query_text:
            params["q"] = f"({drive_search_query(query_text)}) and trashed = false"
        else:
            params["q"] = "trashed = false"
            params["orderBy"] = "modifiedTime desc"
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path="/files",
            query=params,
            max_response_bytes=MAX_PROVIDER_LIST_BYTES,
        )
        raw_files = body.get("files", [])
        if raw_files is None:
            raw_files = []
        if not isinstance(raw_files, list):
            raise DriveContractError("Google Drive returned an invalid file list.")
        files: list[dict[str, Any]] = []
        trashed_omitted = 0
        for item in raw_files[:MAX_FILE_REFS]:
            if not isinstance(item, dict):
                continue
            if item.get("trashed") is True:
                trashed_omitted += 1
                continue
            files.append(project_drive_file(item).safe_dict())
        more = isinstance(body.get("nextPageToken"), str) and bool(body.get("nextPageToken"))
        return _list_envelope(
            operation=operation,
            files=files,
            more=more,
            trashed_omitted=trashed_omitted,
        )

    async def search_files(arguments: dict[str, Any]) -> Any:
        query_text = _string_arg(dict(arguments), "query", limit=MAX_DRIVE_QUERY_CHARS)
        if not query_text:
            raise DriveContractError("A Drive search needs a query.")
        return await _list_files(
            arguments, operation="files.list.search", query_text=query_text
        )

    async def list_recent_files(arguments: dict[str, Any]) -> Any:
        return await _list_files(arguments, operation="files.list.recent", query_text=None)

    async def get_file_metadata(arguments: dict[str, Any]) -> Any:
        file_id = _string_arg(dict(arguments), "fileId")
        if not file_id:
            raise DriveContractError("A Drive file id is needed.")
        body = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path=f"/files/{quote(file_id, safe='')}",
            query={"fields": FILE_FIELDS, "supportsAllDrives": "true"},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        if body.get("trashed") is True:
            raise DriveContractError("Drive resource is trashed and is not readable")
        projection = project_drive_file(body)
        return _bounded_envelope(
            {
                "provider": "google_drive",
                "operation": "files.get",
                "result_status": "OK",
                "projection": projection.safe_dict(),
                "content_ingested": False,
                "raw_credentials_present": False,
            }
        )

    async def read_file_content(arguments: dict[str, Any]) -> Any:
        file_id = _string_arg(dict(arguments), "fileId")
        if not file_id:
            raise DriveContractError("A Drive file id is needed to read a file.")
        encoded = quote(file_id, safe="")
        metadata = await _port_json(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path=f"/files/{encoded}",
            query={"fields": CONTENT_METADATA_FIELDS, "supportsAllDrives": "true"},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        classification = classify_drive_resource(metadata)
        if classification is DriveResourceClassification.TRASHED_FAIL_CLOSED:
            raise DriveContractError("Drive resource is trashed and is not readable")
        if classification is DriveResourceClassification.SHORTCUT_TARGET_REQUIRED:
            raise DriveContractError(
                "Drive shortcut targets require independently authorized resolution."
            )
        if classification is DriveResourceClassification.BINARY_NOT_INGESTED:
            raise DriveContractError(
                "Drive resource is not a text-readable file and its content is not ingested."
            )
        mime = metadata.get("mimeType") if isinstance(metadata.get("mimeType"), str) else None
        export_as = export_mime_for(mime)
        if export_as is not None:
            text = await _port_text(
                port,
                binding_ref=binding_ref,
                actor_ref=actor_ref,
                path=f"/files/{encoded}/export",
                query={"mimeType": export_as},
                max_response_bytes=MAX_PROVIDER_CONTENT_BYTES,
            )
            operation = "files.export"
        else:
            text = await _port_text(
                port,
                binding_ref=binding_ref,
                actor_ref=actor_ref,
                path=f"/files/{encoded}",
                query={"alt": "media"},
                max_response_bytes=MAX_PROVIDER_CONTENT_BYTES,
            )
            operation = "files.get.media"
        content, truncated = _bounded_content(text)
        projection = project_drive_file(metadata)
        return _bounded_envelope(
            {
                "provider": "google_drive",
                "operation": operation,
                "result_status": "REVIEW_REQUIRED" if truncated else "OK",
                "projection": projection.safe_dict(),
                "resource_classification": classification.value,
                "export_mime_type": export_as,
                "content": content,
                "content_truncated": truncated,
                "content_chars": len(content),
                "drive_content_trusted": False,
                "raw_credentials_present": False,
            }
        )

    return {
        DRIVE_SEARCH_FILES_TOOL_ID: search_files,
        DRIVE_LIST_RECENT_FILES_TOOL_ID: list_recent_files,
        DRIVE_GET_FILE_METADATA_TOOL_ID: get_file_metadata,
        DRIVE_READ_FILE_CONTENT_TOOL_ID: read_file_content,
    }


def register_drive_read_tools(
    runtime: ToolRuntime,
    port: DriveReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
) -> tuple[str, ...]:
    """Register the readonly Drive tools on a ToolRuntime and return their ids."""

    handlers = build_drive_read_handlers(port, binding_ref=binding_ref, actor_ref=actor_ref)
    registered: list[str] = []
    for spec in drive_read_tool_specs():
        runtime.register(spec, handlers[spec.id])
        registered.append(spec.id)
    return tuple(registered)


__all__ = [
    "DRIVE_BASE_URL",
    "DRIVE_BINARY_AUTO_INGEST",
    "DRIVE_CANONICAL_TOOL_IDS",
    "DRIVE_CONNECTOR_ID",
    "DRIVE_DESCRIPTOR",
    "DRIVE_FULL_AUTH_SCOPE",
    "DRIVE_FULL_SCOPE",
    "DRIVE_GET_FILE_METADATA_TOOL_ID",
    "DRIVE_LIST_RECENT_FILES_TOOL_ID",
    "DRIVE_LIVE_PROVIDER_CALLS",
    "DRIVE_OAUTH_FLOW_IMPLEMENTED",
    "DRIVE_RAW_CREDENTIAL_IN_CORE",
    "DRIVE_READ_FILE_CONTENT_TOOL_ID",
    "DRIVE_READONLY_AUTH_SCOPE",
    "DRIVE_READONLY_SCOPE",
    "DRIVE_READ_TOOL_IDS",
    "DRIVE_SEARCH_FILES_TOOL_ID",
    "DRIVE_SHARED_DRIVE_IDENTITY_PRESERVED",
    "DRIVE_SHORTCUT_AUTO_ESCAPE",
    "DRIVE_TRASHED_RESOURCE_READABLE",
    "DRIVE_VERSION_EVIDENCE_PRESERVED",
    "DRIVE_WRITE_TOOLS_PRESENT",
    "DriveCapability",
    "DriveCapabilityClassification",
    "DriveCapabilityGrant",
    "DriveContractError",
    "DriveFileProjection",
    "DriveReadPort",
    "DriveResourceClassification",
    "build_drive_read_handlers",
    "capability_requires_p01_approval",
    "classify_drive_resource",
    "classify_drive_tool_id",
    "core_auth_scopes_for_capability",
    "drive_capability_snapshot",
    "drive_read_tool_specs",
    "drive_search_query",
    "export_mime_for",
    "is_textual_mime",
    "project_drive_file",
    "provider_scopes_for_capability",
    "register_drive_read_tools",
]
