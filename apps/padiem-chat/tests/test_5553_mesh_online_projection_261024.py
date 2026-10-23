"""#5553 — server-recorded Mesh liveness inside the one ONLINE authority.

The input chip showed "연결 확인 필요" for a PC whose Mesh agent was connected
(``conn = 1``) because ONLINE was decided only from the broker session +
heartbeat, and a Mesh-only target has neither. The fix is not a second
authority: the existing canonical source now also consumes one **server
recorded** Mesh presence receipt — a device-connection observation stamped
with the server's receipt time — under the same rules the heartbeat path uses.

Evidence source (measured, not assumed):

* the Mesh failover heartbeat receipt (``padiem_mesh_heartbeat/v1``:
  ``device_connected`` plus the receipt time) and the MeshCentral
  ``listdevices`` ``conn`` fact behind it; freshness uses the same bound the
  failover controller applies (``DEFAULT_HEARTBEAT_STALE_SECONDS``).
* ``oracle_mesh_dispatch`` carries no liveness column and the broker
  ``device_truth`` envelope carries no Mesh field, so neither is used here.

Client-supplied connection claims are structurally impossible: the projection
reads only the receipt block the trusted boundary records, and a malformed or
non-boolean claim is treated as no evidence at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.claw_local_access_source import (
    MESH_PRESENCE_MAX_AGE_SECONDS,
    CanonicalClawLocalAccessTruthSource,
    MeshPresenceReceipt,
    project_mesh_online_binding,
)
from kagent.contracts import ContractError
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle
from kagent.local_agent_mesh_failover import DEFAULT_HEARTBEAT_STALE_SECONDS

NOW = datetime(2026, 10, 24, 9, 0, 30, tzinfo=timezone.utc)
DEVICE_ID = "pc-mesh-5553"
BINDING_REF = "bind_5553"
ACCOUNT_REF = "acct_5553"
WORKSPACE_REF = "ws_5553"
GENERATION = 3

BINDING_ISSUED_AT = datetime(2026, 10, 24, 8, 0, tzinfo=timezone.utc)
CREDENTIAL_EXPIRES_AT = datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc)
SESSION_ISSUED_AT = datetime(2026, 10, 24, 8, 50, tzinfo=timezone.utc)
SESSION_EXPIRES_AT = datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _binding(*, generation: int = GENERATION) -> DeviceBinding:
    return DeviceBinding(
        device_id=DEVICE_ID,
        binding_ref=BINDING_REF,
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        credential_ref="local-access-projection-only",
        credential_generation=generation,
        issued_at=BINDING_ISSUED_AT,
        credential_expires_at=CREDENTIAL_EXPIRES_AT,
    )


def _presence(
    *,
    observed_at: datetime,
    generation: int = GENERATION,
    connected: bool = True,
) -> MeshPresenceReceipt:
    return MeshPresenceReceipt(
        device_id=DEVICE_ID,
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        credential_generation=generation,
        observed_at=observed_at,
        connected=connected,
    )


def _facts(
    *,
    presence: object = None,
    generation: int = GENERATION,
    heartbeat_last_seen_at: datetime | None = None,
    canonical_state: str = "paired_offline",
) -> dict:
    """One broker ``device_truth`` fact block, plus the server receipt block."""

    facts = {
        "canonical_state": canonical_state,
        "binding": {
            "device_id": DEVICE_ID,
            "binding_ref": BINDING_REF,
            "account_ref": ACCOUNT_REF,
            "workspace_ref": WORKSPACE_REF,
            "credential_generation": generation,
            "issued_at": _iso(BINDING_ISSUED_AT),
            "credential_expires_at": _iso(CREDENTIAL_EXPIRES_AT),
        },
        "session": None,
        "heartbeat_last_seen_at": None,
        "mesh_presence": None,
    }
    if heartbeat_last_seen_at is not None:
        facts["session"] = {
            "session_id": "sess_5553",
            "binding_ref": BINDING_REF,
            "device_id": DEVICE_ID,
            "account_ref": ACCOUNT_REF,
            "workspace_ref": WORKSPACE_REF,
            "credential_generation": generation,
            "issued_at": _iso(SESSION_ISSUED_AT),
            "expires_at": _iso(SESSION_EXPIRES_AT),
        }
        facts["heartbeat_last_seen_at"] = _iso(heartbeat_last_seen_at)
    if presence is not None:
        if isinstance(presence, MeshPresenceReceipt):
            facts["mesh_presence"] = {
                "device_id": presence.device_id,
                "account_ref": presence.account_ref,
                "workspace_ref": presence.workspace_ref,
                "credential_generation": presence.credential_generation,
                "observed_at": _iso(presence.observed_at),
                "connected": presence.connected,
            }
        else:
            facts["mesh_presence"] = presence
    return facts


def _canonical(facts: dict, *, now: datetime = NOW) -> DeviceLifecycle | None:
    return CanonicalClawLocalAccessTruthSource._canonical_state(facts, now=now)


def test_a_fresh_mesh_presence_receipt_projects_online() -> None:
    """A fresh server receipt is ONLINE — and the existing paths are unchanged."""

    # Freshness is the failover controller's own bound, not a new number.
    assert MESH_PRESENCE_MAX_AGE_SECONDS == DEFAULT_HEARTBEAT_STALE_SECONDS
    assert MESH_PRESENCE_MAX_AGE_SECONDS == 180

    # At the bound the receipt still counts; one second past it does not.
    at_bound = _presence(observed_at=NOW - timedelta(seconds=MESH_PRESENCE_MAX_AGE_SECONDS))
    projected = project_mesh_online_binding(binding=_binding(), presence=at_bound, now=NOW)
    assert projected.state is DeviceLifecycle.ONLINE
    assert projected.device_id == DEVICE_ID

    fresh = _presence(observed_at=NOW - timedelta(seconds=5))
    assert _canonical(_facts(presence=fresh)) is DeviceLifecycle.ONLINE

    # Additive, not replacing: the broker session + heartbeat path still decides.
    heartbeat_facts = _facts(heartbeat_last_seen_at=NOW - timedelta(seconds=15))
    assert _canonical(heartbeat_facts) is DeviceLifecycle.ONLINE

    # No receipt at all keeps today's answer.
    assert _canonical(_facts(presence=None)) is DeviceLifecycle.PAIRED_OFFLINE


def test_a_stale_mesh_presence_receipt_falls_back_to_paired_offline() -> None:
    """An old or future-dated observation is not liveness."""

    stale = _presence(
        observed_at=NOW - timedelta(seconds=MESH_PRESENCE_MAX_AGE_SECONDS + 1)
    )
    with pytest.raises(ContractError):
        project_mesh_online_binding(binding=_binding(), presence=stale, now=NOW)
    assert _canonical(_facts(presence=stale)) is DeviceLifecycle.PAIRED_OFFLINE

    future = _presence(observed_at=NOW + timedelta(seconds=1))
    with pytest.raises(ContractError):
        project_mesh_online_binding(binding=_binding(), presence=future, now=NOW)
    assert _canonical(_facts(presence=future)) is DeviceLifecycle.PAIRED_OFFLINE


def test_a_foreign_credential_generation_is_never_online() -> None:
    """A receipt from another credential generation cannot promote the device."""

    foreign = _presence(observed_at=NOW - timedelta(seconds=5), generation=GENERATION + 1)
    with pytest.raises(ContractError):
        project_mesh_online_binding(binding=_binding(), presence=foreign, now=NOW)
    assert _canonical(_facts(presence=foreign)) is DeviceLifecycle.PAIRED_OFFLINE

    # A terminal broker state never reaches any projection, receipt or not.
    fresh = _presence(observed_at=NOW - timedelta(seconds=5))
    assert _canonical(_facts(presence=fresh, canonical_state="revoked")) is DeviceLifecycle.REVOKED
    assert (
        _canonical(_facts(presence=fresh, canonical_state="credential_expired"))
        is DeviceLifecycle.CREDENTIAL_EXPIRED
    )

    # A client-shaped claim (string "true", missing generation) is no evidence.
    malformed = {
        "device_id": DEVICE_ID,
        "account_ref": ACCOUNT_REF,
        "connected": "true",
        "observed_at": _iso(NOW - timedelta(seconds=5)),
    }
    assert _canonical(_facts(presence=malformed)) is DeviceLifecycle.PAIRED_OFFLINE
