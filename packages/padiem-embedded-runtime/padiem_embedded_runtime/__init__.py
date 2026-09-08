"""IP-SIDECAR — Padiem Embedded AI Runtime (S6 approval presentation).

Public, browser-safe boundary only. No Engine transport, no provider calls,
no browser network fetch, no File/Blob byte reads, no ref minting, no
approval verification or authority minting, no action execution, no
secrets, no product semantics.
"""

from __future__ import annotations

from .approval_presentation import (
    ApprovalProposal,
    ApprovalStatePresentation,
    ConfirmationIntentPresentation,
    PresentedProposal,
    ProposalPresentation,
    PublicReferenceDisplay,
    normalize_approval_proposal,
    present_approval_proposals,
    present_approval_state,
    present_confirmation_intent,
    present_public_reference,
)
from .attachment_input import (
    AttachmentRefPresentation,
    PresentedSelection,
    SelectionDescriptor,
    SelectionPresentation,
    UploadLifecyclePresentation,
    normalize_selection,
    present_attachment_ref,
    present_selections,
    present_upload_lifecycle,
)
from .bootstrap import BootstrapConfig, parse_bootstrap_config
from .bridge import BridgeOutcome, SessionProjection, intake_host_payload
from .compatibility import VersionCompatibility, check_contract_compatibility
from .diagnostics import IntegrationDiagnostics, build_diagnostics
from .engine_port import DeterministicFakeEnginePort, EnginePort
from .errors import SidecarContractError
from .events import PublicEvent, project_event
from .evidence import (
    CitationPresentation,
    CitationRef,
    PresentedCitation,
    normalize_citation,
    present_citations,
)
from .host_context import HostContextEnvelope, envelop_host_context
from .lifecycle import EmbeddedShell, HostSafeResult

__all__ = [
    "ApprovalProposal",
    "ApprovalStatePresentation",
    "AttachmentRefPresentation",
    "BootstrapConfig",
    "BridgeOutcome",
    "CitationPresentation",
    "CitationRef",
    "ConfirmationIntentPresentation",
    "DeterministicFakeEnginePort",
    "EmbeddedShell",
    "EnginePort",
    "HostContextEnvelope",
    "HostSafeResult",
    "IntegrationDiagnostics",
    "PresentedCitation",
    "PresentedProposal",
    "PresentedSelection",
    "ProposalPresentation",
    "PublicEvent",
    "PublicReferenceDisplay",
    "SessionProjection",
    "SelectionDescriptor",
    "SelectionPresentation",
    "SidecarContractError",
    "UploadLifecyclePresentation",
    "VersionCompatibility",
    "build_diagnostics",
    "check_contract_compatibility",
    "envelop_host_context",
    "intake_host_payload",
    "normalize_approval_proposal",
    "normalize_citation",
    "normalize_selection",
    "parse_bootstrap_config",
    "present_approval_proposals",
    "present_approval_state",
    "present_attachment_ref",
    "present_citations",
    "present_confirmation_intent",
    "present_public_reference",
    "present_selections",
    "present_upload_lifecycle",
    "project_event",
]
