"""IP-SIDECAR — Padiem Embedded AI Runtime (S2 minimal contract).

Public, browser-safe boundary only. No Engine transport, no provider calls,
no secrets, no product semantics.
"""

from __future__ import annotations

from .bootstrap import BootstrapConfig, parse_bootstrap_config
from .engine_port import DeterministicFakeEnginePort, EnginePort
from .errors import SidecarContractError
from .events import PublicEvent, project_event
from .host_context import HostContextEnvelope, envelop_host_context
from .lifecycle import EmbeddedShell, HostSafeResult

__all__ = [
    "BootstrapConfig",
    "DeterministicFakeEnginePort",
    "EmbeddedShell",
    "EnginePort",
    "HostContextEnvelope",
    "HostSafeResult",
    "PublicEvent",
    "SidecarContractError",
    "envelop_host_context",
    "parse_bootstrap_config",
    "project_event",
]
