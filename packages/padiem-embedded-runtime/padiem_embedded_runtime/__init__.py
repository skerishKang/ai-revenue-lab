"""IP-SIDECAR — Padiem Embedded AI Runtime (S3 host-context bridge).

Public, browser-safe boundary only. No Engine transport, no provider calls,
no secrets, no product semantics.
"""

from __future__ import annotations

from .bootstrap import BootstrapConfig, parse_bootstrap_config
from .bridge import BridgeOutcome, SessionProjection, intake_host_payload
from .compatibility import VersionCompatibility, check_contract_compatibility
from .diagnostics import IntegrationDiagnostics, build_diagnostics
from .engine_port import DeterministicFakeEnginePort, EnginePort
from .errors import SidecarContractError
from .events import PublicEvent, project_event
from .host_context import HostContextEnvelope, envelop_host_context
from .lifecycle import EmbeddedShell, HostSafeResult

__all__ = [
    "BootstrapConfig",
    "BridgeOutcome",
    "DeterministicFakeEnginePort",
    "EmbeddedShell",
    "EnginePort",
    "HostContextEnvelope",
    "HostSafeResult",
    "IntegrationDiagnostics",
    "PublicEvent",
    "SessionProjection",
    "SidecarContractError",
    "VersionCompatibility",
    "build_diagnostics",
    "check_contract_compatibility",
    "envelop_host_context",
    "intake_host_payload",
    "parse_bootstrap_config",
    "project_event",
]
