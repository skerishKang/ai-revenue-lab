"""#3094 — worker/runtime composition of the concrete local-access source.

Mirrors the established trusted-composition pattern (``claw_p01_composition``):
the deployed Python Worker has no process environment, so the source is built
only from trusted Worker bindings resolved by the composition root. This module
never touches a process environment and never reads request input.

The trusted boundary is the ``LOCAL_AGENT_BROKER_AUTHORITY_SERVICE`` binding
pointing at the canonical Local Agent broker Worker
(``packages/padiem-control-plane/local_agent_broker_worker.py``). That
entrypoint's ``device_truth`` RPC — the narrow read-only, owner-scoped canonical
device-fact projection — is the only thing this composition may consume. A
compatible binding is wrapped into the typed port the canonical source reads;
any other state — binding absent (today's deploy), binding without the
``device_truth`` method, or a construction failure — yields ``None`` plus one
bounded public-safe diagnostic, and the app keeps the fail-closed unconfigured
source installed by ``create_app``. A missing trusted runtime must never become
a guessed device state.

Contract markers
----------------
``TRUSTED_BOUNDARY = "worker:LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"``
``CONSUMED_BROKER_API = "device_truth RPC (canonical broker Worker)"``
``COMPOSITION_INPUT_SOURCE = "trusted_worker_bindings_only"``
``FAIL_CLOSED_WHEN_BOUNDARY_ABSENT = True``
``MUTATION = False``
``PRODUCTION_MUTATION = False``
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .claw_local_access_source import CanonicalClawLocalAccessTruthSource
from .worker_config import (
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
    binding_value,
)

__all__ = [
    "LOCAL_ACCESS_DIAG_BOUNDING_ABSENT",
    "LOCAL_ACCESS_DIAG_PORT_INCOMPATIBLE",
    "LOCAL_ACCESS_DIAG_CONSTRUCTION_FAILED",
    "BrokerAuthorityDeviceTruthPort",
    "build_claw_local_access_source",
    "build_claw_local_access_source_with_diagnostic",
    "build_mesh_presence_generation_resolver",
]

# Bounded public-safe diagnostics. Fixed constants only: exception messages,
# binding values and any trusted-boundary detail are never propagated.
LOCAL_ACCESS_DIAG_BOUNDING_ABSENT = "local_access_authority_binding_absent"
LOCAL_ACCESS_DIAG_PORT_INCOMPATIBLE = "local_access_authority_port_incompatible"
LOCAL_ACCESS_DIAG_CONSTRUCTION_FAILED = "local_access_source_construction_failed"


class BrokerAuthorityDeviceTruthPort:
    """Typed port adapter over the canonical broker ``device_truth`` RPC.

    The Worker service binding exposes the broker Worker entrypoint's methods
    directly (the same RPC surface the identity authority consumes). This
    adapter is the only translation between that surface and the typed port
    protocol: it forwards the server-derived owner identity, awaits the RPC
    result and hands the envelope back untouched.
    """

    configured = True

    def __init__(self, binding: Any) -> None:
        self._binding = binding

    async def device_truth(
        self,
        *,
        owner_id: str,
        conversation_id: str,
        now: datetime,
    ) -> Any:
        del conversation_id, now  # the broker scopes by owner identity and its own clock
        result = self._binding.device_truth({"account_ref": owner_id})
        if result is not None and hasattr(result, "__await__"):
            result = await result
        return result


def build_claw_local_access_source_with_diagnostic(
    env: Any,
    presence_store: Any = None,
) -> tuple[CanonicalClawLocalAccessTruthSource | None, str | None]:
    """Compose the concrete source from the trusted binding, or fail closed.

    Returns ``(source, None)`` when the trusted boundary is present and
    compatible, otherwise ``(None, diagnostic)`` where the diagnostic is one
    fixed constant above. The caller keeps whatever fail-closed default the
    app factory already installed.
    """

    boundary = binding_value(env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME)
    if boundary is None:
        return None, LOCAL_ACCESS_DIAG_BOUNDING_ABSENT
    try:
        port = getattr(boundary, "device_truth")
    except Exception:
        # Even reading the port must not explode the composition root: a
        # hostile or broken boundary is just an incompatible one.
        return None, LOCAL_ACCESS_DIAG_PORT_INCOMPATIBLE
    if not callable(port):
        # A binding without the canonical broker's device_truth RPC cannot
        # serve this panel; no second source may be invented for it.
        return None, LOCAL_ACCESS_DIAG_PORT_INCOMPATIBLE
    try:
        source = CanonicalClawLocalAccessTruthSource(
            port=BrokerAuthorityDeviceTruthPort(boundary),
            presence_store=presence_store,
        )
    except Exception:
        return None, LOCAL_ACCESS_DIAG_CONSTRUCTION_FAILED
    return source, None


def build_claw_local_access_source(
    env: Any, presence_store: Any = None,
) -> CanonicalClawLocalAccessTruthSource | None:
    """Same fail-closed composition, without the diagnostic."""

    source, _ = build_claw_local_access_source_with_diagnostic(
        env, presence_store=presence_store,
    )
    return source


def build_mesh_presence_generation_resolver(env: Any) -> Any:
    """#5553 — stamp a presence beat with its canonical credential generation.

    This reads the SAME owner-scoped ``device_truth`` RPC the access source
    consumes; it never invents a device lookup, an account or a generation.
    The resolved binding must be the exact device the beat named. Requirement 6:
    absent/unresolved Broker registration returns None; the authenticated poll
    still records a source=mesh receipt with NULL generation. It never invents
    a Broker generation or a credential.
    """

    boundary = binding_value(env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME)
    if boundary is None:
        return None
    port = getattr(boundary, "device_truth", None)
    if not callable(port):
        return None

    async def resolve(*, account_ref: str, device_id: str) -> int | None:
        try:
            result = port({"account_ref": account_ref})
            if hasattr(result, "__await__"):
                result = await result
        except Exception:
            return None
        if (
            not isinstance(result, dict)
            or result.get("ok") is not True
            or result.get("available") is not True
        ):
            return None
        facts = result.get("device_truth")
        binding = facts.get("binding") if isinstance(facts, dict) else None
        if not isinstance(binding, dict) or binding.get("device_id") != device_id:
            return None
        generation = binding.get("credential_generation")
        if type(generation) is not int or not 1 <= generation <= 1_000_000:
            return None
        return generation

    return resolve


# ---------------------------------------------------------------------------
# Contract markers
# ---------------------------------------------------------------------------

TRUSTED_BOUNDARY = "worker:LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"
CONSUMED_BROKER_API = "device_truth RPC (canonical broker Worker)"
COMPOSITION_INPUT_SOURCE = "trusted_worker_bindings_only"
FAIL_CLOSED_WHEN_BOUNDARY_ABSENT = True
MUTATION = False
PRODUCTION_MUTATION = False
