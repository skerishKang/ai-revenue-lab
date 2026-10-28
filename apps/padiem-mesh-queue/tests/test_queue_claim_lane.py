"""#5881 follow-on — the claim lane behaves the same on SQLite as it does on D1.

Nothing here re-implements a rule. Each test drives the REAL route function and the REAL
store code, and asserts the invariants that make the executor lane safe: the channel
proof's 503/403 split, one winner per claim, a lease that re-delivers only after it ran
out, a re-claim that rolls the nonce so a late submission is refused, renewal that
cannot resurrect a lost claim (409), an owner's stop that reaches a claimed command
without failing the row, and consumption that accepts exactly one first delivery.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import re
import sqlite3
import sys
from types import SimpleNamespace

QUEUE = pathlib.Path(__file__).resolve().parents[1]
CHAT = QUEUE.parents[1] / "apps" / "padiem-chat"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

from app.oracle_mesh_read_return_routes import (  # noqa: E402
    ORACLE_MESH_READ_BUSY_PATH, ORACLE_MESH_READ_CANCEL_PATH, ORACLE_MESH_READ_POLL_PATH,
    oracle_mesh_read_busy_check, oracle_mesh_read_cancel_check, oracle_mesh_read_poll,
)
from app.oracle_mesh_lease_renew_routes import (  # noqa: E402
    ORACLE_MESH_READ_RENEW_PATH, oracle_mesh_read_renew,
)
from app.history import D1HistoryStore  # noqa: E402
from app.d1_sqlite import SqliteD1  # noqa: E402
from app.oracle_mesh_read_return_routes import (  # noqa: E402
    build_oracle_mesh_return_source,
)
from schema import apply  # noqa: E402
from service import create_app  # noqa: E402

SECRET = "queue-channel-secret-value-261029"
OWNERSHIP = [{"account_ref": "acct-1", "device_id": "device-1", "node_ref": "node-ABC",
              "root_ref": "C:", "path_relative": "p.txt", "file_path": "C:/p.txt",
              "command_exec": True}]
MS_Z = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\Z")
POLL_FIELDS = {
    "dispatch_id", "nonce", "expires_at", "node_ref", "file_path", "account_ref",
    "device_id", "binding_ref", "root_ref", "path_relative", "command_id", "run_id",
    "tool_request_ref", "request_id", "revision_ref", "evidence_ref",
    "request_fingerprint", "kind", "command_text", "max_bytes",
}


def _moment(seconds=0):
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


class _Headers(dict):
    """Starlette headers are case-insensitive; the routes name this one in Mixed-Case."""

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _Request:
    """The header/body surface the channel routes actually read."""

    def __init__(self, state, payload, *, secret=SECRET, wait=None,
                 content_type="application/json"):
        self.app = SimpleNamespace(state=state)
        body = b"{}" if payload is None else json.dumps(payload).encode("utf-8")
        self.headers = _Headers({
            "content-type": content_type,
            "content-length": str(len(body)),
            "x-oracle-mesh-secret": secret,
        })
        if wait is not None:
            self.headers["x-oracle-mesh-wait"] = wait
        self._body = body

    async def body(self):
        return self._body


def _app(connection, *, secret=SECRET, mode="mesh"):
    return create_app(connection=connection, channel_secret=secret,
                      ownership_map=json.dumps(OWNERSHIP), mode=mode)


def _state(connection, **kwargs):
    return _app(connection, **kwargs).state


def _stage(state, *, dispatch_id="dsp_" + "a" * 32, state_name="pending",
           claimed_until=None):
    return asyncio.run(_stage_async(state, dispatch_id=dispatch_id, state_name=state_name,
                                    claimed_until=claimed_until))


async def _stage_async(state, *, dispatch_id, state_name, claimed_until):
    await state.history_store._run(
        "INSERT INTO oracle_mesh_dispatch (dispatch_id, user_id, run_id, command_id, "
        "tool_request_ref, request_id, revision_ref, evidence_ref, request_fingerprint, "
        "account_ref, workspace_ref, device_id, binding_ref, node_ref, root_ref, "
        "path_relative, file_path, kind, state, expires_at, created_at, claimed_until, "
        "nonce_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        # One row per (user, run, tool call) is the product's own uniqueness rule, so
        # each staged dispatch carries its own run and call identity.
        dispatch_id, "usr_" + "b" * 32, "chat_pcq_" + dispatch_id[-24:],
        "cmd-" + dispatch_id[-8:], "tool-" + dispatch_id[-8:],
        "req-" + dispatch_id[-8:], "rev-" + dispatch_id[-8:], "evid-" + dispatch_id[-8:],
        "fp-" + dispatch_id[-8:], "acct-1", "ws-1", "device-1", "bind-1",
        "node-ABC", "C:", "p.txt", "C:/p.txt", "read", state_name, _moment(600),
        _moment(), claimed_until, None,
    )


def _json(response):
    return json.loads(response.body.decode("utf-8"))


def endpoint_of(app, path):
    """The mounted endpoint for one path, so the health probe needs no HTTP client."""

    return next(route.endpoint for route in app.routes if route.path == path)


def _connection():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply(connection)
    return connection


def test_missing_channel_source_answers_503_not_an_unauthenticated_claim():
    state = SimpleNamespace(history_store=None, oracle_mesh_return_source=None)
    response = asyncio.run(oracle_mesh_read_poll(
        _Request(state, {}, secret=SECRET)))
    assert response.status_code == 503
    assert _json(response)["error"]["code"] == "oracle_mesh_unconfigured"


def test_wrong_secret_and_oversized_proof_are_refused_the_same_way():
    state = _state(_connection())
    for secret in ("nope-nope-nope-nope", "z" * 513):
        response = asyncio.run(oracle_mesh_read_poll(_Request(state, {}, secret=secret)))
        assert response.status_code == 403, secret[:8]
        assert _json(response)["error"]["code"] == "oracle_mesh_channel_rejected"


def test_empty_queue_answers_ok_with_no_dispatch():
    state = _state(_connection())
    response = asyncio.run(oracle_mesh_read_poll(_Request(state, {})))
    assert response.status_code == 200
    assert _json(response) == {"ok": True, "dispatch": None}


def test_one_poll_claims_once_and_the_answer_carries_the_canonical_fields():
    state = _state(_connection())
    _stage(state)
    first = _json(asyncio.run(oracle_mesh_read_poll(_Request(state, {}))))
    assert first["ok"] is True
    assert set(first["dispatch"]) == POLL_FIELDS
    assert len(first["dispatch"]["nonce"]) >= 16
    second = _json(asyncio.run(oracle_mesh_read_poll(_Request(state, {}))))
    assert second["dispatch"] is None


def test_renewal_moves_the_lease_under_the_same_nonce_and_refuses_another_one():
    state = _state(_connection())
    _stage(state)
    claimed = _json(asyncio.run(oracle_mesh_read_poll(_Request(state, {}))))["dispatch"]
    body = {"dispatch_id": claimed["dispatch_id"], "nonce": claimed["nonce"]}
    ok = asyncio.run(oracle_mesh_read_renew(_Request(state, body)))
    assert ok.status_code == 200
    assert MS_Z.match(_json(ok)["claimed_until"]), _json(ok)
    lost = asyncio.run(oracle_mesh_read_renew(
        _Request(state, {"dispatch_id": claimed["dispatch_id"], "nonce": "f" * 32})))
    assert lost.status_code == 409
    assert _json(lost)["error"]["code"] == "oracle_mesh_claim_lost"


def test_an_expired_lease_is_handed_out_again_under_a_rotated_nonce():
    state = _state(_connection())
    _stage(state)
    first = _json(asyncio.run(oracle_mesh_read_poll(_Request(state, {}))))["dispatch"]
    store = state.history_store
    asyncio.run(store._run("UPDATE oracle_mesh_dispatch SET claimed_until=? "
                           "WHERE dispatch_id=?", _moment(-1), first["dispatch_id"]))
    again = _json(asyncio.run(oracle_mesh_read_poll(_Request(state, {}))))["dispatch"]
    assert again["nonce"] != first["nonce"]
    # The superseded claim can no longer deliver: consumption proves the nonce.
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=first["dispatch_id"], nonce=first["nonce"])) is None
    accepted = asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=again["dispatch_id"], nonce=again["nonce"]))
    assert accepted["claim"] == "first" and accepted["state"] == "received"


def test_an_owner_stop_reaches_a_claimed_command_without_failing_the_row():
    state = _state(_connection())
    dispatch_id = "dsp_" + "d" * 32
    user_id = "usr_" + "b" * 32
    _stage(state, dispatch_id=dispatch_id)
    claimed = _json(asyncio.run(oracle_mesh_read_poll(_Request(state, {}))))["dispatch"]
    store = state.history_store
    run_id = claimed["run_id"]
    stopped = asyncio.run(store.cancel_oracle_mesh_dispatches_for_run(
        user_id=user_id, run_id=run_id))
    assert stopped == 1
    row = asyncio.run(store._first("SELECT state, termination FROM oracle_mesh_dispatch "
                                   "WHERE dispatch_id=?", claimed["dispatch_id"]))
    assert row["state"] == "pending" and row["termination"] == "cancelled"
    answer = _json(asyncio.run(oracle_mesh_read_cancel_check(
        _Request(state, {"dispatch_id": claimed["dispatch_id"]}))))
    assert answer == {"ok": True, "cancelled": True}


def test_an_unclaimed_row_is_removed_from_the_queue_and_never_handed_out():
    state = _state(_connection())
    dispatch_id = "dsp_" + "e" * 32
    _stage(state, dispatch_id=dispatch_id)
    store = state.history_store
    run_id = asyncio.run(store._first("SELECT run_id FROM oracle_mesh_dispatch "
                                      "WHERE dispatch_id=?", dispatch_id))["run_id"]
    assert asyncio.run(store.cancel_oracle_mesh_dispatches_for_run(
        user_id="usr_" + "b" * 32, run_id=run_id)) == 1
    answered = _json(asyncio.run(oracle_mesh_read_poll(_Request(state, {}))))
    assert answered["dispatch"] is None


def test_consumption_refuses_an_unknown_dispatch_and_a_foreign_nonce():
    state = _state(_connection())
    store = state.history_store
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id="dsp_" + "f" * 32, nonce="a" * 32)) is None
    _stage(state)
    claimed = _json(asyncio.run(oracle_mesh_read_poll(_Request(state, {}))))["dispatch"]
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=claimed["dispatch_id"], nonce="0" * 32)) is None
    digest = asyncio.run(store._first("SELECT nonce_sha256 FROM oracle_mesh_dispatch "
                                      "WHERE dispatch_id=?", claimed["dispatch_id"]))
    assert digest["nonce_sha256"] == hashlib.sha256(
        claimed["nonce"].encode("utf-8")).hexdigest()


def test_busy_counts_a_live_claim_on_the_same_pc_and_excludes_the_asker():
    state = _state(_connection())
    _stage(state)
    claimed = _json(asyncio.run(oracle_mesh_read_poll(_Request(state, {}))))["dispatch"]
    node = claimed["node_ref"]
    other = asyncio.run(oracle_mesh_read_busy_check(
        _Request(state, {"node_ref": node, "dispatch_id": "dsp_" + "9" * 32})))
    assert _json(other) == {"ok": True, "working": True, "live_claims": 1}
    self_answer = asyncio.run(oracle_mesh_read_busy_check(
        _Request(state, {"node_ref": node, "dispatch_id": claimed["dispatch_id"]})))
    assert _json(self_answer) == {"ok": True, "working": False, "live_claims": 0}


def test_busy_refuses_to_end_work_when_the_answer_cannot_be_read():
    state = _state(_connection())

    def broken(*, node_ref, except_dispatch_id):
        raise RuntimeError("store unreachable")

    state.history_store.oracle_mesh_node_live_claims = broken
    answer = _json(asyncio.run(oracle_mesh_read_busy_check(
        _Request(state, {"node_ref": "node-ABC", "dispatch_id": "dsp_" + "1" * 32}))))
    assert answer == {"ok": True, "working": True, "live_claims": 1}


def test_busy_shares_the_channel_proof_rules():
    state = _state(_connection())
    response = asyncio.run(oracle_mesh_read_busy_check(
        _Request(state, {"node_ref": "node-ABC"}, secret="nope-nope-nope-nope")))
    assert response.status_code == 403
    assert _json(response)["error"]["code"] == "oracle_mesh_channel_rejected"


def test_health_reports_the_three_counts_the_cutover_decision_reads():
    from service import HEALTH_PATH

    app = _app(_connection())
    _stage(app.state)
    _stage(app.state, dispatch_id="dsp_" + "1" * 32)
    claimed = _json(asyncio.run(oracle_mesh_read_poll(_Request(app.state, {}))))["dispatch"]
    # One row is now claimed by an executor, one is still queued; deliver the claimed
    # one so all three shapes appear exactly once.
    asyncio.run(app.state.history_store.consume_oracle_mesh_dispatch(
        dispatch_id=claimed["dispatch_id"], nonce=claimed["nonce"]))
    probe = _Request(app.state, None, content_type="text/plain")
    body = _json(asyncio.run(endpoint_of(app, HEALTH_PATH)(probe)))
    assert body["ok"] is True
    assert body == {"ok": True, "queue": "mesh", "pending_unclaimed": 1,
                    "pending_claimed": 0, "received": 1}
