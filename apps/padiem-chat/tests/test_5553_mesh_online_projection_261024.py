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


# ---------------------------------------------------------------------------
# The receipt supply path: executor poll -> mesh_device_presence -> projection
# ---------------------------------------------------------------------------

NODE_ID = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
POLL_SECRET = "5553-deployment-channel-secret-value"
POLL_PATH_FILE = "mesh-presence-5553.txt"


class _PollHistory:
    async def oldest_pending_oracle_mesh_dispatch(self):
        return None

    async def claim_oracle_mesh_dispatch(self, *, dispatch_id, nonce_sha256):
        raise AssertionError("no dispatch should be claimed")


class _PollRequest:
    def __init__(self, data, state, *, secret=None):
        self.app = SimpleNamespace(state=state)
        raw = json.dumps(data).encode("utf-8")
        self.headers = {
            "content-type": "application/json",
            "content-length": str(len(raw)),
        }
        if secret is not None:
            self.headers[mesh_routes.ORACLE_MESH_CHANNEL_HEADER] = secret
        self._raw = raw

    async def body(self):
        return self._raw


class _PresenceStore:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})
        self.upserts = []

    async def upsert(self, *, device_id, connected, received_at, credential_generation):
        record = {
            "device_id": device_id,
            "connected": connected,
            "received_at": received_at,
            "credential_generation": credential_generation,
        }
        self.upserts.append(record)
        self.rows[device_id] = record
        return True

    async def load(self, device_id):
        return self.rows.get(device_id)


class _DirectoryBinding:
    def __init__(self, facts):
        self.facts = facts

    async def device_directory(self, payload):
        assert payload == {"account_ref": ACCOUNT_REF, "workspace_ref": WORKSPACE_REF}
        return {
            "ok": True,
            "available": True,
            "owner_scoped": True,
            "device_count": 1,
            "devices": [self.facts],
        }


async def _generation_resolver(*, account_ref, device_id):
    assert account_ref == ACCOUNT_REF
    assert device_id == DEVICE_ID
    return GENERATION


def _poll_source():
    source = mesh_routes.build_oracle_mesh_return_source(
        [{
            "account_ref": ACCOUNT_REF,
            "device_id": DEVICE_ID,
            "node_ref": NODE_ID,
            "root_ref": "mesh_5553",
            "path_relative": POLL_PATH_FILE,
            "file_path": "C:/Users/owner/" + POLL_PATH_FILE,
        }],
        POLL_SECRET,
        mesh_routes.EXECUTION_MODE_MESH,
    )
    assert source is not None
    return source


def _poll_state(store):
    return SimpleNamespace(
        oracle_mesh_return_source=_poll_source(),
        history_store=_PollHistory(),
        mesh_device_presence_store=store,
        mesh_presence_generation_resolver=_generation_resolver,
    )


def _poll(state, payload):
    response = asyncio.run(
        mesh_routes.oracle_mesh_read_poll(
            _PollRequest(payload, state, secret=POLL_SECRET)
        )
    )
    return response.status_code, json.loads(response.body)


def _presence_row(*, observed_at, generation=GENERATION, connected=True):
    return {
        "device_id": DEVICE_ID,
        "connected": connected,
        "received_at": _iso(observed_at),
        "credential_generation": generation,
    }


def _directory_state(*, observed_at, generation=GENERATION):
    source = BrokerDeviceDirectorySource(
        _DirectoryBinding(_facts(generation=GENERATION)),
        presence_store=_PresenceStore(
            {DEVICE_ID: _presence_row(observed_at=observed_at, generation=generation)}
        ),
    )
    return asyncio.run(
        source.list_devices(
            owner_id=ACCOUNT_REF, workspace_id=WORKSPACE_REF, now=NOW,
        )
    )


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
