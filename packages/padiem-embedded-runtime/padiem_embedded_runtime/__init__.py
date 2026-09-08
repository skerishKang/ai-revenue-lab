"""IP-SIDECAR — Padiem Embedded AI Runtime (S5 attachment input presentation).

Public, browser-safe boundary only. No Engine transport, no provider calls,
no browser network fetch, no File/Blob byte reads, no ref minting, no
secrets, no product semantics.
"""

from __future__ import annotations

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
    "AttachmentRefPresentation",
    "BootstrapConfig",
    "BridgeOutcome",
    "CitationPresentation",
    "CitationRef",
    "DeterministicFakeEnginePort",
    "EmbeddedShell",
    "EnginePort",
    "HostContextEnvelope",
    "HostSafeResult",
    "IntegrationDiagnostics",
    "PresentedCitation",
    "PresentedSelection",
    "PublicEvent",
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
    "normalize_citation",
    "normalize_selection",
    "parse_bootstrap_config",
    "present_attachment_ref",
    "present_citations",
    "present_selections",
    "present_upload_lifecycle",
    "project_event",
]
