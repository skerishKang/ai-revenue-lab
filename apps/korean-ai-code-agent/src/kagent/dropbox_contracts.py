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

MAX_DROPBOX_RESOURCES = 512
MAX_DROPBOX_DISPLAY_PATH_CHARS = 4096
MAX_DROPBOX_FILE_BYTES = 50 * 1024 * 1024
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _hex64(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _HEX64_RE.fullmatch(value.strip().lower()):
        raise ContractError(f"{field_name} must be a lowercase 64-hex digest")
    return value.strip().lower()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _nonnegative_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{field_name} must be a non-negative integer")
    return value


def _rev_hash(rev: str) -> str:
    return hashlib.sha256(_safe_ref(rev, "rev").encode("utf-8")).hexdigest()


class DropboxAccessModel(str, Enum):
    APP_FOLDER = "app_folder"
    FULL_DROPBOX = "full_dropbox"
    TEAM_SPACE = "team_space"


class DropboxResourceKind(str, Enum):
    FILE = "file"
    FOLDER = "folder"


@dataclass(frozen=True, slots=True)
class DropboxResourceRef:
    namespace_ref: str
    resource_ref: str
    kind: DropboxResourceKind

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace_ref", _safe_ref(self.namespace_ref, "namespace_ref"))
        object.__setattr__(self, "resource_ref", _safe_ref(self.resource_ref, "resource_ref"))
        if not isinstance(self.kind, DropboxResourceKind):
            try:
                object.__setattr__(self, "kind", DropboxResourceKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Dropbox resource kind") from exc

    @property
    def key(self) -> str:
        return f"{self.namespace_ref}:{self.kind.value}:{self.resource_ref}"


@dataclass(frozen=True, slots=True)
class DropboxScopeProjection:
    binding_ref: str
    workspace_ref: str
    account_ref: str
    access_model: DropboxAccessModel
    root_namespace_ref: str
    home_namespace_ref: str
    allowed_resources: tuple[DropboxResourceRef, ...]

    def __post_init__(self) -> None:
        for name in ("binding_ref", "workspace_ref", "account_ref", "root_namespace_ref", "home_namespace_ref"):
            object.__setattr__(self, name, _safe_ref(getattr(self, name), name))
        if not isinstance(self.access_model, DropboxAccessModel):
            try:
                object.__setattr__(self, "access_model", DropboxAccessModel(self.access_model))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Dropbox access model") from exc
        if not self.allowed_resources or len(self.allowed_resources) > MAX_DROPBOX_RESOURCES:
            raise ContractError("Dropbox scope requires 1..512 explicit resources")
        if any(not isinstance(item, DropboxResourceRef) for item in self.allowed_resources):
            raise ContractError("allowed_resources must contain DropboxResourceRef")
        keys = tuple(item.key for item in self.allowed_resources)
        if len(keys) != len(set(keys)):
            raise ContractError("Dropbox allowed resources must be unique")
        if self.access_model is DropboxAccessModel.APP_FOLDER and self.root_namespace_ref != self.home_namespace_ref:
            raise ContractError("App Folder scope must not claim a distinct team-space root")

    def allows(self, resource: DropboxResourceRef) -> bool:
        if not isinstance(resource, DropboxResourceRef):
            raise ContractError("resource must be DropboxResourceRef")
        return resource.key in {item.key for item in self.allowed_resources}

    def allows_namespace(self, namespace_ref: str) -> bool:
        namespace = _safe_ref(namespace_ref, "namespace_ref")
        return namespace in {item.namespace_ref for item in self.allowed_resources}

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-dropbox-scope.v1",
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "account_ref": self.account_ref,
            "access_model": self.access_model.value,
            "root_namespace_ref": self.root_namespace_ref,
            "home_namespace_ref": self.home_namespace_ref,
            "allowed_resources": [item.key for item in self.allowed_resources],
            "whole_account_model_visibility": False,
            "display_path_is_authority": False,
            "whole_tree_sync": False,
        }


@dataclass(frozen=True, slots=True)
class DropboxMetadataProjection:
    binding_ref: str
    workspace_ref: str
    resource: DropboxResourceRef
    display_path: str
    name: str
    size_bytes: int
    rev: str | None = None
    provider_content_hash: str | None = None
    client_modified_at: datetime | None = None
    server_modified_at: datetime | None = None
    deleted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "workspace_ref", _safe_ref(self.workspace_ref, "workspace_ref"))
        if not isinstance(self.resource, DropboxResourceRef):
            raise ContractError("resource must be DropboxResourceRef")
        object.__setattr__(self, "display_path", _bounded_text(self.display_path, "display_path", MAX_DROPBOX_DISPLAY_PATH_CHARS))
        object.__setattr__(self, "name", _bounded_text(self.name, "name", 512))
        _nonnegative_int(self.size_bytes, "size_bytes")
        if self.size_bytes > MAX_DROPBOX_FILE_BYTES:
            raise ContractError("Dropbox metadata exceeds Padiem file bound")
        object.__setattr__(self, "rev", _optional_ref(self.rev, "rev"))
        if self.provider_content_hash is not None:
            object.__setattr__(self, "provider_content_hash", _hex64(self.provider_content_hash, "provider_content_hash"))
        if self.client_modified_at is not None:
            object.__setattr__(self, "client_modified_at", _aware(self.client_modified_at, "client_modified_at"))
        if self.server_modified_at is not None:
            object.__setattr__(self, "server_modified_at", _aware(self.server_modified_at, "server_modified_at"))
        if not isinstance(self.deleted, bool):
            raise ContractError("deleted must be bool")
        if self.resource.kind is DropboxResourceKind.FILE and not self.deleted and self.rev is None:
            raise ContractError("live Dropbox file metadata requires rev")

    @property
    def state_fingerprint(self) -> str:
        encoded = json.dumps(
            {
                "resource": self.resource.key,
                "rev": self.rev,
                "provider_content_hash": self.provider_content_hash,
                "server_modified_at": self.server_modified_at.isoformat() if self.server_modified_at else None,
                "deleted": self.deleted,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def state_ref(self) -> str:
        return f"dropbox-state:{self.state_fingerprint}"

    def safe_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource.key,
            "display_path": self.display_path,
            "name": self.name,
            "size_bytes": self.size_bytes,
            "rev": self.rev,
            "provider_content_hash": self.provider_content_hash,
            "provider_content_hash_algorithm": "dropbox-content-hash",
            "provider_content_hash_is_sha256": False,
            "deleted": self.deleted,
            "content_trusted": False,
        }


class DropboxMutationCapability(str, Enum):
    UPLOAD_ADD = "dropbox.upload_add"
    UPDATE_FILE = "dropbox.update_file"
    COPY = "dropbox.copy"
    MOVE = "dropbox.move"
    DELETE = "dropbox.delete"


@dataclass(frozen=True, slots=True)
class DropboxMutationMaterial:
    binding_ref: str
    workspace_ref: str
    capability: DropboxMutationCapability
    source: DropboxResourceRef | None
    target_parent: DropboxResourceRef | None
    target_name: str
    payload_sha256: str
    expected_rev: str | None = None
    strict_conflict: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "workspace_ref", _safe_ref(self.workspace_ref, "workspace_ref"))
        if not isinstance(self.capability, DropboxMutationCapability):
            try:
                object.__setattr__(self, "capability", DropboxMutationCapability(self.capability))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Dropbox mutation capability") from exc
        if self.source is not None and not isinstance(self.source, DropboxResourceRef):
            raise ContractError("source must be DropboxResourceRef")
        if self.target_parent is not None and not isinstance(self.target_parent, DropboxResourceRef):
            raise ContractError("target_parent must be DropboxResourceRef")
        if self.target_parent is not None and self.target_parent.kind is not DropboxResourceKind.FOLDER:
            raise ContractError("Dropbox target_parent must be a folder")
        object.__setattr__(self, "target_name", _bounded_text(self.target_name, "target_name", 512))
        object.__setattr__(self, "payload_sha256", _hex64(self.payload_sha256, "payload_sha256"))
        object.__setattr__(self, "expected_rev", _optional_ref(self.expected_rev, "expected_rev"))
        if not isinstance(self.strict_conflict, bool):
            raise ContractError("strict_conflict must be bool")

        if self.capability is DropboxMutationCapability.UPLOAD_ADD:
            if self.source is not None or self.target_parent is None or not self.target_name or self.expected_rev is not None:
                raise ContractError("upload_add requires target parent/name and no existing source/rev")
        elif self.capability is DropboxMutationCapability.UPDATE_FILE:
            if self.source is None or self.source.kind is not DropboxResourceKind.FILE or self.expected_rev is None:
                raise ContractError("update_file requires exact file source and expected rev")
            if not self.strict_conflict:
                raise ContractError("update_file requires strict conflict semantics")
        elif self.capability in {DropboxMutationCapability.COPY, DropboxMutationCapability.MOVE}:
            if self.source is None or self.target_parent is None or not self.target_name or self.expected_rev is not None:
                raise ContractError("copy/move require exact source and destination parent/name")
        elif self.capability is DropboxMutationCapability.DELETE:
            if self.source is None or self.target_parent is not None or self.target_name or self.expected_rev is not None:
                raise ContractError("delete requires exact source only")

        if self.source is not None and self.target_parent is not None:
            if self.source.namespace_ref != self.target_parent.namespace_ref:
                raise ContractError("cross-namespace Dropbox mutation is not supported by this contract")

    @property
    def namespace_ref(self) -> str:
        if self.source is not None:
            return self.source.namespace_ref
        assert self.target_parent is not None
        return self.target_parent.namespace_ref

    @property
    def target_ref(self) -> str:
        if self.capability in {DropboxMutationCapability.UPDATE_FILE, DropboxMutationCapability.DELETE}:
            assert self.source is not None
            return f"dropbox:{self.source.key}"
        assert self.target_parent is not None
        name_hash = hashlib.sha256(self.target_name.encode("utf-8")).hexdigest()
        return f"dropbox:{self.target_parent.key}:child-name-sha256:{name_hash}"

    @property
    def provider_expected_version_ref(self) -> str | None:
        return None if self.expected_rev is None else f"dropbox-rev:{_rev_hash(self.expected_rev)}"

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "capability": self.capability.value,
            "source": self.source.key if self.source else None,
            "target_parent": self.target_parent.key if self.target_parent else None,
            "target_name": self.target_name,
            "payload_sha256": self.payload_sha256,
            "expected_rev_sha256": _rev_hash(self.expected_rev) if self.expected_rev else None,
            "strict_conflict": self.strict_conflict,
            "overwrite_without_rev": False,
        }

    @property
    def material_fingerprint(self) -> str:
        encoded = json.dumps(self.canonical_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def version_ref(self) -> str:
        return self.provider_expected_version_ref or f"dropbox-material:{self.material_fingerprint}"


@dataclass(frozen=True, slots=True)
class DropboxMutationApproval:
    approval_ref: str
    evidence_ref: str
    material_fingerprint: str
    approved_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_ref", _safe_ref(self.approval_ref, "approval_ref"))
        object.__setattr__(self, "evidence_ref", _safe_ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "material_fingerprint", _hex64(self.material_fingerprint, "material_fingerprint"))
        object.__setattr__(self, "approved_at", _aware(self.approved_at, "approved_at"))


class DropboxMutationPreflightDecision(str, Enum):
    ALLOW = "allow"
    OUT_OF_SCOPE = "out_of_scope"
    WRONG_CONNECTOR_OR_TOOL = "wrong_connector_or_tool"
    TARGET_MISMATCH = "target_mismatch"
    APPROVAL_MISMATCH = "approval_mismatch"
    MATERIAL_CHANGED = "material_changed"
    STALE_REV = "stale_rev"
    VERSION_BINDING_MISMATCH = "version_binding_mismatch"


def dropbox_mutation_preflight(
    *,
    scope: DropboxScopeProjection,
    material: DropboxMutationMaterial,
    approval: DropboxMutationApproval,
    intent: ConnectorWriteIntent,
    current_source: DropboxMetadataProjection | None = None,
) -> DropboxMutationPreflightDecision:
    if not all((isinstance(scope, DropboxScopeProjection), isinstance(material, DropboxMutationMaterial), isinstance(approval, DropboxMutationApproval), isinstance(intent, ConnectorWriteIntent))):
        raise ContractError("invalid Dropbox mutation preflight contract")
    if material.binding_ref != scope.binding_ref or material.workspace_ref != scope.workspace_ref or not scope.allows_namespace(material.namespace_ref):
        return DropboxMutationPreflightDecision.OUT_OF_SCOPE
    if material.source is not None and not scope.allows(material.source):
        return DropboxMutationPreflightDecision.OUT_OF_SCOPE
    if material.target_parent is not None and not scope.allows(material.target_parent):
        return DropboxMutationPreflightDecision.OUT_OF_SCOPE
    if intent.connector_id != "dropbox" or intent.tool_name != material.capability.value:
        return DropboxMutationPreflightDecision.WRONG_CONNECTOR_OR_TOOL
    if intent.binding_ref != material.binding_ref or intent.target_ref != material.target_ref:
        return DropboxMutationPreflightDecision.TARGET_MISMATCH
    if intent.approval_ref != approval.approval_ref or intent.evidence_ref != approval.evidence_ref:
        return DropboxMutationPreflightDecision.APPROVAL_MISMATCH
    if approval.material_fingerprint != material.material_fingerprint or intent.payload_fingerprint != material.material_fingerprint:
        return DropboxMutationPreflightDecision.MATERIAL_CHANGED
    if intent.expected_version_ref != material.version_ref:
        return DropboxMutationPreflightDecision.VERSION_BINDING_MISMATCH
    if material.capability is DropboxMutationCapability.UPDATE_FILE:
        if current_source is None or material.source is None:
            return DropboxMutationPreflightDecision.STALE_REV
        if (
            current_source.binding_ref != material.binding_ref
            or current_source.workspace_ref != material.workspace_ref
            or current_source.resource.key != material.source.key
            or current_source.deleted
            or current_source.rev != material.expected_rev
        ):
            return DropboxMutationPreflightDecision.STALE_REV
    return DropboxMutationPreflightDecision.ALLOW


@dataclass(frozen=True, slots=True)
class DropboxMutationReceipt:
    connector_receipt: ConnectorWriteReceipt
    capability: DropboxMutationCapability
    approved_target_ref: str
    result_resource: DropboxResourceRef | None
    result_rev: str | None
    result_provider_content_hash: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.connector_receipt, ConnectorWriteReceipt) or self.connector_receipt.connector_id != "dropbox":
            raise ContractError("Dropbox receipt requires dropbox ConnectorWriteReceipt")
        if not isinstance(self.capability, DropboxMutationCapability):
            try:
                object.__setattr__(self, "capability", DropboxMutationCapability(self.capability))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Dropbox receipt capability") from exc
        object.__setattr__(self, "approved_target_ref", _safe_ref(self.approved_target_ref, "approved_target_ref"))
        if self.connector_receipt.target_ref != self.approved_target_ref:
            raise ContractError("Dropbox receipt target does not match approved target")
        if self.result_resource is not None and not isinstance(self.result_resource, DropboxResourceRef):
            raise ContractError("result_resource must be DropboxResourceRef")
        object.__setattr__(self, "result_rev", _optional_ref(self.result_rev, "result_rev"))
        if self.result_provider_content_hash is not None:
            object.__setattr__(self, "result_provider_content_hash", _hex64(self.result_provider_content_hash, "result_provider_content_hash"))
        if self.capability is DropboxMutationCapability.DELETE:
            if self.result_rev is not None or self.result_provider_content_hash is not None:
                raise ContractError("Dropbox delete receipt cannot claim live file revision/hash")
        elif self.result_resource is None:
            raise ContractError("Dropbox non-delete receipt requires result resource")


DROPBOX_OFFICIAL_API_REQUIRED = True
DROPBOX_PATH_ROOT_EXPLICIT = True
DROPBOX_APP_FOLDER_PREFERRED_WHEN_SUFFICIENT = True
DROPBOX_WHOLE_ACCOUNT_MODEL_VISIBILITY = False
DROPBOX_DISPLAY_PATH_IS_AUTHORITY = False
DROPBOX_WHOLE_TREE_SYNC_SUPPORTED = False
DROPBOX_UPDATE_WRITE_MODE = "update_rev"
DROPBOX_STRICT_CONFLICT_REQUIRED = True
DROPBOX_PROVIDER_CONTENT_HASH_IS_SHA256 = False
DROPBOX_RAW_OAUTH_TOKEN_IN_B54 = False
REAL_DROPBOX_OAUTH_CONFIGURED = False
REAL_DROPBOX_MUTATION_CONFIGURED = False
