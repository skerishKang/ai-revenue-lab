"""Catalogue -> Core projection contract (#1999, Gap 1 of #1998).

Claw's reviewed catalogue (``ConnectorCatalogueEntry``) stays the operational
source of truth. This module projects reviewed entries into the Core canonical
shapes — ``ConnectorDescriptor`` rows plus a ``ToolRegistrySnapshot`` of
``RegisteredTool`` rows — so the connector roadmap becomes visible in the
shared registry WITHOUT execution activation. ``ConnectorRuntime`` stays
dormant; nothing here registers handlers or invokes providers.

ID grammar (Core connector_registry.py:23-28):
- connector: ``connector:b54:<connector_id>@1``
- tool:      ``tool:b54:<connector_id>_<tool_name>@1``

Fail-closed rules mirrored from connector_platform.py:115-127:
- a tool's effect comes ONLY from the entry's reviewed read_tools/write_tools
  lists;
- an advertised tool that is not explicitly reviewed raises
  ``ConnectorProjectionError`` — it is never silently projected as READ;
- every WRITE tool carries ``ApprovalPolicy.USER_CONFIRMATION``
  (Core contracts.py:155-156 enforces that write tools need a policy).

Drift detection is free: ``RegisteredTool`` fingerprints are SHA-256 over the
ToolSpec content (tool_registry.py:47-60), so any change to a projected tool
definition changes the fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from padiem_ai_core.connector_registry import (
    ConnectorDescriptor,
    ConnectorRegistrySnapshot,
    validate_connector_tools,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_registry import ToolRegistrySnapshot

from .connector_platform import (
    ConnectorAuthKind,
    ConnectorCatalogueEntry,
    ConnectorTool,
    GOOGLE_DRIVE_ENTRY,
)
from .gmail_connector import GMAIL_ENTRY, GMAIL_TOOLS
from .google_drive_connector import DRIVE_TOOLS
from .verified_mcp_catalogue import GOOGLE_CALENDAR_ENTRY, SLACK_ENTRY
from .notion_contracts import CURRENT_NOTION_MCP_ENTRY

PROJECTION_OWNER = "b54"
PROJECTION_MAJOR = 1

# The five reviewed catalogue entries projected by this slice
# (#1998 anchors: gmail_connector.py:47-56, connector_platform.py:399-414,
# verified_mcp_catalogue.py:43-94, notion_contracts.py:59-89).
PROJECTED_CATALOGUE_ENTRIES: tuple[ConnectorCatalogueEntry, ...] = (
    GMAIL_ENTRY,
    GOOGLE_DRIVE_ENTRY,
    GOOGLE_CALENDAR_ENTRY,
    SLACK_ENTRY,
    CURRENT_NOTION_MCP_ENTRY,
)

# Reviewed parameter contracts that exist today. Entries without a reviewed
# ConnectorTool schema project with the neutral object schema below; their
# effect classification still comes from the entry's read/write lists.
REVIEWED_TOOL_SCHEMAS: dict[str, ConnectorTool] = {
    f"{GMAIL_ENTRY.connector_id}/{tool.name}": tool for tool in GMAIL_TOOLS
} | {
    f"{GOOGLE_DRIVE_ENTRY.connector_id}/{tool.name}": tool for tool in DRIVE_TOOLS
}

# #1998 classification: roadmap connectors that must NOT be projected yet.
# Reasons are structural, not capacity (#1998 ④/⑤).
DEFERRED_CONNECTORS: dict[str, str] = {
    "kakao": (
        "send governance: template-reviewed sender needs a send-boundary "
        "policy field the descriptor does not model (#1998 ④ NEEDS_EXTENSION)"
    ),
    "neon-postgres": (
        "dynamic SQL surface: statement-level read/write effect cannot be "
        "classified by tool name (#1998 ④ NEEDS_EXTENSION)"
    ),
    "cloudflare": (
        "production mutation stays on the bespoke write-intent path "
        "(cloudflare_connector.py / connector_trust.py); connector registry "
        "does not model deployment governance (#1998 ④ NEEDS_NEW_MECHANISM)"
    ),
}

_NEUTRAL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": True,
}


class ConnectorProjectionError(ValueError):
    """Fail-closed projection contract violation."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def _canonical_connector_id(connector_id: str) -> str:
    return f"connector:{PROJECTION_OWNER}:{connector_id}@{PROJECTION_MAJOR}"


def _canonical_tool_id(connector_id: str, tool_name: str) -> str:
    return (
        f"tool:{PROJECTION_OWNER}:{connector_id}_{tool_name}@{PROJECTION_MAJOR}"
    )


def _runtime_tool_id(connector_id: str, tool_name: str) -> str:
    # ToolSpec.id uses the dot-safe identifier grammar (contracts.py:9);
    # the versioned canonical id is the registry key (tool_registry.py:20-22).
    return f"{PROJECTION_OWNER}.{connector_id}_{tool_name}"


def _requires_authorization(entry: ConnectorCatalogueEntry) -> bool:
    # Keyless kinds (NONE / BUILTIN) do not require an authorization ref;
    # USER_OAUTH and DEPLOYMENT_BEARER do. Core never sees the credential —
    # only an opaque reference (connector_registry.py:238-266).
    return entry.auth_kind not in {ConnectorAuthKind.NONE, ConnectorAuthKind.BUILTIN}


@dataclass(frozen=True, slots=True)
class ConnectorProjection:
    """Projected Core shapes + per-tool fingerprints for drift detection."""

    descriptors: tuple[ConnectorDescriptor, ...]
    connector_registry: ConnectorRegistrySnapshot
    tool_registry: ToolRegistrySnapshot
    fingerprints: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.connector_registry, ConnectorRegistrySnapshot):
            raise ConnectorProjectionError(
                "invalid_projection", "connector_registry must be ConnectorRegistrySnapshot"
            )
        if not isinstance(self.tool_registry, ToolRegistrySnapshot):
            raise ConnectorProjectionError(
                "invalid_projection", "tool_registry must be ToolRegistrySnapshot"
            )
        # Loop closure (#1999 required work 2): every descriptor's tool refs
        # must resolve in the projected snapshot (connector_registry.py:205-229).
        for descriptor in self.descriptors:
            validate_connector_tools(descriptor, self.tool_registry)


def _tool_spec(
    entry: ConnectorCatalogueEntry,
    tool_name: str,
    effect_read: bool,
) -> ToolSpec:
    canonical_id = _canonical_tool_id(entry.connector_id, tool_name)
    reviewed = REVIEWED_TOOL_SCHEMAS.get(f"{entry.connector_id}/{tool_name}")
    if reviewed is not None:
        description = reviewed.description
        input_schema: dict[str, Any] = dict(reviewed.input_schema)
    else:
        effect_word = "read" if effect_read else "write"
        description = (
            f"{entry.title} reviewed {effect_word} tool '{tool_name}' "
            "(catalogue projection; parameter contract not yet reviewed)."
        )
        input_schema = dict(_NEUTRAL_INPUT_SCHEMA)
    return ToolSpec(
        id=_runtime_tool_id(entry.connector_id, tool_name),
        title=f"{entry.title}: {tool_name}",
        description=description,
        owner=PROJECTION_OWNER,
        side_effect=ToolSideEffect.READ if effect_read else ToolSideEffect.WRITE,
        approval_policy=(
            ApprovalPolicy.NOT_REQUIRED
            if effect_read
            else ApprovalPolicy.USER_CONFIRMATION
        ),
        input_schema=input_schema,
    )


def project_catalogue_entries(
    entries: Iterable[ConnectorCatalogueEntry],
    *,
    advertised_tools: Mapping[str, Iterable[str]] | None = None,
) -> ConnectorProjection:
    """Project reviewed catalogue entries into Core canonical shapes.

    ``advertised_tools`` optionally carries per-connector tool names a
    transport advertises at runtime. Any advertised tool that is not in the
    entry's reviewed read/write lists raises — the projection never converts
    an unreviewed tool into a READ (mirrors classify() fail-closed,
    connector_platform.py:115-127).
    """

    entries = tuple(entries)
    if not entries:
        raise ConnectorProjectionError("empty_projection", "no catalogue entries provided")

    deferred = set(DEFERRED_CONNECTORS)
    descriptors: list[ConnectorDescriptor] = []
    registry = ToolRegistrySnapshot()
    fingerprints: dict[str, str] = {}

    for entry in entries:
        if entry.connector_id in deferred:
            raise ConnectorProjectionError(
                "deferred_connector_projection",
                f"connector '{entry.connector_id}' is DEFERRED per #1998 and "
                "must not be projected in this slice",
            )

        reviewed_names = set(entry.read_tools) | set(entry.write_tools)
        if advertised_tools is not None:
            for name in advertised_tools.get(entry.connector_id, ()):
                if name not in reviewed_names:
                    raise ConnectorProjectionError(
                        "unreviewed_tool",
                        f"advertised tool '{name}' on connector "
                        f"'{entry.connector_id}' is not in the reviewed "
                        "read/write lists; refusing to project it as READ",
                    )

        canonical_tool_ids: list[str] = []
        # Deterministic order: reads then writes, as reviewed.
        for tool_name in entry.read_tools:
            canonical_id = _canonical_tool_id(entry.connector_id, tool_name)
            registry = registry.with_tool(
                canonical_tool_id=canonical_id,
                runtime_spec=_tool_spec(entry, tool_name, effect_read=True),
            )
            fingerprints[canonical_id] = registry.get(canonical_id).fingerprint
            canonical_tool_ids.append(canonical_id)
        for tool_name in entry.write_tools:
            canonical_id = _canonical_tool_id(entry.connector_id, tool_name)
            spec = _tool_spec(entry, tool_name, effect_read=False)
            if spec.approval_policy is ApprovalPolicy.NOT_REQUIRED:
                # Defensive: a WRITE without a policy must never be emitted.
                raise ConnectorProjectionError(
                    "write_tool_missing_approval_policy",
                    f"projected write tool '{canonical_id}' lacks an "
                    "approval policy; refusing silent downgrade",
                )
            registry = registry.with_tool(
                canonical_tool_id=canonical_id,
                runtime_spec=spec,
            )
            fingerprints[canonical_id] = registry.get(canonical_id).fingerprint
            canonical_tool_ids.append(canonical_id)

        descriptors.append(
            ConnectorDescriptor(
                connector_id=_canonical_connector_id(entry.connector_id),
                title=entry.title,
                canonical_tool_ids=tuple(canonical_tool_ids),
                requires_authorization=_requires_authorization(entry),
            )
        )

    connector_registry = ConnectorRegistrySnapshot.from_connectors(descriptors)
    return ConnectorProjection(
        descriptors=tuple(descriptors),
        connector_registry=connector_registry,
        tool_registry=registry,
        fingerprints=dict(fingerprints),
    )


def project_reviewed_entries() -> ConnectorProjection:
    """Project the five reviewed entries (Gmail, Drive, Calendar, Slack, Notion)."""

    return project_catalogue_entries(PROJECTED_CATALOGUE_ENTRIES)
