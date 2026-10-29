"""#82 — the queue serves the same lane-status read, behind the same secret split.

After the cutover the queue is the live store, so the monitor's read has to come from
here. The condition for moving anything to this service was that no rule is
re-implemented: the route function is the Worker's own, imported and served here, and
these tests hold that by comparing the two answers on the same rows.

The second property is the secret boundary introduced in the Worker (#6145): a
read-only watch secret may read the lane and must never claim, renew, cancel or
consume. The queue composes the same source object, so the same check answers — and a
test that only covered the Worker would not notice if this service ever stopped
composing it.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest
from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore
from app.oracle_mesh_lease_renew_routes import oracle_mesh_read_renew
from app.oracle_mesh_read_return_routes import (
    ORACLE_MESH_READ_LANE_STATUS_PATH, ORACLE_MESH_READ_POLL_PATH,
    oracle_mesh_read_lane_status, oracle_mesh_read_poll,
)
from schema import apply
from service import HEALTH_PATH, create_app
from test_queue_claim_lane import _Request, _json, _stage, _state, endpoint_of

SECRET = "queue-channel-secret-value-261029"
WATCH = "queue-watch-read-secret-261029"
SERVICE_SECRET = "queue-service-secret-value-261029"
OWNERSHIP = [{"account_ref": "acct-1", "device_id": "device-1", "node_ref": "node-ABC",
              "root_ref": "C:", "path_relative": "p.txt", "file_path": "C:/p.txt",
              "command_exec": True}]
NODE_B = "node-OTHER"


def _db():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply(connection)
    return SqliteD1(connection)


def _app(database, *, watch=WATCH):
    return create_app(connection=database, channel_secret=SECRET, mode="mesh",
                      ownership_map=json.dumps(OWNERSHIP),
                      service_secret=SERVICE_SECRET, watch_secret=watch)


def _lane(app, *, secret=SECRET, payload=None):
    handler = endpoint_of(app, ORACLE_MESH_READ_LANE_STATUS_PATH)
    return asyncio.run(handler(_Request(app.state, payload, secret=secret)))


def _stage_two(database):
    """One unclaimed, one claimed and one on another PC: three different answers."""

    state = _app(database).state
    _stage(state, dispatch_id="dsp_" + "a" * 32)
    _stage(state, dispatch_id="dsp_" + "b" * 32)
    claimed = asyncio.run(oracle_mesh_read_poll(_Request(state, {}, secret=SECRET)))
    assert _json(claimed)["dispatch"] is not None
    _stage(state, dispatch_id="dsp_" + "c" * 32)  # node-ABC, still unclaimed
    asyncio.run(state.history_store._run(
        "UPDATE oracle_mesh_dispatch SET node_ref=? WHERE dispatch_id=?",
        NODE_B, "dsp_" + "c" * 32,
    ))


def _masked(body):
    """Counts and ages, with the ages compared loosely and the PC names kept."""

    def bucket(entry):
        return {"count": entry["count"],
                "has_age": entry["oldest_seconds"] is not None}

    return {
        "unclaimed": bucket(body["unclaimed"]),
        "claimed": bucket(body["claimed"]),
        "nodes": sorted(
            ({"node_ref": row["node_ref"], "open": row["open"],
              "waiting": row["waiting"],
              "has_age": row["oldest_seconds"] is not None,
              "has_waiting_age": row["waiting_oldest_seconds"] is not None}
             for row in body["nodes"]),
            key=lambda row: row["node_ref"],
        ),
    }


def test_the_queue_answers_the_lane_status_exactly_as_the_worker_does():
    """Same rows, same handler, same numbers — the differential the move rests on."""

    chat_database = _db()
    queue_database = _db()
    _stage_two(chat_database)
    _stage_two(queue_database)

    worker = asyncio.run(D1HistoryStore(chat_database).oracle_mesh_lane_status())
    queue = _json(_lane(_app(queue_database)))

    assert _masked(worker) == _masked(queue)
    assert worker["unclaimed"]["count"] == queue["unclaimed"]["count"] >= 2
    assert worker["claimed"]["count"] == queue["claimed"]["count"] == 1
    assert {row["node_ref"] for row in queue["nodes"]} == {"node-ABC", NODE_B}


def test_the_read_only_secret_opens_the_lane_read_and_no_claiming_leg():
    app = _app(_db())

    assert _lane(app, secret=WATCH).status_code == 200
    assert _lane(app, secret=SECRET).status_code == 200, "the channel secret is unchanged"

    refused = asyncio.run(oracle_mesh_read_poll(_Request(app.state, {}, secret=WATCH)))
    assert refused.status_code == 403
    assert _json(refused)["error"]["code"] == "oracle_mesh_channel_rejected"

    renewed = asyncio.run(oracle_mesh_read_renew(_Request(app.state, {}, secret=WATCH)))
    assert renewed.status_code == 403

    # Consumption lives behind the service-to-service door, and the watch secret is not
    # the key to it either.
    door = endpoint_of(app, "/internal/store")
    door_response = asyncio.run(door(_FakeInternal(app.state, {
        "name": "consume_oracle_mesh_dispatch",
        "kwargs": {"dispatch_id": "dsp_" + "a" * 32, "nonce": "n" * 32},
    }, secret=WATCH)))
    assert door_response.status_code == 403
    assert _json(door_response)["error"]["code"] == "queue_channel_rejected"


class _FakeInternal:
    """The header/body surface the internal door reads, carrying a wrong secret."""

    def __init__(self, state, payload, *, secret):
        import types

        body = json.dumps(payload).encode("utf-8")
        self.app = types.SimpleNamespace(state=state)
        self.headers = {"content-type": "application/json",
                        "content-length": str(len(body)),
                        "x-padiem-queue-secret": secret}
        self._body = body

    async def body(self):
        return self._body


def test_without_a_watch_secret_the_read_leg_keeps_its_old_behaviour():
    app = _app(_db(), watch=None)
    assert _lane(app, secret=WATCH).status_code == 403
    assert _lane(app, secret=SECRET).status_code == 200


def test_health_stays_secret_free_and_still_counts():
    app = _app(_db())
    handler = endpoint_of(app, HEALTH_PATH)
    body = _json(asyncio.run(handler(_Request(app.state, None, secret=None))))
    assert body["ok"] is True
    assert body["pending_unclaimed"] == 0 and body["pending_claimed"] == 0
    assert body["received"] == 0


def test_the_queue_refuses_to_compose_two_names_for_one_secret():
    with pytest.raises(ValueError):
        create_app(connection=_db(), channel_secret=SECRET, mode="mesh",
                   ownership_map=json.dumps(OWNERSHIP), watch_secret=SECRET)
