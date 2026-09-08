"""Engine Gmail capability classification + projection seam (#2141 S1).

Smallest Engine-side extension of the existing Gmail trusted binding seam
(``app/connector_bindings.py``): every Gmail tool id is classified through
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
* classification failures fail closed (tool ids that are not the three
  promoted READ tools classify as WRITE_OR_MATERIAL/UNKNOWN and are rejected
  for binding).
"""

from __future__ import annotations

from typing import Any

from padiem_ai_core.connectors import GMAIL_CANONICAL_TOOL_IDS, GMAIL_CONNECTOR_ID
from padiem_ai_core.gmail_capability import (
    GMAIL_READ_TOOL_IDS,
    GmailCapability,
    GmailCapabilityClassification,
    GmailCapabilityGrant,
    capability_requires_p01_approval,
    classify_gmail_tool_id,
    core_auth_scopes_for_capability,
    gmail_capability_snapshot,
)

GMAIL_ENGINE_CAPABILITY_PROJECTION_VERSION = "engine-gmail-capability.v1"


def classify_gmail_tool_for_binding(tool_id: str) -> GmailCapabilityClassification:
    """Classify a Gmail tool id at the Engine binding seam.

    Raises for anything that is not a promoted READ tool: write/material or
    unknown tool ids must never reach binding assembly. This is the seam-level
    enforcement of ``unknown/new Gmail tools fail closed``.
    """

    classification = classify_gmail_tool_id(tool_id)
    if classification is not GmailCapabilityClassification.READ:
        raise ValueError(f"gmail_tool_not_bindable:{classification.value}")
    return classification


def project_gmail_capability_facts(
    grant: GmailCapabilityGrant,
    *,
    tool_ids: tuple[str, ...] = GMAIL_READ_TOOL_IDS,
) -> dict[str, Any]:
    """Project bounded Gmail capability facts for Engine transports.

    Deterministic, network-free, and credential-free: the projection contains
    capability/scope *names* only, never token values, never provider
    endpoints beyond the connector id, and never a second approval authority.
    Every requested tool id must classify as READ or the projection refuses.
    """

    if not isinstance(grant, GmailCapabilityGrant):
        raise ValueError("grant must be a Core GmailCapabilityGrant")
    if not tool_ids:
        raise ValueError("tool_ids must not be empty")
    for tool_id in tool_ids:
        classify_gmail_tool_for_binding(tool_id)
    return {
        "projection_version": GMAIL_ENGINE_CAPABILITY_PROJECTION_VERSION,
        "connector_id": grant.connector_id if grant.connector_id == GMAIL_CONNECTOR_ID else grant.connector_id,
        "binding_ref": grant.binding_ref,
        "granted_capabilities": sorted(item.value for item in grant.granted_capabilities),
        "send_authority": grant.send_authority(),
        "bindable_tool_ids": sorted(tool_ids),
        "capability_core_auth_scopes": {
            capability.value: list(core_auth_scopes_for_capability(capability))
            for capability in GmailCapability
        },
        "p01_approval_required": {
            capability.value: capability_requires_p01_approval(capability)
            for capability in GmailCapability
        },
        "draft_implies_send": False,
        "mints_approval_authority": False,
        "raw_credentials_present": False,
        "oauth_token_present": False,
        "live_provider_calls": 0,
        "production_activation": False,
    }


__all__ = [
    "GMAIL_ENGINE_CAPABILITY_PROJECTION_VERSION",
    "classify_gmail_tool_for_binding",
    "project_gmail_capability_facts",
    "gmail_capability_snapshot",
]
