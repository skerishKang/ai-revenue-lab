from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from .contracts import ContractError
from .security import redact_secrets

MAX_ONEDRIVE_RESOURCES = 512
MAX_ONEDRIVE_FILE_BYTES = 50 * 1024 * 1024
MAX_ONEDRIVE_PATH_CHARS = 4096
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
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


def _sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip().lower()):
        raise ContractError(f"{field_name} must be lowercase SHA-256")
    return value.strip().lower()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _nonnegative_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{field_name} must be a non-negative integer")
    return value


def _etag_hash(etag: str) -> str:
    if not isinstance(etag, str) or not etag.strip():
        raise ContractError("etag must be non-empty text")
    normalized = redact_secrets(etag.strip())
    if len(normalized) > 1024:
        raise ContractError("etag exceeds bound")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class OneDriveKind(str, Enum):
    PERSONAL = "personal"
    BUSINESS = "business"
    SHAREPOINT = "sharepoint"


class OneDrivePermissionMode(str, Enum):
    APP_FOLDER_PERSONAL = "app_folder_personal"
    SELECTED_RESOURCE = "selected_resource"
    DELEGATED_FILES = "delegated_files"
    BROAD = "broad"


class OneDriveResourceKind(str, Enum):
    FILE = "file"
    FOLDER = "folder"


@dataclass(frozen=True, slots=True)
class OneDriveResourceRef:
    drive_ref: str
    item_ref: str
    kind: OneDriveResourceKind

    def __post_init__(self) -> None:
        object.__setattr__(self, "drive_ref", _safe_ref(self.drive_ref, "drive_ref"))
        object.__setattr__(self, "item_ref", _safe_ref(self.item_ref, "item_ref"))
        if not isinstance(self.kind, OneDriveResourceKind):
            try:
                object.__setattr__(self, "kind", OneDriveResourceKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid OneDrive resource kind") from exc

    @property
    def key(self) -> str:
        return f"{self.drive_ref}:{self.kind.value}:{self.item_ref}"


@dataclass(frozen=True, slots=True)
class OneDriveScopeProjection:
    binding_ref: str
    workspace_ref: str
    account_ref: str
    kind: OneDriveKind
    drive_ref: str
    permission_mode: OneDrivePermissionMode
    allowed_resources: tuple[OneDriveResourceRef, ...]
    tenant_ref: str | None = None
    site_ref: str | None = None

    def __post_init__(self) -> None:
        for name in ("binding_ref", "workspace_ref", "account_ref", "drive_ref"):
            object.__setattr__(self, name, _safe_ref(getattr(self, name), name))
        if not isinstance(self.kind, OneDriveKind):
            try:
                object.__setattr__(self, "kind", OneDriveKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid OneDrive kind") from exc
        if not isinstance(self.permission_mode, OneDrivePermissionMode):
            try:
                object.__setattr__(self, "permission_mode", OneDrivePermissionMode(self.permission_mode))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid OneDrive permission mode") from exc
        object.__setattr__(self, "tenant_ref", _optional_ref(self.tenant_ref, "tenant_ref"))
        object.__setattr__(self, "site_ref", _optional_ref(self.site_ref, "site_ref"))
        if self.kind in {OneDriveKind.BUSINESS, OneDriveKind.SHAREPOINT} and self.tenant_ref is None:
            raise ContractError("business/SharePoint OneDrive requires tenant_ref")
        if self.kind is OneDriveKind.SHAREPOINT and self.site_ref is None:
            raise ContractError("SharePoint drive requires site_ref")
        if self.kind is OneDriveKind.PERSONAL and self.site_ref is not None:
            raise ContractError("personal OneDrive cannot claim SharePoint site_ref")
        if self.permission_mode is OneDrivePermissionMode.APP_FOLDER_PERSONAL and self.kind is not OneDriveKind.PERSONAL:
            raise ContractError("App Folder permission mode is personal-OneDrive only")
        if not self.allowed_resources or len(self.allowed_resources) > MAX_ONEDRIVE_RESOURCES:
            raise ContractError("OneDrive scope requires 1..512 explicit resources")
        if any(not isinstance(item, OneDriveResourceRef) for item in self.allowed_resources):
            raise ContractError("allowed_resources must contain OneDriveResourceRef")
        if any(item.drive_ref != self.drive_ref for item in self.allowed_resources):
            raise ContractError("OneDrive scope cannot mix drive identities")
        keys = tuple(item.key for item in self.allowed_resources)
        if len(keys) != len(set(keys)):
            raise ContractError("OneDrive allowed resources must be unique")

    def allows(self, resource: OneDriveResourceRef) -> bool:
        if not isinstance(resource, OneDriveResourceRef):
            raise ContractError("resource must be OneDriveResourceRef")
        return resource.key in {item.key for item in self.allowed_resources}

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-onedrive-scope.v1",
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "account_ref": self.account_ref,
            "kind": self.kind.value,
            "drive_ref": self.drive_ref,
            "tenant_ref": self.tenant_ref,
            "site_ref": self.site_ref,
            "permission_mode": self.permission_mode.value,
            "allowed_resources": [item.key for item in self.allowed_resources],
            "whole_tenant_model_visibility": False,
            "path_is_authority": False,
        }


@dataclass(frozen=True, slots=True)
class OneDriveItemProjection:
    binding_ref: str
    workspace_ref: str
    resource: OneDriveResourceRef
    name: str
    display_path: str
    size_bytes: int
    etag: str
    ctag: str | None = None
    modified_at: datetime | None = None
    deleted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "workspace_ref", _safe_ref(self.workspace_ref, "workspace_ref"))
        if not isinstance(self.resource, OneDriveResourceRef):
            raise ContractError("resource must be OneDriveResourceRef")
        object.__setattr__(self, "name", _bounded_text(self.name, "name", 512))
        object.__setattr__(self, "display_path", _bounded_text(self.display_path, "display_path", MAX_ONEDRIVE_PATH_CHARS))
        _nonnegative_int(self.size_bytes, "size_bytes")
        if self.size_bytes > MAX_ONEDRIVE_FILE_BYTES:
            raise ContractError("OneDrive item exceeds Padiem file bound")
        if not isinstance(self.etag, str) or not self.etag.strip() or len(self.etag.strip()) > 1024:
            raise ContractError("OneDrive item requires bounded eTag")
        object.__setattr__(self, "etag", redact_secrets(self.etag.strip()))
        if self.ctag is not None:
            if not isinstance(self.ctag, str) or not self.ctag.strip() or len(self.ctag.strip()) > 1024:
                raise ContractError("cTag must be bounded text")
            object.__setattr__(self, "ctag", redact_secrets(self.ctag.strip()))
        if self.modified_at is not None:
            object.__setattr__(self, "modified_at", _aware(self.modified_at, "modified_at"))
        if not isinstance(self.deleted, bool):
            raise ContractError("deleted must be bool")

    @property
    def etag_sha256(self) -> str:
        return _etag_hash(self.etag)

    @property
    def ctag_sha256(self) -> str | None:
        return None if self.ctag is None else _etag_hash(self.ctag)

    @property
    def state_ref(self) -> str:
        encoded = json.dumps(
            {
                "resource": self.resource.key,
                "etag_sha256": self.etag_sha256,
                "ctag_sha256": self.ctag_sha256,
                "modified_at": self.modified_at.isoformat() if self.modified_at else None,
                "deleted": self.deleted,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"onedrive-state:{hashlib.sha256(encoded).hexdigest()}"

    def safe_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource.key,
            "name": self.name,
            "display_path": self.display_path,
            "size_bytes": self.size_bytes,
            "etag_sha256": self.etag_sha256,
            "ctag_sha256": self.ctag_sha256,
            "raw_etag_present": False,
            "raw_ctag_present": False,
            "deleted": self.deleted,
            "content_trusted": False,
        }


class OneDriveConflictBehavior(str, Enum):
    FAIL = "fail"
    REPLACE = "replace"
    RENAME = "rename"


class OneDriveMutationCapability(str, Enum):
    UPLOAD_NEW = "onedrive.upload_new"
    UPDATE_CONTENT = "onedrive.update_content"
    MOVE = "onedrive.move"
    COPY = "onedrive.copy"
    DELETE = "onedrive.delete"


@dataclass(frozen=True, slots=True)
class OneDriveMutationMaterial:
    binding_ref: str
    workspace_ref: str
    capability: OneDriveMutationCapability
    source: OneDriveResourceRef | None
    target_parent: OneDriveResourceRef | None
    target_name: str
    payload_sha256: str
    expected_etag_sha256: str | None = None
    conflict_behavior: OneDriveConflictBehavior = OneDriveConflictBehavior.FAIL
    resumable_upload: bool = False
    defer_commit: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "workspace_ref", _safe_ref(self.workspace_ref, "workspace_ref"))
        if not isinstance(self.capability, OneDriveMutationCapability):
            try:
                object.__setattr__(self, "capability", OneDriveMutationCapability(self.capability))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid OneDrive mutation capability") from exc
        if self.source is not None and not isinstance(self.source, OneDriveResourceRef):
            raise ContractError("source must be OneDriveResourceRef")
        if self.target_parent is not None:
            if not isinstance(self.target_parent, OneDriveResourceRef) or self.target_parent.kind is not OneDriveResourceKind.FOLDER:
                raise ContractError("target_parent must be OneDrive folder")
        object.__setattr__(self, "target_name", _bounded_text(self.target_name, "target_name", 512))
        object.__setattr__(self, "payload_sha256", _sha256(self.payload_sha256, "payload_sha256"))
        if self.expected_etag_sha256 is not None:
            object.__setattr__(self, "expected_etag_sha256", _sha256(self.expected_etag_sha256, "expected_etag_sha256"))
        if not isinstance(self.conflict_behavior, OneDriveConflictBehavior):
            try:
                object.__setattr__(self, "conflict_behavior", OneDriveConflictBehavior(self.conflict_behavior))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid OneDrive conflict behavior") from exc
        if not isinstance(self.resumable_upload, bool) or not isinstance(self.defer_commit, bool):
            raise ContractError("resumable_upload/defer_commit must be bool")
        if self.conflict_behavior is not OneDriveConflictBehavior.FAIL:
            raise ContractError("initial Padiem OneDrive contract only permits conflictBehavior=fail")
        if self.defer_commit and not self.resumable_upload:
            raise ContractError("defer_commit requires resumable upload")

        existing_caps = {OneDriveMutationCapability.UPDATE_CONTENT, OneDriveMutationCapability.MOVE, OneDriveMutationCapability.DELETE}
        if self.capability in existing_caps:
            if self.source is None or self.expected_etag_sha256 is None:
                raise ContractError("existing-resource mutation requires exact source and expected eTag hash")
        if self.capability is OneDriveMutationCapability.UPLOAD_NEW:
            if self.source is not None or self.target_parent is None or not self.target_name or self.expected_etag_sha256 is not None:
                raise ContractError("upload_new requires exact destination parent/name and no existing source/eTag")
        elif self.capability is OneDriveMutationCapability.UPDATE_CONTENT:
            if self.source is None or self.source.kind is not OneDriveResourceKind.FILE or self.target_parent is not None or self.target_name:
                raise ContractError("update_content requires exact existing file only")
        elif self.capability is OneDriveMutationCapability.MOVE:
            if self.source is None or self.target_parent is None or not self.target_name:
                raise ContractError("move requires source and destination parent/name")
        elif self.capability is OneDriveMutationCapability.COPY:
            if self.source is None or self.target_parent is None or not self.target_name or self.expected_etag_sha256 is not None:
                raise ContractError("copy requires source/destination but no existing target eTag")
        elif self.capability is OneDriveMutationCapability.DELETE:
            if self.source is None or self.target_parent is not None or self.target_name:
                raise ContractError("delete requires exact source only")

        if self.source is not None and self.target_parent is not None and self.source.drive_ref != self.target_parent.drive_ref:
            raise ContractError("cross-drive OneDrive mutation is not supported by this initial contract")

    @property
    def drive_ref(self) -> str:
        if self.source is not None:
            return self.source.drive_ref
        assert self.target_parent is not None
        return self.target_parent.drive_ref

    @property
    def target_ref(self) -> str:
        if self.capability in {OneDriveMutationCapability.UPDATE_CONTENT, OneDriveMutationCapability.DELETE}:
            assert self.source is not None
            return f"onedrive:{self.source.key}"
        assert self.target_parent is not None
        name_hash = hashlib.sha256(self.target_name.encode("utf-8")).hexdigest()
        return f"onedrive:{self.target_parent.key}:child-name-sha256:{name_hash}"

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "capability": self.capability.value,
            "source": self.source.key if self.source else None,
            "target_parent": self.target_parent.key if self.target_parent else None,
            "target_name": self.target_name,
            "payload_sha256": self.payload_sha256,
            "expected_etag_sha256": self.expected_etag_sha256,
            "conflict_behavior": self.conflict_behavior.value,
            "resumable_upload": self.resumable_upload,
            "defer_commit": self.defer_commit,
            "silent_replace_or_rename": False,
        }

    @property
    def material_fingerprint(self) -> str:
        encoded = json.dumps(self.canonical_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def version_ref(self) -> str:
        return (
            f"onedrive-etag:{self.expected_etag_sha256}"
            if self.expected_etag_sha256 is not None
            else f"onedrive-material:{self.material_fingerprint}"
        )


@dataclass(frozen=True, slots=True)
class OneDriveUploadSessionProjection:
    session_ref: str
    binding_ref: str
    workspace_ref: str
    target_ref: str
    expires_at: datetime
    defer_commit: bool

    def __post_init__(self) -> None:
        for name in ("session_ref", "binding_ref", "workspace_ref", "target_ref"):
            object.__setattr__(self, name, _safe_ref(getattr(self, name), name))
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))
        if not isinstance(self.defer_commit, bool):
            raise ContractError("defer_commit must be bool")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "session_ref": self.session_ref,
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "target_ref": self.target_ref,
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "defer_commit": self.defer_commit,
            "raw_upload_url_present": False,
        }


@dataclass(frozen=True, slots=True)
class OneDriveMutationApproval:
    approval_ref: str
    evidence_ref: str
    material_fingerprint: str
    approved_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_ref", _safe_ref(self.approval_ref, "approval_ref"))
        object.__setattr__(self, "evidence_ref", _safe_ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "material_fingerprint", _sha256(self.material_fingerprint, "material_fingerprint"))
        object.__setattr__(self, "approved_at", _aware(self.approved_at, "approved_at"))


class OneDriveMutationPreflightDecision(str, Enum):
    ALLOW = "allow"
    OUT_OF_SCOPE = "out_of_scope"
    WRONG_CONNECTOR_OR_TOOL = "wrong_connector_or_tool"
    TARGET_MISMATCH = "target_mismatch"
    APPROVAL_MISMATCH = "approval_mismatch"
    MATERIAL_CHANGED = "material_changed"
    STALE_ETAG = "stale_etag"
    VERSION_BINDING_MISMATCH = "version_binding_mismatch"


def onedrive_mutation_preflight(
    *,
    scope: OneDriveScopeProjection,
    material: OneDriveMutationMaterial,
    approval: OneDriveMutationApproval,
    intent: ConnectorWriteIntent,
    current_source: OneDriveItemProjection | None = None,
) -> OneDriveMutationPreflightDecision:
    if not all((isinstance(scope, OneDriveScopeProjection), isinstance(material, OneDriveMutationMaterial), isinstance(approval, OneDriveMutationApproval), isinstance(intent, ConnectorWriteIntent))):
        raise ContractError("invalid OneDrive mutation preflight contract")
    if material.binding_ref != scope.binding_ref or material.workspace_ref != scope.workspace_ref or material.drive_ref != scope.drive_ref:
        return OneDriveMutationPreflightDecision.OUT_OF_SCOPE
    if material.source is not None and not scope.allows(material.source):
        return OneDriveMutationPreflightDecision.OUT_OF_SCOPE
    if material.target_parent is not None and not scope.allows(material.target_parent):
        return OneDriveMutationPreflightDecision.OUT_OF_SCOPE
    if intent.connector_id != "onedrive" or intent.tool_name != material.capability.value:
        return OneDriveMutationPreflightDecision.WRONG_CONNECTOR_OR_TOOL
    if intent.binding_ref != material.binding_ref or intent.target_ref != material.target_ref:
        return OneDriveMutationPreflightDecision.TARGET_MISMATCH
    if intent.approval_ref != approval.approval_ref or intent.evidence_ref != approval.evidence_ref:
        return OneDriveMutationPreflightDecision.APPROVAL_MISMATCH
    if approval.material_fingerprint != material.material_fingerprint or intent.payload_fingerprint != material.material_fingerprint:
        return OneDriveMutationPreflightDecision.MATERIAL_CHANGED
    if intent.expected_version_ref != material.version_ref:
        return OneDriveMutationPreflightDecision.VERSION_BINDING_MISMATCH
    if material.expected_etag_sha256 is not None:
        if current_source is None or material.source is None:
            return OneDriveMutationPreflightDecision.STALE_ETAG
        if (
            current_source.binding_ref != material.binding_ref
            or current_source.workspace_ref != material.workspace_ref
            or current_source.resource.key != material.source.key
            or current_source.deleted
            or current_source.etag_sha256 != material.expected_etag_sha256
        ):
            return OneDriveMutationPreflightDecision.STALE_ETAG
    return OneDriveMutationPreflightDecision.ALLOW


@dataclass(frozen=True, slots=True)
class OneDriveMutationReceipt:
    connector_receipt: ConnectorWriteReceipt
    capability: OneDriveMutationCapability
    approved_target_ref: str
    result_resource: OneDriveResourceRef | None
    result_etag_sha256: str | None
    result_ctag_sha256: str | None = None
    upload_committed: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.connector_receipt, ConnectorWriteReceipt) or self.connector_receipt.connector_id != "onedrive":
            raise ContractError("OneDrive receipt requires onedrive ConnectorWriteReceipt")
        if not isinstance(self.capability, OneDriveMutationCapability):
            try:
                object.__setattr__(self, "capability", OneDriveMutationCapability(self.capability))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid OneDrive receipt capability") from exc
        object.__setattr__(self, "approved_target_ref", _safe_ref(self.approved_target_ref, "approved_target_ref"))
        if self.connector_receipt.target_ref != self.approved_target_ref:
            raise ContractError("OneDrive receipt target does not match approved target")
        if self.result_resource is not None and not isinstance(self.result_resource, OneDriveResourceRef):
            raise ContractError("result_resource must be OneDriveResourceRef")
        if self.result_etag_sha256 is not None:
            object.__setattr__(self, "result_etag_sha256", _sha256(self.result_etag_sha256, "result_etag_sha256"))
        if self.result_ctag_sha256 is not None:
            object.__setattr__(self, "result_ctag_sha256", _sha256(self.result_ctag_sha256, "result_ctag_sha256"))
        if not isinstance(self.upload_committed, bool):
            raise ContractError("upload_committed must be bool")
        if self.capability is OneDriveMutationCapability.DELETE:
            if self.result_etag_sha256 is not None or self.result_ctag_sha256 is not None:
                raise ContractError("delete receipt cannot claim live item tags")
        elif self.result_resource is None:
            raise ContractError("non-delete OneDrive receipt requires result resource")


MICROSOFT_GRAPH_REQUIRED = True
ONEDRIVE_PERSONAL_BUSINESS_SHAREPOINT_DISTINCT = True
ONEDRIVE_SELECTED_RESOURCE_SCOPE_PREFERRED = True
ONEDRIVE_LEGACY_FILES_READWRITE_SELECTED_FOR_DIRECT_GRAPH = False
ONEDRIVE_APP_FOLDER_PERSONAL_NARROW_MODE = True
ONEDRIVE_WHOLE_TENANT_MODEL_VISIBILITY = False
ONEDRIVE_PATH_IS_AUTHORITY = False
ONEDRIVE_IF_MATCH_ETAG_REQUIRED_FOR_EXISTING_MUTATIONS = True
ONEDRIVE_NEW_UPLOAD_CONFLICT_DEFAULT = "fail"
ONEDRIVE_RAW_UPLOAD_SESSION_URL_IN_B54 = False
ONEDRIVE_RAW_OAUTH_TOKEN_IN_B54 = False
REAL_MICROSOFT_OAUTH_CONFIGURED = False
REAL_ONEDRIVE_MUTATION_CONFIGURED = False
