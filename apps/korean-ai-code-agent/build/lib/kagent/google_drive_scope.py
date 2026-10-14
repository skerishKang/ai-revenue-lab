from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
from typing import Any

from .connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from .contracts import ContractError
from .security import redact_secrets

GOOGLE_SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_CHECKSUM_RE = re.compile(r"^[0-9a-fA-F]{16,128}$")


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
    if value is None:
        return None
    return _safe_ref(value, field_name)


def _refs(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_safe_ref(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ContractError(f"{field_name} values must be unique")
    return normalized


def _optional_checksum(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _CHECKSUM_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a hexadecimal checksum")
    return value.strip().lower()


def _version(value: int | str | None, field_name: str, *, required: bool = True) -> int | None:
    if value is None:
        if required:
            raise ContractError(f"{field_name} is required")
        return None
    if isinstance(value, bool):
        raise ContractError(f"{field_name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field_name} must be a positive integer") from exc
    if parsed < 1:
        raise ContractError(f"{field_name} must be a positive integer")
    return parsed


def _timestamp(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field_name} must be an RFC3339 timestamp")
    normalized = value.strip()
    candidate = normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ContractError(f"{field_name} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"{field_name} must include timezone information")
    return normalized


class DriveSpaceKind(str, Enum):
    MY_DRIVE = "my_drive"
    SHARED_DRIVE = "shared_drive"


@dataclass(frozen=True, slots=True)
class DriveScopeProjection:
    binding_ref: str
    allow_my_drive_root: bool = False
    allowed_shared_drive_ids: tuple[str, ...] = ()
    allowed_file_ids: tuple[str, ...] = ()
    allowed_folder_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        if not isinstance(self.allow_my_drive_root, bool):
            raise ContractError("allow_my_drive_root must be boolean")
        object.__setattr__(
            self,
            "allowed_shared_drive_ids",
            _refs(self.allowed_shared_drive_ids, "shared_drive_id"),
        )
        object.__setattr__(self, "allowed_file_ids", _refs(self.allowed_file_ids, "file_id"))
        object.__setattr__(self, "allowed_folder_ids", _refs(self.allowed_folder_ids, "folder_id"))
        if not (
            self.allow_my_drive_root
            or self.allowed_shared_drive_ids
            or self.allowed_file_ids
            or self.allowed_folder_ids
        ):
            raise ContractError("Drive scope must explicitly authorize at least one resource boundary")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-google-drive-scope.v1",
            "binding_ref": self.binding_ref,
            "allow_my_drive_root": self.allow_my_drive_root,
            "allowed_shared_drive_ids": list(self.allowed_shared_drive_ids),
            "allowed_file_ids": list(self.allowed_file_ids),
            "allowed_folder_ids": list(self.allowed_folder_ids),
            "all_drives_default": False,
            "shortcut_inherits_parent_scope": False,
        }


@dataclass(frozen=True, slots=True)
class DriveShortcutDetails:
    target_id: str
    target_mime_type: str | None = None
    target_resource_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", _safe_ref(self.target_id, "shortcut_target_id"))
        if self.target_mime_type is not None:
            if not isinstance(self.target_mime_type, str) or not self.target_mime_type.strip():
                raise ContractError("target_mime_type must be a non-empty string")
            object.__setattr__(self, "target_mime_type", self.target_mime_type.strip())
        object.__setattr__(
            self,
            "target_resource_key",
            _optional_ref(self.target_resource_key, "shortcut_target_resource_key"),
        )


@dataclass(frozen=True, slots=True)
class DriveFileMetadata:
    file_id: str
    name: str
    mime_type: str
    version: int
    parents: tuple[str, ...] = ()
    drive_id: str | None = None
    trashed: bool = False
    modified_time: str | None = None
    md5_checksum: str | None = None
    sha256_checksum: str | None = None
    head_revision_id: str | None = None
    resource_key: str | None = None
    shortcut: DriveShortcutDetails | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_id", _safe_ref(self.file_id, "file_id"))
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name.strip()) > 1_024:
            raise ContractError("Drive file name must be bounded and non-empty")
        object.__setattr__(self, "name", redact_secrets(self.name.strip()))
        if not isinstance(self.mime_type, str) or not self.mime_type.strip() or len(self.mime_type) > 255:
            raise ContractError("Drive mime_type must be bounded and non-empty")
        object.__setattr__(self, "mime_type", self.mime_type.strip())
        object.__setattr__(self, "version", _version(self.version, "version"))
        object.__setattr__(self, "parents", _refs(self.parents, "parent_id"))
        object.__setattr__(self, "drive_id", _optional_ref(self.drive_id, "drive_id"))
        if not isinstance(self.trashed, bool):
            raise ContractError("trashed must be boolean")
        object.__setattr__(self, "modified_time", _timestamp(self.modified_time, "modified_time"))
        object.__setattr__(
            self,
            "md5_checksum",
            _optional_checksum(self.md5_checksum, "md5_checksum"),
        )
        object.__setattr__(
            self,
            "sha256_checksum",
            _optional_checksum(self.sha256_checksum, "sha256_checksum"),
        )
        object.__setattr__(self, "head_revision_id", _optional_ref(self.head_revision_id, "head_revision_id"))
        object.__setattr__(self, "resource_key", _optional_ref(self.resource_key, "resource_key"))
        if self.shortcut is not None and not isinstance(self.shortcut, DriveShortcutDetails):
            raise ContractError("shortcut must be DriveShortcutDetails")
        if self.mime_type == GOOGLE_SHORTCUT_MIME and self.shortcut is None:
            raise ContractError("Google shortcut metadata requires shortcut details")
        if self.mime_type != GOOGLE_SHORTCUT_MIME and self.shortcut is not None:
            raise ContractError("shortcut details require Google shortcut mime type")

    @property
    def space_kind(self) -> DriveSpaceKind:
        return DriveSpaceKind.SHARED_DRIVE if self.drive_id is not None else DriveSpaceKind.MY_DRIVE

    @property
    def is_shortcut(self) -> bool:
        return self.shortcut is not None

    @classmethod
    def from_provider(cls, value: dict[str, Any]) -> "DriveFileMetadata":
        if not isinstance(value, dict):
            raise ContractError("Drive provider metadata must be an object")
        details = value.get("shortcutDetails")
        shortcut = None
        if details is not None:
            if not isinstance(details, dict):
                raise ContractError("shortcutDetails must be an object")
            shortcut = DriveShortcutDetails(
                target_id=details.get("targetId"),
                target_mime_type=details.get("targetMimeType"),
                target_resource_key=details.get("targetResourceKey"),
            )
        parents = value.get("parents") or []
        if not isinstance(parents, list):
            raise ContractError("Drive parents must be a list")
        return cls(
            file_id=value.get("id"),
            name=value.get("name") or "(untitled)",
            mime_type=value.get("mimeType"),
            version=value.get("version"),
            parents=tuple(parents),
            drive_id=value.get("driveId"),
            trashed=bool(value.get("trashed", False)),
            modified_time=value.get("modifiedTime"),
            md5_checksum=value.get("md5Checksum"),
            sha256_checksum=value.get("sha256Checksum"),
            head_revision_id=value.get("headRevisionId"),
            resource_key=value.get("resourceKey"),
            shortcut=shortcut,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "name": self.name,
            "mime_type": self.mime_type,
            "version": self.version,
            "parents": list(self.parents),
            "drive_id": self.drive_id,
            "space_kind": self.space_kind.value,
            "trashed": self.trashed,
            "modified_time": self.modified_time,
            "md5_checksum": self.md5_checksum,
            "sha256_checksum": self.sha256_checksum,
            "head_revision_id": self.head_revision_id,
            "resource_key": self.resource_key,
            "shortcut": (
                {
                    "target_id": self.shortcut.target_id,
                    "target_mime_type": self.shortcut.target_mime_type,
                    "target_resource_key": self.shortcut.target_resource_key,
                }
                if self.shortcut
                else None
            ),
            "content_trusted": False,
        }


@dataclass(frozen=True, slots=True)
class DriveResourceProof:
    binding_ref: str
    metadata: DriveFileMetadata
    ancestor_folder_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        if not isinstance(self.metadata, DriveFileMetadata):
            raise ContractError("metadata must be DriveFileMetadata")
        object.__setattr__(
            self,
            "ancestor_folder_ids",
            _refs(self.ancestor_folder_ids, "ancestor_folder_id"),
        )


class DriveScopeDecision(str, Enum):
    ALLOW = "allow"
    BINDING_MISMATCH = "binding_mismatch"
    TRASHED = "trashed"
    OUT_OF_SCOPE = "out_of_scope"
    SHORTCUT_TARGET_REQUIRED = "shortcut_target_required"
    SHORTCUT_TARGET_MISMATCH = "shortcut_target_mismatch"


def authorize_drive_resource(scope: DriveScopeProjection, proof: DriveResourceProof) -> DriveScopeDecision:
    if not isinstance(scope, DriveScopeProjection) or not isinstance(proof, DriveResourceProof):
        raise ContractError("scope/proof types are invalid")
    if scope.binding_ref != proof.binding_ref:
        return DriveScopeDecision.BINDING_MISMATCH
    metadata = proof.metadata
    if metadata.trashed:
        return DriveScopeDecision.TRASHED
    exact_file = metadata.file_id in scope.allowed_file_ids
    exact_folder = metadata.file_id in scope.allowed_folder_ids
    allowed_folder_ancestor = bool(set(proof.ancestor_folder_ids) & set(scope.allowed_folder_ids))
    broad_location = (
        (metadata.drive_id is None and scope.allow_my_drive_root)
        or (metadata.drive_id is not None and metadata.drive_id in scope.allowed_shared_drive_ids)
    )
    if not (exact_file or exact_folder or allowed_folder_ancestor or broad_location):
        return DriveScopeDecision.OUT_OF_SCOPE
    if metadata.is_shortcut:
        return DriveScopeDecision.SHORTCUT_TARGET_REQUIRED
    return DriveScopeDecision.ALLOW


def authorize_drive_shortcut(
    scope: DriveScopeProjection,
    shortcut_proof: DriveResourceProof,
    target_proof: DriveResourceProof,
) -> DriveScopeDecision:
    shortcut_decision = authorize_drive_resource(scope, shortcut_proof)
    if shortcut_decision is not DriveScopeDecision.SHORTCUT_TARGET_REQUIRED:
        return shortcut_decision
    shortcut = shortcut_proof.metadata.shortcut
    if shortcut is None or target_proof.metadata.file_id != shortcut.target_id:
        return DriveScopeDecision.SHORTCUT_TARGET_MISMATCH
    # Deliberately re-authorize the target from its own location/ancestor proof.
    # A shortcut's folder or shared-drive location never grants access to its target.
    return authorize_drive_resource(scope, target_proof)


def shared_drive_list_query(
    scope: DriveScopeProjection,
    *,
    drive_id: str,
    q: str | None = None,
    page_size: int = 25,
) -> dict[str, str]:
    if not isinstance(scope, DriveScopeProjection):
        raise ContractError("scope must be DriveScopeProjection")
    drive_id = _safe_ref(drive_id, "drive_id")
    if drive_id not in scope.allowed_shared_drive_ids:
        raise ContractError("shared drive is not explicitly allowed")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise ContractError("page_size must be between 1 and 100")
    query = "trashed = false"
    if q is not None:
        if not isinstance(q, str) or not q.strip() or len(q.strip()) > 2_000:
            raise ContractError("Drive q must be bounded and non-empty")
        query = f"({q.strip()}) and trashed = false"
    return {
        "corpora": "drive",
        "driveId": drive_id,
        "includeItemsFromAllDrives": "true",
        "supportsAllDrives": "true",
        "pageSize": str(page_size),
        "q": query,
    }


def shared_drive_operation_query(*, resource_key: str | None = None) -> dict[str, str]:
    params = {"supportsAllDrives": "true"}
    if resource_key is not None:
        params["resourceKey"] = _safe_ref(resource_key, "resource_key")
    return params


@dataclass(frozen=True, slots=True)
class DriveWritePrecondition:
    file_id: str
    expected_version: int
    expected_modified_time: str | None = None
    expected_md5_checksum: str | None = None
    expected_sha256_checksum: str | None = None
    expected_head_revision_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_id", _safe_ref(self.file_id, "file_id"))
        object.__setattr__(self, "expected_version", _version(self.expected_version, "expected_version"))
        object.__setattr__(
            self,
            "expected_modified_time",
            _timestamp(self.expected_modified_time, "expected_modified_time"),
        )
        object.__setattr__(
            self,
            "expected_md5_checksum",
            _optional_checksum(self.expected_md5_checksum, "expected_md5_checksum"),
        )
        object.__setattr__(
            self,
            "expected_sha256_checksum",
            _optional_checksum(self.expected_sha256_checksum, "expected_sha256_checksum"),
        )
        object.__setattr__(
            self,
            "expected_head_revision_id",
            _optional_ref(self.expected_head_revision_id, "expected_head_revision_id"),
        )

    @property
    def version_ref(self) -> str:
        return f"drive-version:{self.expected_version}"

    def matches(self, metadata: DriveFileMetadata) -> bool:
        if not isinstance(metadata, DriveFileMetadata) or metadata.file_id != self.file_id:
            return False
        if metadata.version != self.expected_version:
            return False
        checks = (
            (self.expected_modified_time, metadata.modified_time),
            (self.expected_md5_checksum, metadata.md5_checksum),
            (self.expected_sha256_checksum, metadata.sha256_checksum),
            (self.expected_head_revision_id, metadata.head_revision_id),
        )
        return all(expected is None or expected == actual for expected, actual in checks)


class DriveWritePreflightDecision(str, Enum):
    ALLOW = "allow"
    INTENT_TARGET_MISMATCH = "intent_target_mismatch"
    OUT_OF_SCOPE = "out_of_scope"
    TRASHED = "trashed"
    SHORTCUT_TARGET_REQUIRED = "shortcut_target_required"
    STALE = "stale"


def drive_write_preflight(
    *,
    scope: DriveScopeProjection,
    proof: DriveResourceProof,
    intent: ConnectorWriteIntent,
    precondition: DriveWritePrecondition,
) -> DriveWritePreflightDecision:
    if not isinstance(intent, ConnectorWriteIntent):
        raise ContractError("intent must be ConnectorWriteIntent")
    if (
        intent.connector_id != "google-drive"
        or intent.target_ref != precondition.file_id
        or intent.expected_version_ref != precondition.version_ref
    ):
        return DriveWritePreflightDecision.INTENT_TARGET_MISMATCH
    if proof.metadata.file_id != precondition.file_id or proof.binding_ref != intent.binding_ref:
        return DriveWritePreflightDecision.INTENT_TARGET_MISMATCH
    scope_decision = authorize_drive_resource(scope, proof)
    if scope_decision is DriveScopeDecision.TRASHED:
        return DriveWritePreflightDecision.TRASHED
    if scope_decision is DriveScopeDecision.SHORTCUT_TARGET_REQUIRED:
        return DriveWritePreflightDecision.SHORTCUT_TARGET_REQUIRED
    if scope_decision is not DriveScopeDecision.ALLOW:
        return DriveWritePreflightDecision.OUT_OF_SCOPE
    if not precondition.matches(proof.metadata):
        return DriveWritePreflightDecision.STALE
    return DriveWritePreflightDecision.ALLOW


class DriveWritePostcheckDecision(str, Enum):
    VERIFIED = "verified"
    RECEIPT_MISMATCH = "receipt_mismatch"
    TARGET_MISMATCH = "target_mismatch"
    VERSION_NOT_ADVANCED = "version_not_advanced"
    VERSION_RECEIPT_MISMATCH = "version_receipt_mismatch"


def drive_write_postcheck(
    *,
    intent: ConnectorWriteIntent,
    precondition: DriveWritePrecondition,
    receipt: ConnectorWriteReceipt,
    returned_metadata: DriveFileMetadata,
) -> DriveWritePostcheckDecision:
    if not isinstance(receipt, ConnectorWriteReceipt):
        raise ContractError("receipt must be ConnectorWriteReceipt")
    if (
        receipt.connector_id != "google-drive"
        or receipt.binding_ref != intent.binding_ref
        or receipt.idempotency_key != intent.idempotency_key
        or receipt.target_ref != intent.target_ref
    ):
        return DriveWritePostcheckDecision.RECEIPT_MISMATCH
    if returned_metadata.file_id != precondition.file_id or returned_metadata.file_id != intent.target_ref:
        return DriveWritePostcheckDecision.TARGET_MISMATCH
    if returned_metadata.version <= precondition.expected_version:
        return DriveWritePostcheckDecision.VERSION_NOT_ADVANCED
    expected_returned_version_ref = f"drive-version:{returned_metadata.version}"
    if receipt.version_ref != expected_returned_version_ref:
        return DriveWritePostcheckDecision.VERSION_RECEIPT_MISMATCH
    return DriveWritePostcheckDecision.VERIFIED


DRIVE_SCOPE_CONTRACT_READY = True
DRIVE_SHARED_DRIVE_SUPPORT_CONTRACT_READY = True
DRIVE_ATOMIC_VERSION_CAS_SUPPORTED = False
DRIVE_VERSION_PRECHECK_SUPPORTED = True
DRIVE_VERSION_POSTCHECK_SUPPORTED = True
REAL_GOOGLE_DRIVE_OAUTH_CONFIGURED = False
REAL_GOOGLE_DRIVE_WRITE_CONFIGURED = False
