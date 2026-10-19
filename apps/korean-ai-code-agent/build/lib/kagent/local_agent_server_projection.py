from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .contracts import ContractError
from .local_agent_control_plane_runtime import ControlPlaneHeartbeatReceipt
from .local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def project_server_backed_online_binding(
    *,
    binding: DeviceBinding,
    session: DeviceSession | None,
    heartbeat: ControlPlaneHeartbeatReceipt | None,
    now: datetime,
) -> DeviceBinding:
    """Project the canonical server-backed ONLINE device state (#3080 owns this fact).

    This is the Python-side counterpart of the merged #3083 desktop-shell rule
    (`apps/padiem-desktop-shell/src/contract/device-lifecycle.ts`), which
    refuses any `-> ONLINE` transition whose trigger is not `server_projection`.

    Therefore ONLINE is reachable only from server facts:

    1. a redeemed (`PAIRED_OFFLINE`) device binding, and
    2. a canonical broker session that the broker authority actually opened, and
    3. a server-owned heartbeat acknowledgement bound to that exact session.

    A missing, failed or unrelated session/heartbeat can never yield ONLINE, and
    a local caller can never flip a binding to ONLINE on its own.
    """

    if not isinstance(binding, DeviceBinding):
        raise ContractError("binding must be DeviceBinding")
    if binding.state is not DeviceLifecycle.PAIRED_OFFLINE:
        raise ContractError(
            "server ONLINE projection requires a redeemed PAIRED_OFFLINE binding; "
            f"{binding.state.value} is not a server-projection source"
        )
    if session is None:
        raise ContractError("server ONLINE projection requires a canonical broker session")
    if not isinstance(session, DeviceSession):
        raise ContractError("session must be DeviceSession")
    if heartbeat is None:
        raise ContractError("server ONLINE projection requires a server-owned heartbeat receipt")
    if not isinstance(heartbeat, ControlPlaneHeartbeatReceipt):
        raise ContractError("heartbeat must be ControlPlaneHeartbeatReceipt")
    now = _aware(now, "now")

    binding_correlation = (
        binding.binding_ref,
        binding.device_id,
        binding.account_ref,
        binding.workspace_ref,
        binding.credential_generation,
    )
    if (session.binding_ref, session.device_id, session.account_ref, session.workspace_ref) != binding_correlation[:4]:
        raise ContractError("server session does not correlate with the redeemed device binding")
    if session.issued_at < binding.issued_at:
        raise ContractError("server session was not issued for this binding")
    if not (session.issued_at <= now < session.expires_at):
        raise ContractError("server session is not current; ONLINE projection is refused")
    if heartbeat.session_id != session.session_id:
        raise ContractError("server heartbeat does not belong to the current broker session")
    if (heartbeat.binding_ref, heartbeat.device_id, heartbeat.account_ref, heartbeat.workspace_ref) != binding_correlation[:4]:
        raise ContractError("server heartbeat does not correlate with the redeemed device binding")
    if heartbeat.credential_generation != binding.credential_generation:
        raise ContractError("server heartbeat belongs to a different credential generation")
    if heartbeat.session_expires_at != session.expires_at:
        raise ContractError("server heartbeat reports a different session expiry")
    if not (session.issued_at <= heartbeat.last_seen_at < session.expires_at):
        raise ContractError("server heartbeat was not acknowledged inside the session lifetime")
    if heartbeat.last_seen_at > now:
        raise ContractError("server heartbeat acknowledgement cannot be in the future")

    return replace(binding, state=DeviceLifecycle.ONLINE)


def online_binding_evidence(
    *,
    binding: DeviceBinding,
    session: DeviceSession | None,
    heartbeat: ControlPlaneHeartbeatReceipt | None,
    now: datetime,
) -> dict[str, Any]:
    """Secret-free evidence projection describing whether ONLINE is server-backed."""

    projected = project_server_backed_online_binding(
        binding=binding,
        session=session,
        heartbeat=heartbeat,
        now=now,
    )
    return {
        "contract_version": "claw-local-agent-server-projection.v1",
        "device_id": projected.device_id,
        "binding_ref": projected.binding_ref,
        "state": projected.state.value,
        "server_projection_trigger": SERVER_PROJECTION_TRIGGER,
        "evidence_backed": True,
        "session_id": session.session_id if isinstance(session, DeviceSession) else None,
        "last_seen_at": heartbeat.last_seen_at.isoformat().replace("+00:00", "Z")
        if isinstance(heartbeat, ControlPlaneHeartbeatReceipt)
        else None,
        "online_requires_server_projection": True,
        "local_online_claim": False,
        "public_inbound_port": False,
        "raw_device_credential": False,
        "production_ready": False,
    }


SERVER_PROJECTION_TRIGGER = "server_projection"
CANONICAL_DEVICE_TRUTH_OWNED_BY = "3080"
DESKTOP_SHELL_ONLINE_RULE_REUSED = True
ONLINE_REQUIRES_SERVER_PROJECTION = True
SESSION_AND_HEARTBEAT_REQUIRED = True
PAIRED_OFFLINE_IS_PROJECTION_SOURCE = True
LOCAL_ONLINE_CLAIM = False
RENDERER_OR_LOCAL_SUPERVISION_MAY_FORGE_ONLINE = False
SECOND_DEVICE_LIFECYCLE_AUTHORITY = 0
PRODUCTION_READY = False
