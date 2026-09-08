"""Promoted Gmail capability-split contract (#2141, parent #2010).

Classifies every Gmail tool request into an explicit capability class before
any authorization decision. READ-only tool contracts live in the
already-promoted :mod:`padiem_ai_core.connectors` module; this module adds the
explicit capability split ported from the reviewed B54 contract
(``kagent/gmail_contracts.py``), which remains compatibility evidence only.

Fail-closed rules:

* only the three promoted READ tool ids (and their canonical ids) classify as
  READ; every unknown, unregistered, or future Gmail tool id — including draft,
  send, and label tools that do not exist yet in Core — classifies as
  WRITE_OR_MATERIAL and is rejected before any capability grant is considered;
* draft creation never implies send authority: ``CREATE_DRAFT`` and
  ``SEND_EXISTING_APPROVED_DRAFT`` are distinct capabilities with distinct
  scope requirements, and send additionally requires existing P01
  approval/evidence semantics (never minted here);
* provider OAuth scope strings never become Core authorization facts; only the
  bounded Core auth-scope tokens cross this contract, and raw OAuth tokens can
  never appear in any projection (Core owns no credential surface at all);
* the provider ``gmail.compose`` scope is broader than Padiem send authority,
  so a provider scope alone can never grant send capability.

This module owns no HTTP, no OAuth flow, no credentials, and no provider
transport. It is deterministic and network-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from .connectors import (
    GMAIL_CANONICAL_TOOL_IDS,
    GMAIL_GET_MESSAGE_TOOL_ID,
    GMAIL_GET_THREAD_TOOL_ID,
    GMAIL_SEARCH_MESSAGES_TOOL_ID,
    GMAIL_READONLY_AUTH_SCOPE,
    GMAIL_READONLY_SCOPE,
    GmailContractError,
)

# Provider OAuth scopes (trusted port boundary only; never Core identifiers).
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"

# Bounded Core auth-scope tokens (provider URLs cannot be ToolSpec scopes).
GMAIL_COMPOSE_AUTH_SCOPE = "gmail.compose"
GMAIL_MODIFY_AUTH_SCOPE = "gmail.modify"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")

GMAIL_READ_TOOL_IDS = (
    GMAIL_SEARCH_MESSAGES_TOOL_ID,
    GMAIL_GET_MESSAGE_TOOL_ID,
    GMAIL_GET_THREAD_TOOL_ID,
)


class GmailCapability(str, Enum):
    """Explicit Gmail capability classes (ported from the reviewed B54 contract)."""

    READ = "read"
    CREATE_DRAFT = "create_draft"
    SEND_EXISTING_APPROVED_DRAFT = "send_existing_approved_draft"
    LABEL_MUTATION = "label_mutation"


class GmailCapabilityClassification(str, Enum):
    """Fail-closed classification result for an unclassified Gmail tool id."""

    READ = "read"
    WRITE_OR_MATERIAL = "write_or_material"
    UNKNOWN = "unknown"


def provider_scopes_for_capability(capability: GmailCapability) -> tuple[str, ...]:
    """Provider OAuth scopes required by a capability (trusted port boundary only)."""

    if not isinstance(capability, GmailCapability):
        raise GmailContractError("capability must be GmailCapability")
    if capability is GmailCapability.READ:
        return (GMAIL_READONLY_SCOPE,)
    if capability is GmailCapability.CREATE_DRAFT:
        return (GMAIL_COMPOSE_SCOPE,)
    if capability is GmailCapability.SEND_EXISTING_APPROVED_DRAFT:
        # Gmail drafts.send accepts gmail.compose. Padiem still requires a
        # separate SEND capability + P01 approval because the provider scope
        # is broader than our authority.
        return (GMAIL_COMPOSE_SCOPE,)
    if capability is GmailCapability.LABEL_MUTATION:
        return (GMAIL_MODIFY_SCOPE,)
    raise GmailContractError("unsupported Gmail capability")


def core_auth_scopes_for_capability(capability: GmailCapability) -> tuple[str, ...]:
    """Bounded Core auth-scope tokens required by a capability."""

    if not isinstance(capability, GmailCapability):
        raise GmailContractError("capability must be GmailCapability")
    if capability is GmailCapability.READ:
        return (GMAIL_READONLY_AUTH_SCOPE,)
    if capability is GmailCapability.CREATE_DRAFT:
        return (GMAIL_COMPOSE_AUTH_SCOPE,)
    if capability is GmailCapability.SEND_EXISTING_APPROVED_DRAFT:
        return (GMAIL_COMPOSE_AUTH_SCOPE,)
    if capability is GmailCapability.LABEL_MUTATION:
        return (GMAIL_MODIFY_AUTH_SCOPE,)
    raise GmailContractError("unsupported Gmail capability")


def classify_gmail_tool_id(tool_id: str) -> GmailCapabilityClassification:
    """Classify a Gmail tool id; everything unregistered fails closed.

    Only the three promoted READ tool ids classify as READ. Unknown, future,
    or unregistered Gmail tool ids — including draft/send/label tools that do
    not exist in Core — classify as ``WRITE_OR_MATERIAL`` or ``UNKNOWN`` and
    must never receive a READ capability grant.
    """

    if not isinstance(tool_id, str) or not tool_id.strip():
        raise GmailContractError("tool_id must be a non-empty string")
    normalized = tool_id.strip()
    if not _SAFE_ID_RE.fullmatch(normalized):
        raise GmailContractError("tool_id must be a bounded safe identifier")
    if normalized in GMAIL_READ_TOOL_IDS or normalized in GMAIL_CANONICAL_TOOL_IDS:
        return GmailCapabilityClassification.READ
    if "draft" in normalized.lower() or "send" in normalized.lower() or "label" in normalized.lower():
        return GmailCapabilityClassification.WRITE_OR_MATERIAL
    return GmailCapabilityClassification.UNKNOWN


def capability_requires_p01_approval(capability: GmailCapability) -> bool:
    """Whether a capability requires existing P01 approval/evidence semantics.

    READ and draft creation never imply send authority; send and any material
    mutation require existing P01 approval semantics, which this contract
    never mints.
    """

    if not isinstance(capability, GmailCapability):
        raise GmailContractError("capability must be GmailCapability")
    return capability in (
        GmailCapability.SEND_EXISTING_APPROVED_DRAFT,
        GmailCapability.LABEL_MUTATION,
    )


@dataclass(frozen=True, slots=True)
class GmailCapabilityGrant:
    """One bounded capability grant fact for a connector binding.

    ``granted_capabilities`` carries only explicit capability values resolved
    server-side from grant references; it is never derived from caller JSON.
    Raw OAuth/access/refresh tokens can never appear here — the grant carries
    capability facts only.
    """

    connector_id: str
    binding_ref: str
    granted_capabilities: tuple[GmailCapability, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.connector_id, str) or not self.connector_id.strip():
            raise GmailContractError("connector_id must be a non-empty string")
        if not _SAFE_ID_RE.fullmatch(self.connector_id.strip()):
            raise GmailContractError("connector_id must be a bounded safe identifier")
        if not isinstance(self.binding_ref, str) or not _SAFE_ID_RE.fullmatch(self.binding_ref.strip()):
            raise GmailContractError("binding_ref must be a bounded safe identifier")
        if not isinstance(self.granted_capabilities, tuple) or any(
            not isinstance(item, GmailCapability) for item in self.granted_capabilities
        ):
            raise GmailContractError("granted_capabilities must contain GmailCapability values")
        if len(self.granted_capabilities) != len(set(self.granted_capabilities)):
            raise GmailContractError("granted_capabilities must be unique")

    def allows(self, capability: GmailCapability) -> bool:
        if not isinstance(capability, GmailCapability):
            raise GmailContractError("capability must be GmailCapability")
        return capability in self.granted_capabilities

    def send_authority(self) -> bool:
        """Whether this grant carries send authority.

        Send authority requires the explicit SEND capability. A CREATE_DRAFT
        capability alone never implies send, regardless of provider scopes.
        """

        return self.allows(GmailCapability.SEND_EXISTING_APPROVED_DRAFT)

    def safe_dict(self) -> dict[str, object]:
        return {
            "connector_id": self.connector_id,
            "binding_ref": self.binding_ref,
            "granted_capabilities": sorted(item.value for item in self.granted_capabilities),
            "send_authority": self.send_authority(),
            "raw_credentials_present": False,
            "oauth_token_present": False,
            "mints_approval_authority": False,
            "draft_implies_send": False,
        }


# Review-state mirrors of the B54 compatibility contract, kept fail-closed.
GMAIL_MCP_SEND_TOOL_SUPPORTED = False
GMAIL_MCP_CREATE_DRAFT_SUPPORTED = True
GMAIL_PROVIDER_COMPOSE_SCOPE_INCLUDES_SEND = True
GMAIL_PROVIDER_SCOPE_ALONE_GRANTS_PADIEM_SEND_AUTHORITY = False
GMAIL_SEND_REQUIRES_P01_APPROVAL = True

# No write/material tool is registered in Core in this slice.
GMAIL_WRITE_TOOLS_PRESENT = False
GMAIL_RAW_CREDENTIAL_IN_CORE = False


def gmail_capability_snapshot() -> dict[str, object]:
    """Deterministic, network-free snapshot of the promoted capability split."""

    return {
        "contract_version": "padiem-gmail-capability.v1",
        "capabilities": {
            "read": {
                "core_auth_scopes": list(core_auth_scopes_for_capability(GmailCapability.READ)),
                "requires_p01_approval": capability_requires_p01_approval(GmailCapability.READ),
            },
            "create_draft": {
                "core_auth_scopes": list(core_auth_scopes_for_capability(GmailCapability.CREATE_DRAFT)),
                "requires_p01_approval": capability_requires_p01_approval(GmailCapability.CREATE_DRAFT),
            },
            "send_existing_approved_draft": {
                "core_auth_scopes": list(
                    core_auth_scopes_for_capability(GmailCapability.SEND_EXISTING_APPROVED_DRAFT)
                ),
                "requires_p01_approval": capability_requires_p01_approval(
                    GmailCapability.SEND_EXISTING_APPROVED_DRAFT
                ),
            },
            "label_mutation": {
                "core_auth_scopes": list(core_auth_scopes_for_capability(GmailCapability.LABEL_MUTATION)),
                "requires_p01_approval": capability_requires_p01_approval(GmailCapability.LABEL_MUTATION),
            },
        },
        "read_tool_ids": list(GMAIL_READ_TOOL_IDS),
        "registered_write_tools": [],
        "draft_implies_send": False,
        "provider_scope_grants_padiem_authority": False,
        "mints_second_approval_authority": False,
        "raw_credentials_present": False,
        "live_provider_calls": 0,
        "production_activation": False,
    }


__all__ = [
    "GMAIL_COMPOSE_SCOPE",
    "GMAIL_MODIFY_SCOPE",
    "GMAIL_COMPOSE_AUTH_SCOPE",
    "GMAIL_MODIFY_AUTH_SCOPE",
    "GMAIL_READ_TOOL_IDS",
    "GmailCapability",
    "GmailCapabilityClassification",
    "GmailCapabilityGrant",
    "provider_scopes_for_capability",
    "core_auth_scopes_for_capability",
    "classify_gmail_tool_id",
    "capability_requires_p01_approval",
    "gmail_capability_snapshot",
    "GMAIL_MCP_SEND_TOOL_SUPPORTED",
    "GMAIL_MCP_CREATE_DRAFT_SUPPORTED",
    "GMAIL_PROVIDER_COMPOSE_SCOPE_INCLUDES_SEND",
    "GMAIL_PROVIDER_SCOPE_ALONE_GRANTS_PADIEM_SEND_AUTHORITY",
    "GMAIL_SEND_REQUIRES_P01_APPROVAL",
    "GMAIL_WRITE_TOOLS_PRESENT",
    "GMAIL_RAW_CREDENTIAL_IN_CORE",
]
