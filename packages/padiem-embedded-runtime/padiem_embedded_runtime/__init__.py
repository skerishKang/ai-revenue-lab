"""IP-SIDECAR — Padiem Embedded AI Runtime (S4 evidence/citation presentation).

Public, browser-safe boundary only. No Engine transport, no provider calls,
no browser network fetch, no secrets, no product semantics.
"""

from __future__ import annotations

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
    "PublicEvent",
    "SessionProjection",
    "SidecarContractError",
    "VersionCompatibility",
    "build_diagnostics",
    "check_contract_compatibility",
    "envelop_host_context",
    "intake_host_payload",
    "normalize_citation",
    "parse_bootstrap_config",
    "present_citations",
    "project_event",
]
