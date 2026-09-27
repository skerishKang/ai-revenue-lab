"""#3094 — the concrete read-only local-access truth source over #3080.

The #3094 route exposes one typed seam (``ClawLocalAccessTruthSource``) and a
fail-closed unconfigured default. This module supplies the concrete source that
the worker/runtime composition builds over the **actual canonical broker
boundary**: the ``device_truth`` RPC of the #3080 Local Agent broker Worker
(``packages/padiem-control-plane/local_agent_broker_worker.py``), consumed
through the trusted ``LOCAL_AGENT_BROKER_AUTHORITY_SERVICE`` binding.

Authority boundary
------------------
* The broker owns the facts. Its ``device_truth`` projection reports the
  owner-scoped canonical #3080 facts (binding, newest session, server-owned
  heartbeat last-seen) with a broker-side canonical state that can only be
  ``paired_offline`` / ``credential_expired`` / ``revoked`` — never
  ``online``.
* ONLINE is decided by the existing canonical rule only:
  ``kagent.local_agent_server_projection.project_server_backed_online_binding``
  judges binding + session + heartbeat correlation and freshness — and is
  attempted **only** for a broker-reported ``paired_offline`` device. A device
  the broker reports as ``revoked`` or ``credential_expired`` returns that
  exact fail-closed state without ever reaching the ONLINE rule, so an expired
  credential cannot be resurrected by a still-current session or heartbeat.
  When the projection refuses, the source falls back to the broker-reported
  canonical state, and a fallback that would ever read ``online`` is refused
  outright (fail closed from ONLINE on projection failure).
* The Web vocabulary translation stays in ``app.claw_local_projection`` (G4).
  This module only reports canonical state values to the route; it never maps
  them to Web labels itself.
* The handoff value is forwarded verbatim from the broker envelope when the
  projected device is usable, and dropped whole otherwise. It is never minted,
  parsed, decoded, truncated or rewritten here.
* Owner and workspace scope arrive only as the server-derived ``owner_id`` the
  route already authenticated. No browser-supplied account/workspace authority
  exists on this path: the source receives no request object at all.
* Read-only: no pairing challenge, no credential write, no session, no store
  mutation of any kind.

Contract markers
----------------
``DEVICE_STATE_SOURCE = "canonical:LOCAL_AGENT_BROKER_AUTHORITY device_truth RPC"``
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
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from kagent.contracts import ContractError
from kagent.local_agent_control_plane_runtime import ControlPlaneHeartbeatReceipt
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from kagent.local_agent_server_projection import project_server_backed_online_binding

__all__ = [
    "TrustedLocalAccessDeviceTruthPort",
    "CanonicalClawLocalAccessTruthSource",
]

# The only broker-reported canonical states this source may consume. The
# canonical broker cannot report "online" — a second ONLINE authority is
# forbidden — and any other value fails closed.
_BROKER_CANONICAL_STATES: Mapping[str, DeviceLifecycle] = MappingProxyType(
    {
        "paired_offline": DeviceLifecycle.PAIRED_OFFLINE,
        "credential_expired": DeviceLifecycle.CREDENTIAL_EXPIRED,
        "revoked": DeviceLifecycle.REVOKED,
    }
)

_TEXT_MAX = 512


class TrustedLocalAccessDeviceTruthPort(Protocol):
    """The one approved trusted boundary this source may read.

    Implementations wrap the real ``device_truth`` RPC of the canonical Local
    Agent broker Worker exposed through the trusted service binding. The port
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


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed or len(trimmed) > _TEXT_MAX:
        return None
    return trimmed


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


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
        envelope = _mapping(
            await _maybe_await(
                self._port.device_truth(
                    owner_id=owner_id,
                    conversation_id=conversation_id,
                    now=now,
                )
            )
        )
        if envelope is None or envelope.get("ok") is not True:
            return None
        if envelope.get("available") is not True:
            return None
        facts = _mapping(envelope.get("device_truth"))
        if facts is None:
            return None

        canonical_state = self._canonical_state(facts, now=now)
        if canonical_state is None:
            return None

        handoff_value = facts.get("handoff_value")
        if canonical_state is not DeviceLifecycle.ONLINE:
            # A handoff produced for a device the canonical authority does not
            # consider usable is never forwarded: the value is dropped whole.
            handoff_value = None

        return {
            "canonical_state": canonical_state,
            "device_name": None,
            "platform": None,
            "run_id": None,
            "task_id": None,
            "requires_local_access": True,
            "required_capabilities": ["local_computer"],
            # Never fabricated: the broker reports desktop installation when
            # it knows it; absent evidence is reported as not installed, which
            # renders as install guidance rather than an openable handoff.
            "desktop_installed": facts.get("desktop_installed") is True,
            "handoff_value": handoff_value if isinstance(handoff_value, str) else None,
            "handoff_conversation_id": None,
        }

    @staticmethod
    def _canonical_state(facts: Mapping[str, Any], *, now: datetime) -> DeviceLifecycle | None:
        """The canonical lifecycle for the broker's facts, decided by #3080.

        The single invariant: only a broker-reported ``paired_offline`` device
        may attempt the server-backed ONLINE projection. A device the broker
        already reports as ``revoked`` or ``credential_expired`` — or any
        unknown vocabulary — returns that exact fail-closed state and never
        reaches the ONLINE rule, so an expired credential cannot be resurrected
        into a connected claim by a still-current session or heartbeat.
        """

        broker_state = facts.get("canonical_state")
        fallback = _BROKER_CANONICAL_STATES.get(broker_state) if isinstance(broker_state, str) else None
        if fallback is None:
            # Unknown broker vocabulary: assert nothing rather than guess.
            return None
        if fallback is not DeviceLifecycle.PAIRED_OFFLINE:
            # revoked / credential_expired: fail closed as the broker reported.
            # The #3080 rule is never invoked, so no current session or
            # heartbeat can promote these states to ONLINE.
            return fallback

        binding_facts = _mapping(facts.get("binding"))
        session_facts = _mapping(facts.get("session"))
        if binding_facts is None:
            return None

        try:
            binding = DeviceBinding(
                device_id=_text(binding_facts.get("device_id")) or "",
                binding_ref=_text(binding_facts.get("binding_ref")) or "",
                account_ref=_text(binding_facts.get("account_ref")) or "",
                workspace_ref=_text(binding_facts.get("workspace_ref")) or "",
                credential_ref="local-access-projection-only",
                credential_generation=_int(binding_facts.get("credential_generation")) or 0,
                issued_at=_parse_iso(binding_facts.get("issued_at")) or now,
                credential_expires_at=_parse_iso(binding_facts.get("credential_expires_at")) or now,
                state=DeviceLifecycle.PAIRED_OFFLINE,
            )
            session = None
            heartbeat = None
            last_seen = _parse_iso(facts.get("heartbeat_last_seen_at"))
            if session_facts is not None and last_seen is not None:
                issued_at = _parse_iso(session_facts.get("issued_at"))
                expires_at = _parse_iso(session_facts.get("expires_at"))
                session_id = _text(session_facts.get("session_id"))
                if issued_at is not None and expires_at is not None and session_id is not None:
                    session = DeviceSession(
                        session_id=session_id,
                        binding_ref=_text(session_facts.get("binding_ref")) or "",
                        device_id=_text(session_facts.get("device_id")) or "",
                        account_ref=_text(session_facts.get("account_ref")) or "",
                        workspace_ref=_text(session_facts.get("workspace_ref")) or "",
                        issued_at=issued_at,
                        expires_at=expires_at,
                    )
                    heartbeat = ControlPlaneHeartbeatReceipt(
                        session_id=session_id,
                        binding_ref=session.binding_ref,
                        device_id=session.device_id,
                        account_ref=session.account_ref,
                        workspace_ref=session.workspace_ref,
                        credential_generation=binding.credential_generation,
                        last_seen_at=last_seen,
                        session_expires_at=expires_at,
                    )
        except (ContractError, ValueError, TypeError):
            # A fact set that fails canonical validation asserts nothing.
            return None

        if session is not None and heartbeat is not None:
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
        # Fail closed from ONLINE on projection failure: the broker can never
        # report online, so this guard is structural, but if any upstream ever
        # did, unusable evidence must not preserve a connected claim.
        if fallback is DeviceLifecycle.ONLINE:
            return None
        return fallback


async def _maybe_await(value: Any) -> Any:
    if value is not None and hasattr(value, "__await__"):
        return await value
    return value


# ---------------------------------------------------------------------------
# Contract markers
# ---------------------------------------------------------------------------

DEVICE_STATE_SOURCE = "canonical:LOCAL_AGENT_BROKER_AUTHORITY device_truth RPC"
ONLINE_DECISION_AUTHORITY = "kagent.local_agent_server_projection"
SECOND_DEVICE_LIFECYCLE_AUTHORITY = False
NEW_LIFECYCLE_STATE_CREATED = 0
HANDOFF_VALUE_MINTED_OR_PARSED = False
HANDOFF_VALUE_FORWARDED_VERBATIM_OR_DROPPED = True
OWNER_SCOPE_SOURCE = "server_session_identity_only"
MUTATION = False
PRODUCTION_MUTATION = False
