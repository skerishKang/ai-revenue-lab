"""#7987 — helper readiness: executor relay -> authenticated queue -> SQLite -> Chat proxy.

This is the queue-backed deployment shape (the Chat host reads the queue through
its internal store door). The routes, stores, schema ledger, door and proxy are
the production implementations; only the network is replaced by an in-process
transport. No live PC, executor or service is contacted.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import pathlib
import sys

import httpx
import pytest

QUEUE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QUEUE.parent / "padiem-chat"))
sys.path.insert(0, str(QUEUE))

import internal_store  # noqa: E402
import schema  # noqa: E402
from app import queue_store_proxy  # noqa: E402
from app.mesh_device_drive_store import MeshDeviceDriveStoreError  # noqa: E402
from app.mesh_device_helper_ready_routes import MESH_DEVICE_HELPER_READY_PATH  # noqa: E402
from app.queue_store_proxy import (  # noqa: E402
    QueueBackedDriveStore, QueueStoreClient, QueueUnavailable,
)
from kagent.local_agent_mesh_helper_ready import (  # noqa: E402
    HELPER_READY_HEARTBEAT_SECONDS, HELPER_READY_PATH, MeshHelperReadyReporter,
)
from service import store_resolvers  # noqa: E402
from test_mesh_device_drives import (  # noqa: E402
    CHANNEL, DEVICE, DRIVE, OTHER, SERVICE, USER, WATCH, app_and_db, link, post,
)
from test_queue_schema_apply import _ledger_names, _open  # noqa: E402

MIGRATION = "127_mesh_device_helper_ready.sql"
TABLE = "mesh_device_helper_ready"
BOB = "usr_" + "b" * 32
READY = {"task_present": True, "install_dir_present": True, "pipe_open": True,
         "interactive_session": True, "helper_build": "9f2acb5916c0"}
MISSING = {"task_present": False, "install_dir_present": False, "pipe_open": False,
           "interactive_session": True, "helper_build": None}
UNKNOWN = dict.fromkeys(READY)


def report(app, state, *, device=DEVICE, channel=CHANNEL, extra=None):
    body = {"device_id": device, "helper": state, **(extra or {})}
    return post(app, body, channel=channel, path=MESH_DEVICE_HELPER_READY_PATH)


def chat_side(app) -> QueueBackedDriveStore:
    """What the Chat host holds when it is switched to the queue."""
    def factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)
    return QueueBackedDriveStore(QueueStoreClient(
        origin="https://queue.invalid", service_secret=SERVICE, client_factory=factory))


def stored(db) -> int:
    return db.execute("SELECT count(*) FROM %s" % TABLE).fetchone()[0]


class Recording:
    """Forwards execute() and keeps each whole statement, so replayed DDL is visible."""

    def __init__(self, connection):
        self.connection = connection
        self.statements: list[str] = []

    def execute(self, sql, *values):
        self.statements.append(" ".join(str(sql).split()))
        return self.connection.execute(sql, *values)

    def ddl(self) -> list[str]:
        words = ("CREATE TABLE", "ADD COLUMN", "DROP TABLE", "RENAME TO", "CREATE INDEX")
        return [text for text in self.statements
                if schema.LEDGER_TABLE not in text and any(word in text for word in words)]


def test_the_path_is_the_one_the_executor_posts_to():
    assert MESH_DEVICE_HELPER_READY_PATH == HELPER_READY_PATH


def test_schema_applies_the_table_once_and_requires_it():
    app, db = app_and_db()
    assert MIGRATION in {row[0] for row in db.execute("SELECT name FROM queue_schema_applied")}
    assert MIGRATION in schema.QUEUE_MIGRATIONS and TABLE in schema.QUEUE_TABLES
    assert schema.REQUIRED_COLUMNS[TABLE] == ("device_id", "state_json", "received_at")
    assert [row[1] for row in db.execute("pragma table_info(%s)" % TABLE)] == [
        "device_id", "state_json", "received_at"]
    # The first nine files are the pre-ledger backfill set; this one is not among them.
    assert MIGRATION not in schema.QUEUE_MIGRATIONS[:9]
    db.close()


def test_a_queue_database_from_before_this_table_gains_it_on_the_next_start(tmp_path, monkeypatch):
    connection = _open(tmp_path)
    before = tuple(name for name in schema.QUEUE_MIGRATIONS if name != MIGRATION)
    with monkeypatch.context() as earlier:
        # The service as it was deployed before #7987: no file, no required table.
        earlier.setattr(schema, "QUEUE_TABLES",
                        tuple(name for name in schema.QUEUE_TABLES if name != TABLE))
        schema.apply(connection, migrations=before)
    assert MIGRATION not in _ledger_names(connection)
    connection.execute("INSERT INTO mesh_device_drives VALUES (?,?,?)",
                       (DEVICE, "[]", "2026-11-01T00:00:00Z"))
    link(connection)

    recording = Recording(connection)
    schema.apply(recording)
    assert MIGRATION in _ledger_names(connection)
    # Exactly one piece of DDL ran: nothing that had already run was replayed.
    ddl = recording.ddl()
    assert len(ddl) == 1 and "CREATE TABLE IF NOT EXISTS %s" % TABLE in ddl[0], ddl
    assert connection.execute("SELECT count(*) FROM mesh_device_drives").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM pc_device_links").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM %s" % TABLE).fetchone()[0] == 0

    again = Recording(connection)
    schema.apply(again)
    assert again.ddl() == []  # A restart runs no DDL at all.
    connection.close()


def test_a_database_without_the_table_refuses_to_serve_instead_of_failing_later(tmp_path):
    connection = _open(tmp_path)
    schema.apply(connection)
    connection.execute("DROP TABLE %s" % TABLE)
    with pytest.raises(schema.QueueSchemaIncomplete) as caught:
        schema.apply(connection)
    assert TABLE in str(caught.value)
    connection.close()


def test_report_is_stored_and_chat_reads_it_through_the_queue_proxy():
    async def run():
        app, db = app_and_db()
        link(db)
        before = datetime.now(timezone.utc)
        answer = await report(app, MISSING)
        assert answer.status_code == 200
        assert set(answer.json()) == {"ok", "received_at"}  # The state is never echoed back.
        assert "no-store" in answer.headers["cache-control"]
        proxy = chat_side(app)
        row = await proxy.load_helper_ready(device_id=DEVICE)
        assert row == {"device_id": DEVICE, "state": MISSING,
                       "received_at": answer.json()["received_at"]}
        assert before <= datetime.fromisoformat(row["received_at"].replace("Z", "+00:00"))
        assert await proxy.load_helper_ready(device_id=OTHER) is None
        # The helper came up: the same row is replaced, not appended to.
        later = await report(app, READY)
        assert later.status_code == 200
        row = await proxy.load_helper_ready(device_id=DEVICE)
        assert row["state"] == READY and row["received_at"] == later.json()["received_at"]
        assert row["received_at"] >= answer.json()["received_at"]
        assert stored(db) == 1
        # "Could not be read" is a storable observation of its own.
        assert (await report(app, UNKNOWN)).status_code == 200
        assert (await proxy.load_helper_ready(device_id=DEVICE))["state"] == UNKNOWN
        # Readiness never touches the drive snapshot or any filesystem root.
        assert db.execute("SELECT count(*) FROM mesh_device_drives").fetchone()[0] == 0
        assert db.execute("SELECT roots_json FROM pc_device_links").fetchone()[0] == "[]"
    asyncio.run(run())


def test_chat_can_also_write_through_the_proxy_with_a_real_instant():
    # The boundary carries the receipt time as text and the store needs an instant.
    async def run():
        app, db = app_and_db()
        proxy = chat_side(app)
        moment = datetime(2026, 11, 18, 14, 0, 0, 123000, tzinfo=timezone.utc)
        assert await proxy.upsert_helper_ready(
            device_id=DEVICE, state=READY, received_at=moment) is True
        row = await proxy.load_helper_ready(device_id=DEVICE)
        assert row["state"] == READY
        assert datetime.fromisoformat(row["received_at"].replace("Z", "+00:00")) == moment
    asyncio.run(run())
    assert "received_at" in internal_store.MOMENT_ARGUMENTS


@pytest.mark.parametrize("secret", [None, "incorrect", WATCH, SERVICE])
def test_report_requires_the_executor_channel_secret(secret):
    async def run():
        app, db = app_and_db()
        link(db)
        answer = await report(app, READY, channel=secret)
        assert answer.status_code == 403
        assert stored(db) == 0
    asyncio.run(run())


@pytest.mark.parametrize("state,paused", [(None, None), ("revoked", None),
                                           ("pending_verification", None),
                                           ("active", "2026-11-01T00:00:00Z")])
def test_report_requires_an_active_unpaused_pairing(state, paused):
    async def run():
        app, db = app_and_db()
        if state:
            link(db, state=state, paused=paused)
        answer = await report(app, READY)
        assert answer.status_code == 403
        assert answer.json()["error"]["code"] == "mesh_helper_ready_device_unlinked"
        assert stored(db) == 0
    asyncio.run(run())


@pytest.mark.parametrize("extra", [{"user_id": USER}, {"received_at": "2099-01-01T00:00:00Z"},
                                  {"credential_generation": 1}, {"drives": [DRIVE]}])
def test_report_refuses_an_owner_a_receipt_time_or_anything_extra_from_the_wire(extra):
    async def run():
        app, db = app_and_db()
        link(db)
        answer = await report(app, READY, extra=extra)
        assert answer.status_code == 400
        assert stored(db) == 0
    asyncio.run(run())


@pytest.mark.parametrize("state", [
    None, [], "ready", {},
    {key: READY[key] for key in READY if key != "pipe_open"},
    {**READY, "user": "PRIVATE-NAME"}, {**READY, "path": "C:/Users/PRIVATE-NAME"},
    {**READY, "pipe_open": "PRIVATE-NAME"}, {**READY, "interactive_session": 1},
    {**READY, "helper_build": "PRIVATE-NAME"}, {**READY, "helper_build": "9F2ACB5916C0"},
    {**READY, "secret": "PRIVATE-VALUE-0123456789"},
])
def test_report_has_no_room_for_a_name_a_path_or_a_secret(state):
    async def run():
        app, db = app_and_db()
        link(db)
        answer = await report(app, state)
        assert answer.status_code == 400
        assert answer.json()["error"]["code"] == "mesh_helper_ready_invalid_body"
        assert "PRIVATE" not in answer.text
        assert stored(db) == 0
    asyncio.run(run())


@pytest.mark.parametrize("device", [None, "", "bad\nnode", 7, "x" * 300])
def test_report_refuses_an_unusable_device_identity(device):
    async def run():
        app, db = app_and_db()
        link(db)
        answer = await report(app, READY, device=device)
        assert answer.status_code == 400
        assert stored(db) == 0
    asyncio.run(run())


def test_each_pc_keeps_its_own_row_and_a_shared_pc_keeps_one():
    async def run():
        app, db = app_and_db()
        link(db)
        link(db, user=BOB)          # The same PC linked by a second account.
        link(db, OTHER, user=BOB)   # A different PC of that account.
        assert (await report(app, MISSING)).status_code == 200
        assert (await report(app, READY, device=OTHER)).status_code == 200
        proxy = chat_side(app)
        assert (await proxy.load_helper_ready(device_id=DEVICE))["state"] == MISSING
        assert (await proxy.load_helper_ready(device_id=OTHER))["state"] == READY
        assert stored(db) == 2
        # No owner is written beside an observation: the table has no account column.
        columns = [row[1] for row in db.execute("pragma table_info(%s)" % TABLE)]
        assert "user_id" not in columns and len(columns) == 3
        assert USER not in json.dumps([tuple(row) for row in db.execute("SELECT * FROM %s" % TABLE)])
    asyncio.run(run())


def test_readiness_is_read_only_through_the_service_door_never_the_executor_channel():
    async def run():
        app, db = app_and_db()
        link(db)
        assert (await report(app, READY)).status_code == 200
        call = {"method": "load_helper_ready", "arguments": {"device_id": DEVICE}}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                    base_url="http://queue.invalid") as client:
            for secret in (None, CHANNEL, WATCH, "incorrect"):
                headers = {} if secret is None else {internal_store.QUEUE_SERVICE_SECRET_HEADER: secret}
                refused = await client.post(internal_store.INTERNAL_STORE_PATH, json=call,
                                            headers=headers)
                assert refused.status_code == 403
                assert "pipe_open" not in refused.text
            allowed = await client.post(
                internal_store.INTERNAL_STORE_PATH, json=call,
                headers={internal_store.QUEUE_SERVICE_SECRET_HEADER: SERVICE})
            assert allowed.status_code == 200 and allowed.json()["result"]["state"] == READY
            # The report path only accepts a report: there is nothing to GET.
            assert (await client.get(MESH_DEVICE_HELPER_READY_PATH,
                                     headers={"X-Oracle-Mesh-Secret": CHANNEL})).status_code == 405
    asyncio.run(run())


def test_broken_store_is_unavailable_and_says_nothing_about_the_pc(capsys):
    async def run():
        app, db = app_and_db()
        link(db)
        db.execute("DROP TABLE %s" % TABLE)
        answer = await report(app, READY)
        assert answer.status_code == 503
        assert answer.json()["error"]["code"] == "mesh_helper_ready_unavailable"
        assert "9f2acb5916c0" not in answer.text
        with pytest.raises(QueueUnavailable):
            await chat_side(app).load_helper_ready(device_id=DEVICE)
    asyncio.run(run())
    captured = capsys.readouterr()
    assert CHANNEL not in captured.out + captured.err


@pytest.mark.parametrize("state_json", [
    "not json", "[]", json.dumps({"pipe_open": True}),
    json.dumps({**READY, "user": "PRIVATE-NAME"}), json.dumps({**READY, "pipe_open": "yes"}),
])
def test_corrupt_stored_row_is_unavailable_never_a_readiness_claim(state_json):
    async def run():
        app, db = app_and_db()
        db.execute("INSERT INTO %s VALUES (?,?,?)" % TABLE,
                   (DEVICE, state_json, "2026-11-01T00:00:00Z"))
        with pytest.raises(MeshDeviceDriveStoreError) as caught:
            await app.state.mesh_device_drive_store.load_helper_ready(device_id=DEVICE)
        assert "PRIVATE" not in str(caught.value)
        with pytest.raises(QueueUnavailable):
            await chat_side(app).load_helper_ready(device_id=DEVICE)
    asyncio.run(run())


def test_both_allowlists_route_the_two_public_names_to_the_drive_store():
    names = {"upsert_helper_ready", "load_helper_ready"}
    assert names <= internal_store.DRIVE_METHODS
    # The Chat proxy and the queue door must name exactly the same calls.
    assert queue_store_proxy.QUEUE_DRIVE_METHODS == internal_store.DRIVE_METHODS
    resolvers = store_resolvers()
    app, db = app_and_db()
    for name in names:
        assert not name.startswith("_")
        assert resolvers[name](app.state) is app.state.mesh_device_drive_store
        # Real methods on both objects - never reached through a private name.
        assert callable(getattr(app.state.mesh_device_drive_store, name))
        assert name in vars(QueueBackedDriveStore)
    db.close()


class Clock:
    def __init__(self):
        self.now = 500.0

    def __call__(self):
        return self.now


def test_executor_relay_reaches_the_chat_side_and_follows_the_helper_coming_up():
    queue, db = app_and_db()
    link(db)
    link(db, OTHER, user=BOB)
    unlinked = "node//never-linked"
    channel_calls, clock = [], Clock()

    def channel(path, body):
        channel_calls.append((path, json.loads(json.dumps(body))))
        response = asyncio.run(post(queue, body, channel=CHANNEL, path=path))
        return response.status_code, response.json()

    relay = MeshHelperReadyReporter(post=channel, clock=clock)
    proxy = chat_side(queue)

    def read(device):
        return asyncio.run(proxy.load_helper_ready(device_id=device))

    rows = [{"device_id": DEVICE, "helper": dict(MISSING)},
            {"device_id": OTHER, "helper": dict(READY)},
            {"device_id": unlinked, "helper": dict(READY)}]
    # The queue named three targets here only to prove the door's own check:
    # a PC without an active pairing is refused there and never stored.
    assert relay.observe(rows, [DEVICE, OTHER, unlinked]) == 2
    assert read(DEVICE)["state"] == MISSING and read(OTHER)["state"] == READY
    assert read(unlinked) is None and stored(db) == 2
    first = read(DEVICE)["received_at"]

    clock.now += 30
    assert relay.observe(rows[:2], [DEVICE, OTHER]) == 0  # Unchanged inside the minute.
    assert read(DEVICE)["received_at"] == first

    # The helper is installed on the first PC; the next round carries it.
    rows[0]["helper"] = dict(READY)
    assert relay.observe(rows[:2], [DEVICE, OTHER]) == 1
    assert read(DEVICE)["state"] == READY

    # An unchanged state is sent again once a minute so the receipt stays fresh.
    clock.now += HELPER_READY_HEARTBEAT_SECONDS
    assert relay.observe(rows[:2], [DEVICE, OTHER]) == 2
    assert read(DEVICE)["received_at"] >= first
    assert {path for path, _ in channel_calls} == {HELPER_READY_PATH}
    assert all(set(body) == {"device_id", "helper"} for _, body in channel_calls)
    db.close()
