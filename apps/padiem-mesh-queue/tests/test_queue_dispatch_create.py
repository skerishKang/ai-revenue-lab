"""#5881 follow-on — who owns a run, when the run rows are not in this database.

Every dispatch creation goes through one guard: "is this run this user's". On D1 that is a
read of `claw_run_history`. The 컴2 queue deliberately does not own conversation rows, so
the same read failed with `no such table` and the whole PC lane answered 502 the moment the
switch went live (2026-10-30 14:11) — presence kept working, dispatch creation never did.

The guard now asks a seam instead: the D1 store keeps reading `claw_run_history`, and the
queue answers from the fact the Worker establishes before it forwards anything (its routes
fetch `get_claw_run(uid, run_id)` and answer 404 without calling the queue; the door only
opens for the service secret). These tests pin both halves: a queue database stages a
dispatch without the Chat tables, and a D1 store still refuses someone else's run.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import pathlib
import sqlite3
import sys
from types import SimpleNamespace

QUEUE = pathlib.Path(__file__).resolve().parents[1]
CHAT = QUEUE.parents[1] / "apps" / "padiem-chat"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

import schema  # noqa: E402
import service  # noqa: E402
from app.d1_sqlite import SqliteD1  # noqa: E402
from app.history import D1HistoryStore, HistoryForbidden  # noqa: E402
from internal_store import INTERNAL_STORE_PATH, QUEUE_SERVICE_SECRET_HEADER  # noqa: E402
from service import create_app  # noqa: E402

SECRET = "s" * 32
CHANNEL = "c" * 32
USER = "usr_" + "b" * 32
RUN = "run_" + "a" * 32


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _Request:
    def __init__(self, state, wire):
        self.app = SimpleNamespace(state=state)
        body = json.dumps(wire).encode("utf-8")
        self.headers = _Headers({"content-type": "application/json",
                                 "content-length": str(len(body)),
                                 QUEUE_SERVICE_SECRET_HEADER.lower(): SECRET})
        self._body = body

    async def body(self):
        return self._body


def _queue_db(*, with_chat_tables: bool = False):
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    schema.apply(connection)
    if with_chat_tables:
        connection.execute("CREATE TABLE claw_run_history (id TEXT PRIMARY KEY,"
                           " run_id TEXT, user_id TEXT)")
    return connection


def _expires():
    moment = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _arguments(run_id=RUN, user_id=USER):
    return {
        "user_id": user_id,
        "run_id": run_id,
        "command_id": "cmd_" + "c" * 32,
        "tool_request_ref": "treq_" + "d" * 32,
        "request_id": "oreq_" + "e" * 32,
        "revision_ref": "rev_" + "f" * 32,
        "evidence_ref": None,
        "request_fingerprint": "f" * 64,
        "account_ref": "acct_1",
        "workspace_ref": "ws_" + "1" * 32,
        "device_id": "dev_" + "d" * 24,
        "binding_ref": "bind_1",
        "node_ref": "node_ABC",
        "root_ref": "C:",
        "path_relative": "Windows/win.ini",
        "file_path": "C:/Windows/win.ini",
        "expires_at": _expires(),
    }


def _door(connection):
    app = create_app(connection=connection, channel_secret=CHANNEL, service_secret=SECRET,
                     legacy_map_lane=False, request_log="off")
    handler = [route for route in app.routes
               if getattr(route, "path", None) == INTERNAL_STORE_PATH][0].endpoint
    return handler, app.state


def _post(handler, state, method, arguments):
    return asyncio.run(handler(_Request(state, {"method": method, "arguments": arguments})))


def test_the_queue_stages_a_dispatch_without_the_chat_tables():
    """The 2026-10-30 failure, at the door: this used to answer 502 with `no such table`."""

    connection = _queue_db()
    handler, state = _door(connection)

    response = _post(handler, state, "create_oracle_mesh_dispatch", _arguments())

    assert response.status_code == 200, response.body[:80]
    rows = list(connection.execute(
        "select dispatch_id, state, kind, path_relative from oracle_mesh_dispatch"))
    assert len(rows) == 1
    assert str(rows[0]["state"]) == "pending"
    assert str(rows[0]["kind"]) == "read"
    assert str(rows[0]["path_relative"]) == "Windows/win.ini"


def test_the_queue_store_is_wired_to_the_forwarded_ownership():
    app = create_app(connection=_queue_db(), channel_secret=CHANNEL,
                     service_secret=SECRET, legacy_map_lane=False)
    assert app.state.history_store.run_ownership is service._forwarded_run_ownership


def test_the_forwarded_ownership_refuses_only_unusable_identities():
    async def check():
        assert await service._forwarded_run_ownership(RUN, USER) is True
        assert await service._forwarded_run_ownership("", USER) is False
        assert await service._forwarded_run_ownership(RUN, None) is False

    asyncio.run(check())


def test_the_d1_store_still_refuses_a_run_it_does_not_know():
    """The seam must not become a hole: on D1 the owner is the run row, as before."""

    connection = _queue_db(with_chat_tables=True)
    store = D1HistoryStore(SqliteD1(connection))

    try:
        asyncio.run(store.create_oracle_mesh_dispatch(**_arguments()))
    except HistoryForbidden:
        pass
    else:
        raise AssertionError("a run with no row must be refused")
    assert list(connection.execute("select count(*) from oracle_mesh_dispatch"))[0][0] == 0

    connection.execute("insert into claw_run_history (id, run_id, user_id) values (?, ?, ?)",
                       ("hist_1", RUN, USER))
    staged = asyncio.run(store.create_oracle_mesh_dispatch(**_arguments()))
    assert staged and staged.get("dispatch_id")
    assert list(connection.execute("select count(*) from oracle_mesh_dispatch"))[0][0] == 1


def test_an_injected_checker_is_honoured_both_ways():
    async def deny(_run_id, _user_id):
        return False

    connection = _queue_db()
    store = D1HistoryStore(SqliteD1(connection), run_ownership=deny)
    try:
        asyncio.run(store.create_oracle_mesh_dispatch(**_arguments()))
    except HistoryForbidden:
        pass
    else:
        raise AssertionError("the injected answer must be the answer")
    assert list(connection.execute("select count(*) from oracle_mesh_dispatch"))[0][0] == 0


def test_the_rest_of_the_dispatch_lane_is_untouched():
    """create → oldest_pending → claim (once) on the queue database, end to end."""

    connection = _queue_db()
    handler, state = _door(connection)

    created = _post(handler, state, "create_oracle_mesh_dispatch", _arguments())
    assert created.status_code == 200, created.body[:80]
    dispatch_id = json.loads(created.body)["result"]["dispatch_id"]

    oldest = _post(handler, state, "oldest_pending_oracle_mesh_dispatch", {})
    assert oldest.status_code == 200
    assert json.loads(oldest.body)["result"]["dispatch_id"] == dispatch_id

    nonce = "a" * 64
    first = _post(handler, state, "claim_oracle_mesh_dispatch",
                  {"dispatch_id": dispatch_id, "nonce_sha256": nonce})
    assert first.status_code == 200, first.body[:80]
    assert json.loads(first.body)["result"] is True

    second = _post(handler, state, "claim_oracle_mesh_dispatch",
                   {"dispatch_id": dispatch_id, "nonce_sha256": "b" * 64})
    assert second.status_code == 200, second.body[:80]
    assert json.loads(second.body)["result"] is False  # one poll wins, the other does not
