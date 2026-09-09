"""Engine Drive capability classification + projection seam (#2186 S3).

Smallest Engine-side extension of the existing Drive trusted binding seam
(``app/connector_bindings.py``): every Drive tool id is classified through
Core's fail-closed capability split *before* any binding/authorization
decision, and one bounded capability-fact projection is available to Engine
transports.

Boundaries preserved:

* Core remains the sole tool runtime; the Engine never instantiates a second
  runtime and never re-registers tools here;
* no live provider transport call, no OAuth flow, no credential read/write —
  the projection carries capability facts only;
* no Production composition change, no manifest flip, no wire path: this seam
  is inert until a later slice wires it into ``worker_identity`` composition;
* classification failures fail closed (tool ids that are not the promoted READ
  tools classify as WRITE_OR_MATERIAL/UNKNOWN and are rejected for binding).
"""

from __future__ import annotations

from typing import Any

from padiem_ai_core.drive_capability import (
    DRIVE_CONNECTOR_ID,
    DRIVE_READ_TOOL_IDS,
    DriveCapability,
    DriveCapabilityClassification,
    DriveCapabilityGrant,
    classify_drive_tool_id,
    core_auth_scopes_for_capability,
    drive_capability_snapshot,
)

DRIVE_ENGINE_CAPABILITY_PROJECTION_VERSION = "engine-drive-capability.v1"


def classify_drive_tool_for_binding(tool_id: str) -> DriveCapabilityClassification:
    """Classify a Drive tool id at the Engine binding seam.

    Raises for anything that is not a promoted READ tool: write/material or
    unknown tool ids must never reach binding assembly.
    """

    classification = classify_drive_tool_id(tool_id)
    if classification is not DriveCapabilityClassification.READ:
        raise ValueError(f"drive_tool_not_bindable:{classification.value}")
    return classification


def project_drive_capability_facts(
    grant: DriveCapabilityGrant,
    *,
    tool_ids: tuple[str, ...] = DRIVE_READ_TOOL_IDS,
) -> dict[str, Any]:
    """Project bounded Drive capability facts for Engine transports.

    Deterministic, network-free, and credential-free: the projection contains
    capability/scope *names* only, never token values, never provider
    endpoints beyond the connector id, and never a second approval authority.
    Every requested tool id must classify as READ or the projection refuses.
    """

    if not isinstance(grant, DriveCapabilityGrant):
        raise ValueError("grant must be a Core DriveCapabilityGrant")
    if not tool_ids:
        raise ValueError("tool_ids must not be empty")
    for tool_id in tool_ids:
        classify_drive_tool_for_binding(tool_id)
    return {
        "projection_version": DRIVE_ENGINE_CAPABILITY_PROJECTION_VERSION,
        "connector_id": grant.connector_id,
        "binding_ref": grant.binding_ref,
        "granted_capabilities": sorted(item.value for item in grant.granted_capabilities),
        "bindable_tool_ids": sorted(tool_ids),
        "capability_core_auth_scopes": {
            capability.value: list(core_auth_scopes_for_capability(capability))
            for capability in DriveCapability
        },
        "p01_approval_required": {
            capability.value: capability_requires_p01_approval(capability)
            for capability in DriveCapability
        },
        "draft_implies_send": False,
        "mints_approval_authority": False,
        "raw_credentials_present": False,
        "oauth_token_present": False,
        "live_provider_calls": 0,
        "production_activation": False,
    }


def capability_requires_p01_approval(capability: DriveCapability) -> bool:
    """Re-export Core decision (never mints approval authority)."""

    from padiem_ai_core.drive_capability import capability_requires_p01_approval as _core

    return _core(capability)


__all__ = [
    "DRIVE_ENGINE_CAPABILITY_PROJECTION_VERSION",
    "classify_drive_tool_for_binding",
    "project_drive_capability_facts",
    "drive_capability_snapshot",
]
