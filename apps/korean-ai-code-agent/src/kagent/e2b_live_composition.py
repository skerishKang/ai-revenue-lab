"""Source-only composition root for the existing E2B live transport (#2923, parent #1405).

``e2b_provider_transport.py`` already owns every live-layer authority: the owner decision
(``E2BLiveAuthorization``), the binding-name-only credential port
(``EnvironmentE2BCredentialPort``), the pinned-origin request port
(``StdlibE2BHttpRequestPort``) and the transport that checks the gate before it opens a socket
(``LiveE2BSandboxTransport``). ``e2b_sandbox.py`` owns the launch adapter
(``E2BCloudM1Adapter``). What no file owned was the one place that assembles them, which is why the
canonical flag ``E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED`` read ``False``.

This module is that place, and it is deliberately powerless:

```text
WHAT THIS FILE IS
  One composition root that wires the five existing objects above from server-owned config.

WHAT IT IS NOT
  Not an authorization and not a factory that can arm one. Assembling the objects changes nothing
  about whether a provider request may be made: the gate is still held by the repository flags
  (credential binding, live readiness, live wire verification), by the owner's authorization record
  and by the owner's provider-selection decision. Every one of those is still closed after this
  module runs, so a composed object refuses before any I/O.
```

Three separations are load-bearing, and each one is tested rather than asserted in prose:

* **Construction is not resolution.** ``EnvironmentE2BCredentialPort.resolve`` is the only path to
  a credential value, and building the port does not call it. A composed object performs zero
  credential reads, zero provider requests and zero sandbox allocations; the composed clock is not
  called either. The single local side effect is the stdlib TLS trust store the pinned-origin port
  loads for its SSL context — a local read, never a provider request and never a credential read.
* **The endpoint and the binding are source-owned.** This module takes no base URL, host, port,
  path, environment-variable name, binding name or credential value, and its parameter surface is
  pinned as data (``E2B_COMPOSITION_PARAMETERS``) so a review can diff it instead of trusting prose.
  The only endpoint in the assembled stack is ``E2B_API_HOST`` and the only binding name is
  ``E2B_CREDENTIAL_BINDING_NAME``; both are read from the transport module rather than restated.
* **One authority per concern.** No transport, adapter, credential port or request port is defined
  here — the composed objects are the canonical classes, and ``E2BLiveComposition.__post_init__``
  refuses to hold anything else. The gate flags are read through the transport module at projection
  time so this file cannot drift into a second copy of them.

An owner authorization is still required and still insufficient: passing a fully-formed record with
``owner_authorized`` and ``provider_formally_selected`` both ``True`` leaves the gate shut, because
the repository flags that record credential binding, live readiness and live wire verification are
the reviewed part of the decision. That is the property ``MISSING_AUTHORIZATION_FAILS_CLOSED`` and
``INVALID_AUTHORIZATION_FAILS_CLOSED`` name.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import e2b_provider_transport as _transport
from .e2b_provider_transport import (
    E2B_API_HOST,
    E2B_CREDENTIAL_BINDING_NAME,
    E2BLiveAuthorization,
    E2BWireError,
    EnvironmentE2BCredentialPort,
    LiveE2BSandboxTransport,
    StdlibE2BHttpRequestPort,
)
from .e2b_sandbox import (
    E2B_PROVIDER_CANDIDATE,
    E2B_REAL_PROVIDER_CALLS,
    E2B_REAL_SANDBOX_ALLOCATIONS,
    E2BCloudM1Adapter,
)
from .sandbox import SandboxUnavailableError

E2B_LIVE_COMPOSITION_CONTRACT_VERSION = "claw-e2b-live-composition.v1"

#: Server-owned Cloud M1 template. The composition root takes no template argument, so the only
#: route to a different image is a reviewed edit to this constant.
E2B_CLOUD_M1_TEMPLATE = "claw-m1-base"

#: The composition root's entire caller surface, pinned as data. Neither entry can carry an
#: endpoint, a host, a port, a binding name, an environment-variable name or a credential value.
E2B_COMPOSITION_PARAMETERS = ("authorization", "clock")

#: Construction-time I/O counters. Kept as data a reviewer can assert against instead of trusting
#: the prose above; the tests hold them by spying rather than by reading them back.
E2B_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS = 0
E2B_COMPOSITION_CONSTRUCTION_CREDENTIAL_READS = 0
E2B_COMPOSITION_CONSTRUCTION_SANDBOX_ALLOCATIONS = 0


def _no_wall_clock() -> datetime:
    """Refuse to invent a clock, exactly like the transport's own default.

    A composed object may not read a wall clock of its own accord: an injected clock is part of a
    caller's decision, and a default that silently read one would let the assembled stack act on
    time nobody chose.
    """
    raise SandboxUnavailableError(
        "E2B live composition requires an injected clock; it never reads a wall clock itself"
    )


@dataclass(frozen=True, slots=True)
class E2BLiveComposition:
    """The assembled stack, in the order the transport consumes it.

    Holding the objects is not permission to use them, so the gate state is projected rather than
    summarised optimistically: ``gate_armed`` stays ``False`` for every instance that can exist in
    this build.
    """

    authorization: E2BLiveAuthorization | None
    credential_port: EnvironmentE2BCredentialPort
    request_port: StdlibE2BHttpRequestPort
    transport: LiveE2BSandboxTransport
    adapter: E2BCloudM1Adapter

    def __post_init__(self) -> None:
        # Structural defence against a second stack: a composition that held a look-alike port,
        # transport or adapter would be a new authority wearing the canonical names.
        if self.authorization is not None and not isinstance(self.authorization, E2BLiveAuthorization):
            raise E2BWireError("authorization must be an E2BLiveAuthorization or omitted")
        if not isinstance(self.credential_port, EnvironmentE2BCredentialPort):
            raise E2BWireError("the composition root wires the canonical credential port only")
        if not isinstance(self.request_port, StdlibE2BHttpRequestPort):
            raise E2BWireError("the composition root wires the canonical pinned-origin port only")
        if not isinstance(self.transport, LiveE2BSandboxTransport):
            raise E2BWireError("the composition root wires the canonical live transport only")
        if not isinstance(self.adapter, E2BCloudM1Adapter):
            raise E2BWireError("the composition root wires the canonical Cloud M1 adapter only")

    @property
    def provider_candidate(self) -> Any:
        return self.adapter.provider_candidate

    @property
    def credential_binding_name(self) -> str:
        return self.credential_port.binding_name

    @property
    def blocked_reasons(self) -> tuple[str, ...]:
        if self.authorization is None:
            return ("no owner authorization was supplied to this composition",)
        return self.authorization.blocked_reasons

    @property
    def gate_armed(self) -> bool:
        return self.authorization is not None and self.authorization.armed

    def safe_dict(self) -> dict[str, Any]:
        """Projection safe to log: the binding name, never a value or a resolved byte."""
        return {
            "contract_version": E2B_LIVE_COMPOSITION_CONTRACT_VERSION,
            "provider_candidate": E2B_PROVIDER_CANDIDATE.value,
            # Read through the transport module, not copied: one flag, one authority.
            "composition_root_wired": _transport.E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED,
            "credential_bound": _transport.LIVE_CREDENTIAL_BOUND,
            "live_execution_ready": _transport.E2B_LIVE_EXECUTION_READY,
            "wire_contract_live_verified": _transport.E2B_WIRE_CONTRACT_LIVE_VERIFIED,
            "owner_live_gate_required": _transport.E2B_OWNER_LIVE_GATE_REQUIRED,
            "gate_armed": self.gate_armed,
            "blocked_reasons": list(self.blocked_reasons),
            "provider_endpoint": E2B_API_HOST,
            "credential_binding_name": E2B_CREDENTIAL_BINDING_NAME,
            "credential_value": None,
            "cloud_m1_template": E2B_CLOUD_M1_TEMPLATE,
            "request_port": StdlibE2BHttpRequestPort.__name__,
            "credential_port": EnvironmentE2BCredentialPort.__name__,
            "transport": LiveE2BSandboxTransport.__name__,
            "adapter": E2BCloudM1Adapter.__name__,
            "composition_construction_provider_requests": (
                E2B_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS
            ),
            "composition_construction_credential_reads": (
                E2B_COMPOSITION_CONSTRUCTION_CREDENTIAL_READS
            ),
            "composition_construction_sandbox_allocations": (
                E2B_COMPOSITION_CONSTRUCTION_SANDBOX_ALLOCATIONS
            ),
            "real_provider_calls": E2B_REAL_PROVIDER_CALLS,
            "real_sandbox_allocations": E2B_REAL_SANDBOX_ALLOCATIONS,
            "production_claim": False,
        }


def build_e2b_live_composition(
    *,
    authorization: E2BLiveAuthorization | None = None,
    clock: Callable[[], datetime] | None = None,
) -> E2BLiveComposition:
    """Wire the canonical E2B stack from server-owned config. Performs no I/O of its own.

    ``authorization`` is the owner's record of decision and ``clock`` is the caller's time source;
    everything else — endpoint, binding name, template, ports, transport, adapter — comes from
    source. Supplying neither is the normal state, and it is also the safest one: the composed
    object still refuses every verb because the repository flags that record credential binding,
    live readiness and live wire verification are closed.
    """
    if authorization is not None and not isinstance(authorization, E2BLiveAuthorization):
        raise E2BWireError("authorization must be an E2BLiveAuthorization or omitted")
    if clock is not None and not callable(clock):
        raise E2BWireError("clock must be callable or omitted")
    observed_clock = clock if clock is not None else _no_wall_clock

    # Construction only. The credential port holds the allowlisted binding *name*; resolve() is the
    # value path and stays untouched here.
    credential_port = EnvironmentE2BCredentialPort()
    request_port = StdlibE2BHttpRequestPort()
    transport = LiveE2BSandboxTransport(
        request_port=request_port,
        credential_port=credential_port,
        authorization=authorization,
        clock=observed_clock,
    )
    adapter = E2BCloudM1Adapter(
        transport, template=E2B_CLOUD_M1_TEMPLATE, clock=observed_clock
    )
    return E2BLiveComposition(
        authorization=authorization,
        credential_port=credential_port,
        request_port=request_port,
        transport=transport,
        adapter=adapter,
    )


__all__ = [
    "E2B_CLOUD_M1_TEMPLATE",
    "E2B_COMPOSITION_CONSTRUCTION_CREDENTIAL_READS",
    "E2B_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS",
    "E2B_COMPOSITION_CONSTRUCTION_SANDBOX_ALLOCATIONS",
    "E2B_COMPOSITION_PARAMETERS",
    "E2B_LIVE_COMPOSITION_CONTRACT_VERSION",
    "E2BLiveComposition",
    "build_e2b_live_composition",
]
