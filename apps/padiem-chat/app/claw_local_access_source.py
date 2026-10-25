"""#3094 — the concrete read-only local-access truth source over #3080.

The #3094 route exposes one typed seam (``ClawLocalAccessTruthSource``) and a
fail-closed unconfigured default. This module supplies the concrete source that
the worker/runtime composition builds over the **actual canonical broker
boundary**: the ``device_truth`` RPC of the #3080 Local Agent broker Worker
(``packages/padiem-control-plane/local_agent_broker_worker.py``), consumed
through the trusted ``LOCAL_AGENT_BROKER_AUTHORITY_SERVICE`` binding.

Requirement 6: Broker is not a prerequisite for a Mesh-only device. The
owner-verified directory may consume source=mesh receipts with NULL generation
using the same 180-second freshness bound; it never grants execution.

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
* Mesh execution liveness is a separate server-recorded fact: the **Mesh
  presence receipt** — one device-connection observation (``conn >= 1``)
  stamped with the server's own receipt time. ``project_mesh_online_binding``
  projects it under the same correlation, credential-generation and
  inside-lifetime rules the heartbeat uses, plus the server's Mesh heartbeat
  staleness bound. A browser-supplied connection flag, a missing receipt or a
  stale receipt never yields ONLINE.
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
``ONLINE_DECISION_AUTHORITY = "kagent.local_agent_server_projection + app.claw_local_access_source.project_mesh_online_binding"``
``MESH_ONLINE_EVIDENCE_SOURCE = "server_recorded_mesh_presence_receipt"``
``SECOND_DEVICE_LIFECYCLE_AUTHORITY = False``
``NEW_LIFECYCLE_STATE_CREATED = 0``
``HANDOFF_VALUE_MINTED_OR_PARSED = False``
``OWNER_SCOPE_SOURCE = "server_session_identity_only"``
``MUTATION = False``
``PRODUCTION_MUTATION = False``
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from padiem_ai_core.pc_device_identity import is_pc_device_id
from kagent.contracts import ContractError
from kagent.local_agent_control_plane_runtime import ControlPlaneHeartbeatReceipt
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from kagent.local_agent_server_projection import project_server_backed_online_binding

__all__ = [
    "MESH_PRESENCE_MAX_AGE_SECONDS",
    "MeshPresenceReceipt",
    "TrustedLocalAccessDeviceTruthPort",
    "CanonicalClawLocalAccessTruthSource",
    "project_mesh_online_binding",
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

# The server's own Mesh heartbeat staleness bound (#5462,
# ``kagent.local_agent_mesh_failover.DEFAULT_HEARTBEAT_STALE_SECONDS``). A Mesh
# presence receipt older than this is not liveness: the failover controller
# already stops treating such a heartbeat as proof of execution, so the ONLINE
# projection refuses at exactly the same age.
MESH_PRESENCE_MAX_AGE_SECONDS = 180


@dataclass(frozen=True, slots=True)
class MeshPresenceReceipt:
    """One server-recorded Mesh connection observation.

    Every field is recorded server-side: ``device_id`` is the Mesh node the
    server observed, ``connected`` is the MeshCentral ``conn >= 1`` fact,
    ``observed_at`` is the server's own receipt time, and
    ``credential_generation`` is the canonical generation the observation was
    recorded against. No browser or request value feeds this receipt.
    """

    device_id: str
    account_ref: str
    credential_generation: int
    observed_at: datetime
    connected: bool = True
    workspace_ref: str | None = None


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


def _aware(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _mesh_presence_receipt(value: Any) -> MeshPresenceReceipt | None:
    """Read one server-recorded Mesh presence receipt, or ``None`` if malformed.

    ``None`` means "no usable Mesh evidence", never "offline": the caller keeps
    the broker-reported state in that case.
    """

    facts = _mapping(value)
    if facts is None:
        return None
    device_id = _text(facts.get("device_id"))
    account_ref = _text(facts.get("account_ref"))
    credential_generation = _int(facts.get("credential_generation"))
    observed_at = _parse_iso(facts.get("observed_at"))
    connected = facts.get("connected")
    workspace_ref = facts.get("workspace_ref")
    if workspace_ref is not None:
        workspace_ref = _text(workspace_ref)
        if workspace_ref is None:
            return None
    if device_id is None or account_ref is None:
        return None
    if credential_generation is None or observed_at is None:
        return None
    if not isinstance(connected, bool):
        return None
    return MeshPresenceReceipt(
        device_id=device_id,
        account_ref=account_ref,
        credential_generation=credential_generation,
        observed_at=observed_at,
        connected=connected,
        workspace_ref=workspace_ref,
    )


def mesh_presence_online(row: Any, *, device_id: str, now: datetime) -> bool:
    """Requirement 6: Broker is not a prerequisite for mapped Mesh liveness.

    Callers must first verify the owner/device against the deployment map.
    This receipt is display evidence only; it creates no execution grant.
    """
    if not is_pc_device_id(device_id) or not isinstance(row, Mapping) or row.get("source") != "mesh":
        return False
    observed = _parse_iso(row.get("received_at", row.get("observed_at")))
    if (row.get("device_id") != device_id or row.get("connected") is not True
            or row.get("credential_generation") is not None or observed is None):
        return False
    return 0 <= (_aware(now, "now") - observed).total_seconds() <= MESH_PRESENCE_MAX_AGE_SECONDS


def mesh_directory_local_access_projection(directory: Any) -> dict[str, Any] | None:
    """Reuse the owner-verified directory for the read-only connection panel.

    Requirement 6: no Broker registration is needed. This does not select a
    device, issue a handoff, or change execution authorization.
    """
    if not isinstance(directory, Mapping) or directory.get("ownerScoped") is not True or directory.get("available") is not True:
        return None
    selected = directory.get("selectedDeviceId")
    devices = directory.get("devices")
    if not isinstance(devices, list):
        return None
    if not any(isinstance(row, Mapping) and row.get("executable") is True
               and row.get("state") == "CONNECTED" and row.get("usable") is True
               and row.get("revoked") is False and row.get("expired") is False
               and (selected is None or selected == row.get("deviceId")) for row in devices):
        return None
    return {"canonical_state": DeviceLifecycle.ONLINE, "requires_local_access": True,
            "required_capabilities": ["local_computer"], "desktop_installed": False,
            "handoff_value": None}


def mesh_presence_facts(
    row: Any, binding: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """The receipt block for one stored presence row, or ``None``.

    The stored row carries only what the server recorded (device, connected,
    receipt time, credential generation). Account and workspace correlation
    come from the same Broker binding facts the projection already reads, so a
    row can never smuggle a foreign account or workspace. A row for another
    device is refused rather than retargeted.
    """

    if not isinstance(row, Mapping) or not isinstance(binding, Mapping):
        return None
    device_id = _text(row.get("device_id"))
    generation = _int(row.get("credential_generation"))
    observed_at = _text(row.get("received_at"))
    connected = row.get("connected")
    account_ref = _text(binding.get("account_ref"))
    mesh_only = row.get("source") == "mesh" and row.get("credential_generation") is None
    if device_id is None or (generation is None and not mesh_only) or observed_at is None:
        return None
    if type(connected) is not bool or account_ref is None:
        return None
    if device_id != _text(binding.get("device_id")):
        return None
    workspace_ref = binding.get("workspace_ref")
    if workspace_ref is not None:
        workspace_ref = _text(workspace_ref)
        if workspace_ref is None:
            return None
    return {
        "device_id": device_id,
        "account_ref": account_ref,
        "workspace_ref": workspace_ref,
        "credential_generation": generation,
        "observed_at": observed_at,
        "connected": connected,
        **({"source": "mesh"} if mesh_only else {}),
    }


def project_mesh_online_binding(
    *,
    binding: DeviceBinding,
    presence: MeshPresenceReceipt,
    now: datetime,
) -> DeviceBinding:
    """Project one server-recorded Mesh presence receipt to ONLINE.

    This is a projection *inside* the one ONLINE decision, not a second
    lifecycle authority: it returns the same ``DeviceBinding`` type, and the
    caller's fallback stays the broker-reported state. The invariants mirror
    the server heartbeat rule (``project_server_backed_online_binding``):

    1. the binding is a redeemed ``PAIRED_OFFLINE`` device;
    2. the receipt correlates with that exact binding (device, account and,
       when present, workspace) and reports the same credential generation;
    3. the observation falls inside the binding's own credential lifetime;
    4. the observation is not in the future and is no older than the Mesh
       heartbeat staleness bound;
    5. the receipt actually claims a connected device.

    A missing, foreign, stale or disconnected receipt raises ``ContractError``;
    the caller falls back to the broker-reported state, never to ONLINE.
    """

    if not isinstance(binding, DeviceBinding):
        raise ContractError("binding must be DeviceBinding")
    if binding.state is not DeviceLifecycle.PAIRED_OFFLINE:
        raise ContractError(
            "Mesh ONLINE projection requires a redeemed PAIRED_OFFLINE binding; "
            f"{binding.state.value} is not a projection source"
        )
    if not isinstance(presence, MeshPresenceReceipt):
        raise ContractError("presence must be MeshPresenceReceipt")
    now = _aware(now, "now")
    observed_at = _aware(presence.observed_at, "mesh presence observed_at")

    if presence.connected is not True:
        raise ContractError("mesh presence does not claim a connected device")
    if presence.device_id != binding.device_id:
        raise ContractError("mesh presence does not correlate with the device binding")
    if presence.account_ref != binding.account_ref:
        raise ContractError("mesh presence does not correlate with the device account")
    if presence.workspace_ref is not None and presence.workspace_ref != binding.workspace_ref:
        raise ContractError("mesh presence does not correlate with the device workspace")
    if presence.credential_generation != binding.credential_generation:
        raise ContractError("mesh presence belongs to a different credential generation")
    if not (binding.issued_at <= observed_at < binding.credential_expires_at):
        raise ContractError("mesh presence was not observed inside the binding lifetime")
    if observed_at > now:
        raise ContractError("mesh presence observation cannot be in the future")
    if (now - observed_at).total_seconds() > MESH_PRESENCE_MAX_AGE_SECONDS:
        raise ContractError("mesh presence is stale; ONLINE projection is refused")

    return replace(binding, state=DeviceLifecycle.ONLINE)


class CanonicalClawLocalAccessTruthSource:
    """Read one owner-scoped canonical projection from the trusted boundary.

    ``configured`` is true by construction: an instance only exists after the
    composition seam verified the trusted boundary. Every failure mode below
    collapses to "no projection" (``None``), which the route already reports as
    ``available: false`` with a bounded reason — never as a guessed device.
    """

    configured = True

    def __init__(
        self,
        *,
        port: TrustedLocalAccessDeviceTruthPort,
        presence_store: Any = None,
    ) -> None:
        if not callable(getattr(port, "device_truth", None)):
            raise TypeError("local access trusted port must expose device_truth()")
        self._port = port
        #: #5553 — one server-recorded Mesh presence receipt, read by the same
        #: canonical access source. Absent store means today's exact answer.
        self._presence_store = presence_store

    async def _facts_with_mesh_presence(
        self, facts: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Add the stored presence receipt to the broker facts, or leave them."""

        store = self._presence_store
        if store is None:
            return facts
        binding = _mapping(facts.get("binding"))
        device_id = _text(binding.get("device_id")) if binding is not None else None
        if device_id is None:
            return facts
        try:
            row = store.load(device_id)
            if hasattr(row, "__await__"):
                row = await row
        except Exception:
            return facts
        block = mesh_presence_facts(row, binding)
        if block is None:
            return facts
        merged = dict(facts)
        merged["mesh_presence"] = block
        return merged

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

        # #5553: the stored server-recorded Mesh receipt joins the same fact
        # block, so one decision still covers broker session, heartbeat and
        # Mesh liveness.
        facts = await self._facts_with_mesh_presence(facts)

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
        may attempt an ONLINE projection. A device the broker already reports
        as ``revoked`` or ``credential_expired`` — or any unknown vocabulary —
        returns that exact fail-closed state and never reaches an ONLINE rule,
        so an expired credential cannot be resurrected into a connected claim
        by a still-current session, heartbeat or Mesh receipt.

        Two server-recorded evidence kinds feed the same decision, in order:
        the canonical broker session + heartbeat receipt, then the Mesh
        presence receipt. Either one may produce ONLINE; neither is required,
        and a refusal from both falls back to the broker state.
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

        mesh = _mapping(facts.get("mesh_presence"))
        if (mesh is not None and _text(binding_facts.get("account_ref")) is not None
                and mesh.get("account_ref") == binding_facts.get("account_ref")
                and mesh.get("workspace_ref") == binding_facts.get("workspace_ref")
                and mesh_presence_online(mesh, device_id=binding_facts.get("device_id"), now=now)):
            return DeviceLifecycle.ONLINE

        presence = _mesh_presence_receipt(facts.get("mesh_presence"))

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
        if presence is not None:
            try:
                projected = project_mesh_online_binding(
                    binding=binding,
                    presence=presence,
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
ONLINE_DECISION_AUTHORITY = (
    "kagent.local_agent_server_projection + "
    "app.claw_local_access_source.project_mesh_online_binding"
)
MESH_ONLINE_EVIDENCE_SOURCE = "server_recorded_mesh_presence_receipt"
MESH_PRESENCE_CLIENT_VALUES_ACCEPTED = False
SECOND_DEVICE_LIFECYCLE_AUTHORITY = False
NEW_LIFECYCLE_STATE_CREATED = 0
HANDOFF_VALUE_MINTED_OR_PARSED = False
HANDOFF_VALUE_FORWARDED_VERBATIM_OR_DROPPED = True
OWNER_SCOPE_SOURCE = "server_session_identity_only"
MUTATION = False
PRODUCTION_MUTATION = False
