"""#3094 — the concrete read-only local-access truth source over #3080.

The #3094 route exposes one typed seam (``ClawLocalAccessTruthSource``) and a
fail-closed unconfigured default. This module supplies the concrete source that
a trusted runtime may compose: it reads canonical #3080 device facts from an
approved trusted boundary and lets the canonical authority decide everything.

Authority boundary
------------------
* ONLINE is never decided here. Every projection asks
  ``kagent.local_agent_server_projection.project_server_backed_online_binding``
  (#3080 owns this fact) to judge binding + session + heartbeat correlation and
  freshness. When that projection refuses, the source falls back to the
  binding's own canonical ``DeviceLifecycle`` state — also #3080-owned truth —
  and never upgrades it.
* The Web vocabulary translation stays in ``app.claw_local_projection`` (G4).
  This module only reports canonical state values to the route; it never maps
  them to Web labels itself.
* The handoff value is forwarded verbatim from the trusted boundary when the
  projected device is usable, and dropped whole otherwise. It is never minted,
  parsed, decoded, truncated or rewritten here.
* Owner and workspace scope arrive only as the server-derived ``owner_id`` the
  route already authenticated. No browser-supplied account/workspace authority
  exists on this path: the source receives no request object at all.
* Read-only: no pairing challenge, no credential write, no session, no store
  mutation of any kind.

Contract markers
----------------
``DEVICE_STATE_SOURCE = "canonical:kagent.local_agent_pairing.DeviceLifecycle"``
``ONLINE_DECISION_AUTHORITY = "kagent.local_agent_server_projection"``
``SECOND_DEVICE_LIFECYCLE_AUTHORITY = False``
``NEW_LIFECYCLE_STATE_CREATED = 0``
``HANDOFF_VALUE_MINTED_OR_PARSED = False``
``OWNER_SCOPE_SOURCE = "server_session_identity_only"``
``MUTATION = False``
``PRODUCTION_MUTATION = False``
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Protocol

from kagent.contracts import ContractError
from kagent.local_agent_control_plane_runtime import ControlPlaneHeartbeatReceipt
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from kagent.local_agent_server_projection import project_server_backed_online_binding

__all__ = [
    "TrustedLocalAccessDeviceTruthPort",
    "CanonicalClawLocalAccessTruthSource",
]


class TrustedLocalAccessDeviceTruthPort(Protocol):
    """The one approved trusted boundary this source may read.

    Implementations are the worker/runtime composition's trusted #3080
    broker-authority port: they answer with the canonical device facts they
    already own for the server-authenticated owner, or with nothing. The port
    receives only what the route derived server-side (owner id, conversation
    id, now) — never browser-controlled account or workspace authority.
    """

    def device_truth(
        self,
        *,
        owner_id: str,
        conversation_id: str,
        now: datetime,
    ) -> Any:  # pragma: no cover - protocol declaration
        ...


def _read(source: Any, key: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _exact_instance(value: Any, expected: type) -> bool:
    # Exact type, not isinstance: a boundary-supplied subclass or stand-in is
    # not a canonical fact this source is allowed to project.
    return type(value) is expected


class CanonicalClawLocalAccessTruthSource:
    """Read one owner-scoped canonical projection from the trusted boundary.

    ``configured`` is true by construction: an instance only exists after the
    composition seam verified the trusted boundary. Every failure mode below
    collapses to "no projection" (``None``), which the route already reports as
    ``available: false`` with a bounded reason — never as a guessed device.
    """

    configured = True

    def __init__(self, *, port: TrustedLocalAccessDeviceTruthPort) -> None:
        if not callable(getattr(port, "device_truth", None)):
            raise TypeError("local access trusted port must expose device_truth()")
        self._port = port

    async def project_local_access(
        self,
        *,
        owner_id: str,
        conversation_id: str,
        now: datetime,
    ) -> dict[str, Any] | None:
        truth = self._port.device_truth(
            owner_id=owner_id,
            conversation_id=conversation_id,
            now=now,
        )
        if truth is None:
            return None

        binding = _read(truth, "binding")
        if not _exact_instance(binding, DeviceBinding):
            # No canonical device fact for this owner: assert nothing.
            return None

        canonical_state = self._canonical_state(
            binding=binding,
            session=_read(truth, "session"),
            heartbeat=_read(truth, "heartbeat"),
            now=now,
        )

        handoff_value = _read(truth, "handoff_value")
        if canonical_state is not DeviceLifecycle.ONLINE:
            # A handoff produced for a device the canonical authority does not
            # consider usable is never forwarded: the value is dropped whole.
            handoff_value = None

        return {
            "canonical_state": canonical_state,
            "device_name": _read(truth, "device_name"),
            "platform": _read(truth, "platform"),
            "run_id": _read(truth, "run_id"),
            "task_id": _read(truth, "task_id"),
            "requires_local_access": _read(truth, "requires_local_access") is True,
            "required_capabilities": _read(truth, "required_capabilities"),
            "desktop_installed": _read(truth, "desktop_installed") is True,
            "handoff_value": handoff_value if isinstance(handoff_value, str) else None,
            "handoff_conversation_id": _read(truth, "handoff_conversation_id"),
        }

    @staticmethod
    def _canonical_state(
        *,
        binding: DeviceBinding,
        session: Any,
        heartbeat: Any,
        now: datetime,
    ) -> Any:
        """The canonical lifecycle, decided by #3080 alone.

        The server-backed projection is the only path to a freshly judged
        ONLINE. If it refuses (unrelated/expired session or heartbeat, wrong
        credential generation, ...), the binding's own canonical state stands —
        it is #3080-owned truth, not a B62 judgement — and nothing is upgraded.
        """

        if _exact_instance(session, DeviceSession) and _exact_instance(
            heartbeat, ControlPlaneHeartbeatReceipt
        ):
            try:
                projected = project_server_backed_online_binding(
                    binding=binding,
                    session=session,
                    heartbeat=heartbeat,
                    now=now,
                )
                return projected.state
            except ContractError:
                pass
        return binding.state


# ---------------------------------------------------------------------------
# Contract markers
# ---------------------------------------------------------------------------

DEVICE_STATE_SOURCE = "canonical:kagent.local_agent_pairing.DeviceLifecycle"
ONLINE_DECISION_AUTHORITY = "kagent.local_agent_server_projection"
SECOND_DEVICE_LIFECYCLE_AUTHORITY = False
NEW_LIFECYCLE_STATE_CREATED = 0
HANDOFF_VALUE_MINTED_OR_PARSED = False
HANDOFF_VALUE_FORWARDED_VERBATIM_OR_DROPPED = True
OWNER_SCOPE_SOURCE = "server_session_identity_only"
MUTATION = False
PRODUCTION_MUTATION = False
