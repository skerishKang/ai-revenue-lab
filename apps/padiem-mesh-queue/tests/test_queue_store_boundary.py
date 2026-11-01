"""#5881 follow-on — what the door does at its boundary, and what it says when it hurts.

The 2026-10-30 cutover attempt answered every write with 502 in 0 ms while reads and the
secret kept working, and the cause was one missing name: `received_at` is a datetime to the
presence store, JSON has no datetime, and the boundary's list of moment arguments did not
include it — so the beat arrived as text and `_stamp()` refused it. Nothing about the
database was wrong; the door had simply never been asked, in code, to keep that list
complete. The first test below is that question.

The rest is the shape of the door's own reporting: a store failure names its exception
class from a fixed list and never its text, a transaction found open is closed before the
call rather than poisoning every later one, and `batch()` rolls back for a BaseException
too — the shape an asyncio cancellation takes.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import pathlib
import sqlite3
import sys
from types import SimpleNamespace

QUEUE = pathlib.Path(__file__).resolve().parents[1]
CHAT = QUEUE.parents[1] / "apps" / "padiem-chat"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

import internal_store  # noqa: E402
import schema  # noqa: E402
from app.d1_sqlite import SqliteD1  # noqa: E402
from app.d1_sqlite import _Statement  # noqa: E402
from app.history import D1HistoryStore  # noqa: E402
from app.mesh_device_presence_store import (  # noqa: E402
    D1MeshDevicePresenceStore, MeshDevicePresenceStoreError)
from app.mesh_device_drive_store import D1MeshDeviceDriveStore
from app.pc_device_pairing_store import D1PcPairingStore  # noqa: E402
from internal_store import (  # noqa: E402
    INTERNAL_STORE_PATH, MOMENT_ARGUMENTS, QUEUE_SERVICE_SECRET_HEADER,
    STORE_FAILURE_CLASSES, STORE_FAILURE_PREFIX, TXN_RECOVERY_PREFIX,
)
from service import create_app  # noqa: E402

SECRET = "queue-channel-secret-value-261030"
SERVICE_SECRET = "queue-service-secret-value-261030"
DEVICE = "dev_" + "d" * 24
BEAT = "2026-10-30T04:10:46.123456Z"


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _Request:
    def __init__(self, state, wire, *, secret=SERVICE_SECRET):
        self.app = SimpleNamespace(state=state)
        body = b"{}" if wire is None else json.dumps(wire).encode("utf-8")
        self.headers = _Headers({"content-type": "application/json",
                                 "content-length": str(len(body))})
        if secret is not None:
            self.headers[QUEUE_SERVICE_SECRET_HEADER.lower()] = secret
        self._body = body

    async def body(self):
        return self._body


def _connection():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    schema.apply(connection)
    # `schema.apply` runs at import-time paths on a repository MIGRATION_DIR; the door's
    # own coercion is independent of that, so the test connection is ready here.
    return connection


def _door(connection, **kwargs):
    kwargs.setdefault("request_log", "refusals")
    app = create_app(connection=connection, channel_secret=SECRET,
                     service_secret=SERVICE_SECRET, legacy_map_lane=False, **kwargs)
    handler = [route for route in app.routes
               if getattr(route, "path", None) == INTERNAL_STORE_PATH][0].endpoint
    return handler, app.state


def _call(handler, state, method, arguments):
    return asyncio.run(handler(_Request(state, {"method": method, "arguments": arguments})))


def test_the_presence_beat_arrives_as_iso_text_and_is_written(tmp_path, capsys):
    """The exact 2026-10-30 failure: an ISO string is an instant, not a rejected argument."""

    connection = _connection()
    handler, state = _door(connection)
    response = _call(handler, state, "upsert", {
        "device_id": DEVICE, "connected": True, "received_at": BEAT,
        "credential_generation": None, "source": "mesh"})
    assert response.status_code == 200, response.body[:60]
    rows = list(connection.execute(
        "select received_at, source from mesh_device_presence where device_id = ?", (DEVICE,)))
    assert [str(row["source"]) for row in rows] == ["mesh"]
    assert "2026-10-30T04:10:46" in str(rows[0]["received_at"])
    # A healthy write prints nothing: the door is silent unless something was refused.
    assert STORE_FAILURE_PREFIX not in capsys.readouterr().out


def test_every_moment_argument_of_every_allowed_method_is_coerced():
    """`received_at` was the name this test would have caught before it reached 컴2."""

    allowed = (internal_store.DISPATCH_METHODS | internal_store.PAIRING_METHODS
               | internal_store.PRESENCE_METHODS | internal_store.DRIVE_METHODS)
    moments = set()
    for store in (D1HistoryStore, D1MeshDevicePresenceStore, D1MeshDeviceDriveStore,
                  D1PcPairingStore):
        for name in allowed:
            method = getattr(store, name, None)
            if not callable(method):
                continue
            for parameter in inspect.signature(method).parameters.values():
                if "datetime" in str(parameter.annotation):
                    moments.add(parameter.name)
    assert moments, "the stores take no instants at all? then this test is lying"
    missing = sorted(moments - set(MOMENT_ARGUMENTS))
    assert not missing, "the boundary would pass text where the store needs an instant: %s" % missing


def test_a_store_failure_names_its_class_and_never_its_text(tmp_path, capsys):
    connection = _connection()
    handler, state = _door(connection)
    customer_path = "/home/customer/private/path.txt"
    state.mesh_device_presence_store = SimpleNamespace(
        upsert=_raising(MeshDevicePresenceStoreError(customer_path)))
    response = _call(handler, state, "upsert", {
        "device_id": DEVICE, "connected": True, "received_at": BEAT,
        "credential_generation": None, "source": "mesh"})
    assert response.status_code == 502
    printed = capsys.readouterr().out
    line = [l for l in printed.splitlines() if l.startswith(STORE_FAILURE_PREFIX)][0]
    assert line == "%s path=%s rpc=upsert fail=MeshDevicePresenceStoreError run_hash=none dispatch_id=none" % (
        STORE_FAILURE_PREFIX, INTERNAL_STORE_PATH)
    assert "customer" not in printed and "path.txt" not in printed
    assert "MeshDevicePresenceStoreError" in STORE_FAILURE_CLASSES


def _raising(exc):
    def call(**_kwargs):
        raise exc
    return call


def test_an_unlisted_exception_class_is_printed_as_other(tmp_path, capsys):
    class SomewhereElseError(Exception):
        pass

    connection = _connection()
    handler, state = _door(connection)
    state.mesh_device_presence_store = SimpleNamespace(
        upsert=_raising(SomewhereElseError("caller text")))
    response = _call(handler, state, "upsert", {
        "device_id": DEVICE, "connected": True, "received_at": BEAT,
        "credential_generation": None, "source": "mesh"})
    assert response.status_code == 502
    printed = capsys.readouterr().out
    assert "fail=other" in printed
    assert "caller text" not in printed
    assert "SomewhereElseError" not in printed


def test_a_transaction_found_open_is_closed_and_said(tmp_path, capsys):
    """One connection serves the process, so an open BEGIN would poison every later write."""

    connection = _connection()
    handler, state = _door(connection)
    connection.execute("BEGIN")
    assert connection.in_transaction is True

    response = _call(handler, state, "upsert", {
        "device_id": DEVICE, "connected": True, "received_at": BEAT,
        "credential_generation": None, "source": "mesh"})

    assert response.status_code == 200
    assert connection.in_transaction is False
    printed = capsys.readouterr().out
    recovery = [l for l in printed.splitlines() if l.startswith(TXN_RECOVERY_PREFIX)]
    assert recovery == ["%s path=%s rpc=upsert run_hash=none dispatch_id=none" % (TXN_RECOVERY_PREFIX, INTERNAL_STORE_PATH)]


def test_a_batch_interrupted_by_a_baseexception_leaves_no_transaction():
    """`except Exception` let a cancellation keep its BEGIN; the next caller inherited it."""

    connection = _connection()
    database = SqliteD1(connection)
    first = database.prepare("INSERT INTO mesh_device_presence (device_id, connected,"
                             " received_at, source) VALUES (?, ?, ?, ?)").bind(
                                 DEVICE, 1, BEAT, "mesh")
    second = _Statement(connection, "SELECT 1")

    def interrupted(*_args, **_kwargs):
        raise asyncio.CancelledError()

    second._one_result = interrupted
    try:
        asyncio.run(database.batch([first, second]))
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("the cancellation must still reach the caller")
    assert connection.in_transaction is False

    # The door answers again on the next call, and the rolled-back row did not land.
    handler, state = _door(connection)
    response = _call(handler, state, "upsert", {
        "device_id": "dev_" + "e" * 24, "connected": True, "received_at": BEAT,
        "credential_generation": None, "source": "mesh"})
    assert response.status_code == 200
    left = list(connection.execute(
        "select device_id from mesh_device_presence where device_id = ?", (DEVICE,)))
    assert left == []


def test_the_correlated_request_line_keeps_its_shape(tmp_path, capsys):
    """The request line has fixed diagnostic and bounded correlation fields."""

    connection = _connection()
    handler, state = _door(connection)
    state.mesh_device_presence_store = SimpleNamespace(upsert=_raising(ValueError("nope")))
    _call(handler, state, "upsert", {
        "device_id": DEVICE, "connected": True, "received_at": BEAT,
        "credential_generation": None, "source": "mesh"})
    printed = capsys.readouterr().out
    request = [l for l in printed.splitlines() if l.startswith("MESH_QUEUE_REQUEST")][0]
    fields = [token.split("=")[0] for token in request.split()[1:]]
    assert fields == ["path", "rpc", "status", "ms", "proof", "run_hash", "dispatch_id"]
    assert request.endswith("run_hash=none dispatch_id=none")
    assert not any(token.startswith(("fail=", "txn=")) for token in request.split()[1:])
