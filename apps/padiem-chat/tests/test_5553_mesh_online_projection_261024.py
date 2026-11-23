"""#5553 — server-recorded Mesh liveness inside the one ONLINE authority.

The input chip showed "연결 확인 필요" for a PC whose Mesh agent was connected
(``conn = 1``) because ONLINE was decided only from the broker session +
heartbeat, and a Mesh-only target has neither. The fix is not a second
authority: the existing canonical source now also consumes one **server
recorded** Mesh presence receipt — a device-connection observation stamped
with the server's receipt time — under the same rules the heartbeat path uses.

Evidence source (measured, not assumed):

* the executor poll carries an optional ``presence`` beat; the server resolves
  the canonical device id from the deployment ownership map, stamps the
  device's current Broker credential generation and its own receipt time, and
  UPSERTs ``mesh_device_presence`` (migration 067). The same row feeds the
  canonical ONLINE projection here.
* freshness uses the failover controller's own bound
  (``DEFAULT_HEARTBEAT_STALE_SECONDS`` = 180 s).
* ``oracle_mesh_dispatch`` carries no liveness column and the broker
  ``device_truth`` envelope carries no Mesh field, so neither is used as the
  presence store.

Client-supplied connection claims are structurally impossible: the projection
reads only the receipt block the trusted boundary records, and a malformed or
non-boolean claim is treated as no evidence at all.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as mesh_routes
from app.claw_device_directory_routes import BrokerDeviceDirectorySource
from app.claw_local_access_source import (
    MESH_PRESENCE_MAX_AGE_SECONDS,
    CanonicalClawLocalAccessTruthSource,
    MeshPresenceReceipt,
    project_mesh_online_binding,
)
from kagent.contracts import ContractError
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle
from padiem_ai_core.clock_skew import DEVICE_CLOCK_SKEW_TOLERANCE
from kagent.local_agent_mesh_failover import DEFAULT_HEARTBEAT_STALE_SECONDS

from _support.mesh_online_projection import NOW, DEVICE_ID, BINDING_REF, ACCOUNT_REF, WORKSPACE_REF, GENERATION, BINDING_ISSUED_AT, CREDENTIAL_EXPIRES_AT, SESSION_ISSUED_AT, SESSION_EXPIRES_AT, _iso, _binding, _presence, _facts, _canonical, NODE_ID, POLL_SECRET, POLL_PATH_FILE, _PollHistory, _PollRequest, _PresenceStore, _DirectoryBinding, _generation_resolver, _poll_source, _poll_state, _poll, _presence_row, _directory_state


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

    # 기기 시계 허용(300초)을 넘는 앞섬만 "미래"로 거절한다.
    future = _presence(observed_at=NOW + DEVICE_CLOCK_SKEW_TOLERANCE + timedelta(seconds=1))
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


def test_poll_without_presence_is_byte_for_byte_unchanged() -> None:
    store = _PresenceStore()
    state = _poll_state(store)

    status, body = _poll(state, {})
    assert status == 200
    assert body == {"ok": True, "dispatch": None}
    assert store.upserts == []

    # A malformed beat is refused as evidence, never as a poll failure.
    for malformed in (
        {"presence": [{"device_id": NODE_ID, "connected": "true"}]},
        {"presence": [{"device_id": NODE_ID, "connected": True, "extra": 1}]},
        {"presence": []},
        {"presence": "node"},
        {"unexpected": True},
    ):
        status, body = _poll(_poll_state(store), malformed)
        assert status == 200
        assert body == {"ok": True, "dispatch": None}
    assert store.upserts == []


def test_poll_presence_upserts_with_server_stamped_identity_and_generation() -> None:
    store = _PresenceStore()
    status, body = _poll(
        _poll_state(store),
        {"presence": [{"device_id": NODE_ID, "connected": True}]},
    )
    assert status == 200
    assert body == {"ok": True, "dispatch": None}
    assert len(store.upserts) == 1
    stored = store.upserts[0]
    # The Mesh node was resolved to the canonical device id by the server.
    assert stored["device_id"] == DEVICE_ID
    assert stored["connected"] is True
    # The generation is the Broker binding's, never the request's.
    assert stored["credential_generation"] == GENERATION
    assert isinstance(stored["received_at"], datetime)
    assert stored["received_at"].tzinfo is not None

    # A disconnected beat overwrites the stored liveness instead of keeping it.
    _poll(
        _poll_state(store),
        {"presence": [{"device_id": NODE_ID, "connected": False}]},
    )
    assert store.rows[DEVICE_ID]["connected"] is False


def test_a_fresh_stored_presence_makes_the_directory_usable() -> None:
    items = _directory_state(observed_at=NOW - timedelta(seconds=5))
    assert len(items) == 1
    assert items[0]["deviceId"] == DEVICE_ID
    assert items[0]["state"] == "CONNECTED"
    assert items[0]["usable"] is True


def test_a_presence_older_than_180_seconds_is_not_usable() -> None:
    items = _directory_state(
        observed_at=NOW - timedelta(seconds=MESH_PRESENCE_MAX_AGE_SECONDS + 1)
    )
    assert items[0]["state"] == "OFFLINE"
    assert items[0]["usable"] is False


def test_a_foreign_generation_presence_is_not_usable() -> None:
    items = _directory_state(
        observed_at=NOW - timedelta(seconds=5), generation=GENERATION + 1,
    )
    assert items[0]["state"] == "OFFLINE"
    assert items[0]["usable"] is False
