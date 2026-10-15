from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .connector_platform import ConnectorAuthKind, ConnectorCatalogueEntry
from .connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from .contracts import ContractError
from .security import redact_secrets

MAX_NOTION_RESOURCES = 512
MAX_NOTION_CONTENT_CHARS = 40_000
MAX_NOTION_LINKED_REFS = 256
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


def _sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip().lower()):
        raise ContractError(f"{field_name} must be lowercase SHA-256")
    return value.strip().lower()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _bounded_text(value: str, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
    normalized = redact_secrets(value.strip())
    if len(normalized) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    return normalized


CURRENT_NOTION_MCP_ENTRY = ConnectorCatalogueEntry(
    connector_id="notion",
    title="Notion",
    vendor="Notion",
    host="https://mcp.notion.com",
    path="/mcp",
    auth_kind=ConnectorAuthKind.USER_OAUTH,
    transport_kind="mcp",
    read_tools=(
        "notion-search",
        "notion-fetch",
        "notion-get-comments",
        "notion-get-teams",
        "notion-get-users",
        "notion-get-user",
        "notion-get-self",
        "notion-query-data-sources",
        "notion-query-database-view",
    ),
    write_tools=(
        "notion-create-pages",
        "notion-update-page",
        "notion-move-pages",
        "notion-duplicate-page",
        "notion-create-database",
        "notion-update-data-source",
        "notion-create-view",
        "notion-update-view",
        "notion-create-comment",
    ),
)


class NotionResourceKind(str, Enum):
    PAGE = "page"
    DATABASE = "database"
    DATA_SOURCE = "data_source"
    VIEW = "view"


@dataclass(frozen=True, slots=True)
class NotionResourceRef:
    kind: NotionResourceKind
    resource_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, NotionResourceKind):
            try:
                object.__setattr__(self, "kind", NotionResourceKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Notion resource kind") from exc
        object.__setattr__(self, "resource_ref", _safe_ref(self.resource_ref, "resource_ref"))

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.resource_ref}"


@dataclass(frozen=True, slots=True)
class NotionScopeProjection:
    binding_ref: str
    workspace_ref: str
    allowed_resources: tuple[NotionResourceRef, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "workspace_ref", _safe_ref(self.workspace_ref, "workspace_ref"))
        if not self.allowed_resources or len(self.allowed_resources) > MAX_NOTION_RESOURCES:
            raise ContractError("Notion scope requires 1..512 explicit resources")
        if any(not isinstance(item, NotionResourceRef) for item in self.allowed_resources):
            raise ContractError("allowed_resources must contain NotionResourceRef")
        keys = tuple(item.key for item in self.allowed_resources)
        if len(keys) != len(set(keys)):
            raise ContractError("Notion allowed resources must be unique")

    def allows(self, resource: NotionResourceRef) -> bool:
        if not isinstance(resource, NotionResourceRef):
            raise ContractError("resource must be NotionResourceRef")
        return resource.key in {item.key for item in self.allowed_resources}

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-notion-scope.v1",
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "allowed_resources": [item.key for item in self.allowed_resources],
            "whole_workspace_model_visibility": False,
            "linked_resource_scope_expansion": False,
        }


@dataclass(frozen=True, slots=True)
class NotionSearchHit:
    resource: NotionResourceRef
    title: str
    last_edited_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.resource, NotionResourceRef):
            raise ContractError("resource must be NotionResourceRef")
        object.__setattr__(self, "title", _bounded_text(self.title, "title", 512))
        if self.last_edited_at is not None:
            object.__setattr__(self, "last_edited_at", _aware(self.last_edited_at, "last_edited_at"))


def filter_notion_search_hits(scope: NotionScopeProjection, hits: tuple[NotionSearchHit, ...]) -> tuple[NotionSearchHit, ...]:
    if not isinstance(scope, NotionScopeProjection):
        raise ContractError("scope must be NotionScopeProjection")
    if any(not isinstance(hit, NotionSearchHit) for hit in hits):
        raise ContractError("hits must contain NotionSearchHit")
    return tuple(hit for hit in hits if scope.allows(hit.resource))


@dataclass(frozen=True, slots=True)
class NotionContentProjection:
    binding_ref: str
    workspace_ref: str
    resource: NotionResourceRef
    content_text: str
    last_edited_at: datetime
    content_sha256: str
    linked_resources: tuple[NotionResourceRef, ...] = ()
    in_trash: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "workspace_ref", _safe_ref(self.workspace_ref, "workspace_ref"))
        if not isinstance(self.resource, NotionResourceRef):
            raise ContractError("resource must be NotionResourceRef")
        object.__setattr__(self, "content_text", _bounded_text(self.content_text, "Notion content", MAX_NOTION_CONTENT_CHARS))
        object.__setattr__(self, "last_edited_at", _aware(self.last_edited_at, "last_edited_at"))
        object.__setattr__(self, "content_sha256", _sha256(self.content_sha256, "content_sha256"))
        if len(self.linked_resources) > MAX_NOTION_LINKED_REFS or any(not isinstance(item, NotionResourceRef) for item in self.linked_resources):
            raise ContractError("linked_resources exceed bound or contain invalid values")
        if not isinstance(self.in_trash, bool):
            raise ContractError("in_trash must be bool")

    def model_projection(self, scope: NotionScopeProjection) -> dict[str, Any]:
        if self.binding_ref != scope.binding_ref or self.workspace_ref != scope.workspace_ref or not scope.allows(self.resource):
            raise ContractError("Notion content is outside trusted Padiem scope")
        visible_links = [item.key for item in self.linked_resources if scope.allows(item)]
        return {
            "resource": self.resource.key,
            "content_text": self.content_text,
            "last_edited_at": self.last_edited_at.isoformat().replace("+00:00", "Z"),
            "content_sha256": self.content_sha256,
            "linked_resources": visible_links,
            "in_trash": self.in_trash,
            "content_trusted": False,
            "out_of_scope_links_hidden": len(visible_links) != len(self.linked_resources),
        }

    @property
    def state_fingerprint(self) -> str:
        payload = json.dumps(
            {
                "resource": self.resource.key,
                "last_edited_at": self.last_edited_at.isoformat(),
                "content_sha256": self.content_sha256,
                "in_trash": self.in_trash,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @property
    def state_ref(self) -> str:
        return f"notion-state:{self.state_fingerprint}"


class NotionMutationCapability(str, Enum):
    CREATE_PAGE = "notion.create_page"
    UPDATE_PAGE = "notion.update_page"
    MOVE_PAGE = "notion.move_page"
    DUPLICATE_PAGE = "notion.duplicate_page"
    CREATE_COMMENT = "notion.create_comment"
    CREATE_DATABASE = "notion.create_database"
    UPDATE_DATA_SOURCE = "notion.update_data_source"
    CREATE_VIEW = "notion.create_view"
    UPDATE_VIEW = "notion.update_view"
    TRASH_PAGE = "notion.trash_page"
    RESTORE_PAGE = "notion.restore_page"


@dataclass(frozen=True, slots=True)
class NotionMutationMaterial:
    binding_ref: str
    workspace_ref: str
    capability: NotionMutationCapability
    target: NotionResourceRef | None
    parent: NotionResourceRef | None
    title: str
    content_sha256: str
    properties_sha256: str
    expected_state_ref: str | None = None
    in_trash: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "workspace_ref", _safe_ref(self.workspace_ref, "workspace_ref"))
        if not isinstance(self.capability, NotionMutationCapability):
            try:
                object.__setattr__(self, "capability", NotionMutationCapability(self.capability))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Notion mutation capability") from exc
        if self.target is not None and not isinstance(self.target, NotionResourceRef):
            raise ContractError("target must be NotionResourceRef")
        if self.parent is not None and not isinstance(self.parent, NotionResourceRef):
            raise ContractError("parent must be NotionResourceRef")
        object.__setattr__(self, "title", _bounded_text(self.title, "title", 1024))
        object.__setattr__(self, "content_sha256", _sha256(self.content_sha256, "content_sha256"))
        object.__setattr__(self, "properties_sha256", _sha256(self.properties_sha256, "properties_sha256"))
        object.__setattr__(self, "expected_state_ref", _optional_ref(self.expected_state_ref, "expected_state_ref"))
        if self.in_trash is not None and not isinstance(self.in_trash, bool):
            raise ContractError("in_trash must be bool when supplied")

        create_caps = {NotionMutationCapability.CREATE_PAGE, NotionMutationCapability.CREATE_DATABASE, NotionMutationCapability.CREATE_VIEW}
        existing_caps = set(NotionMutationCapability) - create_caps
        if self.capability in create_caps:
            if self.parent is None or self.expected_state_ref is not None:
                raise ContractError("Notion create operation requires parent and no expected existing state")
        elif self.capability in existing_caps:
            if self.target is None:
                raise ContractError("Notion existing-resource mutation requires exact target")
        if self.capability is NotionMutationCapability.MOVE_PAGE and self.parent is None:
            raise ContractError("move_page requires exact destination parent")
        if self.capability is NotionMutationCapability.TRASH_PAGE and self.in_trash is not True:
            raise ContractError("trash_page requires in_trash=true")
        if self.capability is NotionMutationCapability.RESTORE_PAGE and self.in_trash is not False:
            raise ContractError("restore_page requires in_trash=false")

    @property
    def target_ref(self) -> str:
        if self.target is not None:
            return f"notion:{self.workspace_ref}:{self.target.key}"
        assert self.parent is not None
        return f"notion:{self.workspace_ref}:parent:{self.parent.key}:new:{self.capability.value}"

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "capability": self.capability.value,
            "target": self.target.key if self.target else None,
            "parent": self.parent.key if self.parent else None,
            "title": self.title,
            "content_sha256": self.content_sha256,
            "properties_sha256": self.properties_sha256,
            "expected_state_ref": self.expected_state_ref,
            "in_trash": self.in_trash,
            "permanent_delete": False,
        }

    @property
    def material_fingerprint(self) -> str:
        encoded = json.dumps(self.canonical_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def version_ref(self) -> str:
        return f"notion-material:{self.material_fingerprint}"


@dataclass(frozen=True, slots=True)
class NotionMutationApproval:
    approval_ref: str
    evidence_ref: str
    material_fingerprint: str
    approved_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_ref", _safe_ref(self.approval_ref, "approval_ref"))
        object.__setattr__(self, "evidence_ref", _safe_ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "material_fingerprint", _sha256(self.material_fingerprint, "material_fingerprint"))
        object.__setattr__(self, "approved_at", _aware(self.approved_at, "approved_at"))


class NotionMutationPreflightDecision(str, Enum):
    ALLOW = "allow"
    OUT_OF_SCOPE = "out_of_scope"
    WRONG_CONNECTOR_OR_TOOL = "wrong_connector_or_tool"
    TARGET_MISMATCH = "target_mismatch"
    APPROVAL_MISMATCH = "approval_mismatch"
    MATERIAL_CHANGED = "material_changed"
    STALE_STATE = "stale_state"
    VERSION_BINDING_MISMATCH = "version_binding_mismatch"


def notion_mutation_preflight(
    *,
    scope: NotionScopeProjection,
    material: NotionMutationMaterial,
    approval: NotionMutationApproval,
    intent: ConnectorWriteIntent,
    current_state: NotionContentProjection | None = None,
) -> NotionMutationPreflightDecision:
    if not all((isinstance(scope, NotionScopeProjection), isinstance(material, NotionMutationMaterial), isinstance(approval, NotionMutationApproval), isinstance(intent, ConnectorWriteIntent))):
        raise ContractError("invalid Notion mutation preflight contract")
    if material.binding_ref != scope.binding_ref or material.workspace_ref != scope.workspace_ref:
        return NotionMutationPreflightDecision.OUT_OF_SCOPE
    if material.target is not None and not scope.allows(material.target):
        return NotionMutationPreflightDecision.OUT_OF_SCOPE
    if material.parent is not None and not scope.allows(material.parent):
        return NotionMutationPreflightDecision.OUT_OF_SCOPE
    if intent.connector_id != "notion" or intent.tool_name != material.capability.value:
        return NotionMutationPreflightDecision.WRONG_CONNECTOR_OR_TOOL
    if intent.binding_ref != material.binding_ref or intent.target_ref != material.target_ref:
        return NotionMutationPreflightDecision.TARGET_MISMATCH
    if intent.approval_ref != approval.approval_ref or intent.evidence_ref != approval.evidence_ref:
        return NotionMutationPreflightDecision.APPROVAL_MISMATCH
    if approval.material_fingerprint != material.material_fingerprint or intent.payload_fingerprint != material.material_fingerprint:
        return NotionMutationPreflightDecision.MATERIAL_CHANGED
    if intent.expected_version_ref != material.version_ref:
        return NotionMutationPreflightDecision.VERSION_BINDING_MISMATCH
    if material.expected_state_ref is not None:
        if current_state is None or material.target is None:
            return NotionMutationPreflightDecision.STALE_STATE
        if (
            current_state.binding_ref != material.binding_ref
            or current_state.workspace_ref != material.workspace_ref
            or current_state.resource.key != material.target.key
            or current_state.state_ref != material.expected_state_ref
        ):
            return NotionMutationPreflightDecision.STALE_STATE
    return NotionMutationPreflightDecision.ALLOW


@dataclass(frozen=True, slots=True)
class NotionMutationReceipt:
    connector_receipt: ConnectorWriteReceipt
    capability: NotionMutationCapability
    approved_target_ref: str
    result_resource: NotionResourceRef
    result_last_edited_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.connector_receipt, ConnectorWriteReceipt) or self.connector_receipt.connector_id != "notion":
            raise ContractError("Notion receipt requires notion ConnectorWriteReceipt")
        if not isinstance(self.capability, NotionMutationCapability):
            try:
                object.__setattr__(self, "capability", NotionMutationCapability(self.capability))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Notion receipt capability") from exc
        object.__setattr__(self, "approved_target_ref", _safe_ref(self.approved_target_ref, "approved_target_ref"))
        if self.connector_receipt.target_ref != self.approved_target_ref:
            raise ContractError("Notion receipt target does not match approved target")
        if not isinstance(self.result_resource, NotionResourceRef):
            raise ContractError("result_resource must be NotionResourceRef")
        object.__setattr__(self, "result_last_edited_at", _aware(self.result_last_edited_at, "result_last_edited_at"))


NOTION_HOSTED_MCP_ENDPOINT = "https://mcp.notion.com/mcp"
NOTION_HOSTED_MCP_USER_OAUTH_REQUIRED = True
NOTION_HOSTED_MCP_PKCE_SUPPORTED = True
NOTION_HOSTED_MCP_FILE_UPLOAD_SUPPORTED = False
NOTION_WHOLE_WORKSPACE_MODEL_VISIBILITY_IMPLIED = False
NOTION_LINKED_RESOURCE_SCOPE_EXPANSION = False
NOTION_PERMANENT_DELETE_SUPPORTED = False
NOTION_CURRENT_TRASH_FIELD = "in_trash"
NOTION_DEPRECATED_REQUEST_TRASH_FIELD = "archived"
NOTION_DATABASE_DATA_SOURCE_DISTINCT = True
NOTION_RAW_OAUTH_TOKEN_IN_B54 = False
REAL_NOTION_MCP_CONFIGURED = False
REAL_NOTION_MUTATION_CONFIGURED = False
