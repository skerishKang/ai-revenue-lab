"""#7987 — '명령 가능' on the PC list comes from what the PC itself reported.

This replaces the #7990 history reading (the newest ``not_executed`` dispatch,
``pc_command_ready_store``). Two things that reading could not do are pinned
here as behaviour, not as intent:

* it works on BOTH store shapes. Every list scenario below runs twice: once on
  the local database stores and once on the queue-backed proxies talking to
  the real queue service through its authenticated internal door;
* it speaks before any command is sent, including for a PC with no helper.

No PC command is issued, no dispatch is read, and no operating secret, address
or account is used.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
QUEUE = ROOT / "apps" / "padiem-mesh-queue"
MIGRATIONS = ROOT / "apps" / "padiem-chat" / "migrations"
sys.path.insert(0, str(QUEUE))
sys.path.insert(0, str(Path(__file__).parent))

from app.app_factory import create_app  # noqa: E402
from app.auth import SESSION_COOKIE, create_session_token  # noqa: E402
from sid_session_helper import sid_session_token
from app.claw_local_access_source import MESH_PRESENCE_MAX_AGE_SECONDS  # noqa: E402
from app.config import Settings  # noqa: E402
from app.d1_sqlite import SqliteD1  # noqa: E402
from app.mesh_device_drive_store import D1MeshDeviceDriveStore  # noqa: E402
from app.mesh_device_helper_ready_routes import MESH_DEVICE_HELPER_READY_PATH  # noqa: E402
from app.mesh_device_presence_store import D1MeshDevicePresenceStore  # noqa: E402
from app.pc_command_ready import (  # noqa: E402
    HELPER_READY_MAX_AGE_SECONDS, command_ready_view, load_command_ready,
    unknown_command_ready,
)
from app.pc_device_pairing_routes import PC_PAIRING_PATH  # noqa: E402
from app.pc_device_pairing_store import D1PcPairingStore  # noqa: E402
from app.queue_store_proxy import (  # noqa: E402
    QueueBackedDriveStore, QueueBackedPairingStore, QueueBackedPresenceStore,
    QueueStoreClient,
)

from test_5573_pc_device_pairing import ORIGIN, SESSION_SECRET  # noqa: E402

OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32
CHANNEL = "synthetic-ready-channel-secret"
SERVICE = "synthetic-ready-service-secret"
HELP = "PC 도우미를 다시 설치해 주세요"
READY = {"task_present": True, "install_dir_present": True, "pipe_open": True,
         "interactive_session": True, "helper_build": "9f2acb5916c0"}
MISSING = {"task_present": False, "install_dir_present": False, "pipe_open": False,
           "interactive_session": True, "helper_build": None}
STOPPED = {**READY, "pipe_open": False}
NO_SESSION = {**READY, "pipe_open": False, "interactive_session": False}
UNKNOWN_STATE = dict.fromkeys(READY)
UNKNOWN = unknown_command_ready()
LINK_SQL = ("INSERT INTO pc_device_links (link_id,user_id,mesh_node_id,state,roots_json,"
            "created_at,updated_at,paused_at) VALUES (?,?,?,?,?,?,?,?)")


def node(name: str) -> str:
    return "node//synthetic-" + name


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def run(coro):
    return asyncio.run(coro)


# ---- one row -> three words --------------------------------------------------
def row(state, *, age=5.0, device="node//one", now=None):
    now = now or _now()
    return {"device_id": device, "state": state,
            "received_at": _iso(now - timedelta(seconds=age))}, now


@pytest.mark.parametrize("state,expected,reason", [
    (READY, "ready", None),
    ({**READY, "helper_build": None}, "ready", None),
    # A listening pipe is a running helper, whatever else could not be read.
    ({**UNKNOWN_STATE, "pipe_open": True}, "ready", None),
    (MISSING, "not_ready", "helper_missing"),
    # No task file means the executor cannot reach a helper at all.
    ({**UNKNOWN_STATE, "task_present": False}, "not_ready", "helper_missing"),
    (STOPPED, "not_ready", "helper_stopped"),
    (NO_SESSION, "not_ready", "no_user_session"),
    ({**STOPPED, "interactive_session": None}, "not_ready", None),
    ({**UNKNOWN_STATE, "pipe_open": False}, "not_ready", None),
    (UNKNOWN_STATE, "unknown", None),
    ({**UNKNOWN_STATE, "task_present": True, "interactive_session": True}, "unknown", None),
])
def test_one_row_becomes_one_of_three_words(state, expected, reason):
    stored, now = row(state)
    view = command_ready_view(stored, device_id="node//one", now=now)
    assert view["command_ready"] == expected
    assert view["command_ready_reason"] == reason
    # The existing field keeps its name: it now carries when the PC was last
    # seen not ready, and stays empty otherwise.
    assert view["last_user_session_failure_at"] == (
        stored["received_at"] if expected == "not_ready" else None)
    assert set(view) == set(UNKNOWN)


def test_a_report_older_than_180_seconds_is_unknown_in_both_directions():
    assert HELPER_READY_MAX_AGE_SECONDS == 180 == MESH_PRESENCE_MAX_AGE_SECONDS
    for state in (READY, MISSING):
        fresh, now = row(state, age=179)
        assert command_ready_view(fresh, device_id="node//one", now=now) != UNKNOWN
        stale, now = row(state, age=181)
        assert command_ready_view(stale, device_id="node//one", now=now) == UNKNOWN
        future, now = row(state, age=-30)  # A receipt from the future proves nothing.
        assert command_ready_view(future, device_id="node//one", now=now) == UNKNOWN


@pytest.mark.parametrize("stored", [
    None, "row", [], {},
    {"device_id": "node//one", "state": READY},
    {"device_id": "node//one", "state": READY, "received_at": "yesterday"},
    {"device_id": "node//one", "state": READY, "received_at": "2026-11-18T01:00:00"},
    {"device_id": "node//someone-else", "state": READY, "received_at": "NOW"},
    # A row written by an older or different shape of the observation: fewer
    # fields, other names, or a legacy single flag. None of them is a claim.
    {"device_id": "node//one", "state": {"pipe_open": True}, "received_at": "NOW"},
    {"device_id": "node//one", "state": {"ready": True}, "received_at": "NOW"},
    {"device_id": "node//one", "state": {**READY, "helper_running": True}, "received_at": "NOW"},
    {"device_id": "node//one", "state": {**READY, "pipe_open": "yes"}, "received_at": "NOW"},
    {"device_id": "node//one", "state": None, "received_at": "NOW"},
])
def test_a_missing_partial_or_other_version_row_is_unknown_never_not_ready(stored):
    now = _now()
    if isinstance(stored, dict) and stored.get("received_at") == "NOW":
        stored = {**stored, "received_at": _iso(now)}
    assert command_ready_view(stored, device_id="node//one", now=now) == UNKNOWN


def test_reading_goes_through_the_public_call_and_any_fault_is_unknown():
    now = _now()
    calls = []

    class Store:
        async def load_helper_ready(self, *, device_id):
            calls.append(device_id)
            return {"device_id": device_id, "state": READY, "received_at": _iso(now)}

        def __getattr__(self, name):
            raise AssertionError("private or undeclared store access: " + name)

    assert run(load_command_ready(Store(), device_id="node//one", now=now))[
        "command_ready"] == "ready"
    assert calls == ["node//one"]

    class Broken:
        async def load_helper_ready(self, *, device_id):
            raise RuntimeError("queue unavailable")

    class Sync:
        def load_helper_ready(self, *, device_id):
            return {"device_id": device_id, "state": MISSING, "received_at": _iso(now)}

    assert run(load_command_ready(Broken(), device_id="node//one", now=now)) == UNKNOWN
    assert run(load_command_ready(Sync(), device_id="node//one", now=now))[
        "command_ready"] == "not_ready"
    for absent in (None, object()):
        assert run(load_command_ready(absent, device_id="node//one", now=now)) == UNKNOWN


# ---- the two deployment shapes -------------------------------------------------
def _queue_module(name: str):
    unique = "mesh_queue_%s_command_ready_7987" % name
    module = sys.modules.get(unique)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(unique, QUEUE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(unique, None)
        raise
    return module


class World:
    """One deployment shape: where rows are written and what the Chat host reads."""

    def __init__(self, shape: str):
        self.shape = shape
        self.connection = sqlite3.connect(":memory:", isolation_level=None,
                                          check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        if shape == "local":
            # The host's own database: every Chat migration, then the D1 stores.
            for path in sorted(MIGRATIONS.glob("*.sql")):
                self.connection.executescript(path.read_text(encoding="utf-8"))
            database = SqliteD1(self.connection)
            self.pairing = D1PcPairingStore(database)
            self.presence = D1MeshDevicePresenceStore(database)
            self.drives = D1MeshDeviceDriveStore(database)
            self.queue = None
        else:
            # PC_QUEUE_BACKEND=com2: the real queue service answers the proxies.
            _queue_module("schema").apply(self.connection)
            self.queue = _queue_module("service").create_app(
                connection=self.connection, channel_secret=CHANNEL, service_secret=SERVICE,
                legacy_map_lane=False)
            client = QueueStoreClient(
                origin="https://queue.invalid", service_secret=SERVICE,
                client_factory=lambda **kwargs: httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self.queue), **kwargs))
            self.pairing = QueueBackedPairingStore(client)
            self.presence = QueueBackedPresenceStore(client)
            self.drives = QueueBackedDriveStore(client)

    def link(self, device: str, *, user: str = OWNER, label: str | None = None) -> None:
        self.connection.execute(LINK_SQL, (
            "link-%s-%s" % (device, user[-1]), user, device, "active", "[]",
            "2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z", None))
        if label is not None:
            self.connection.execute(
                "UPDATE pc_device_links SET label=? WHERE mesh_node_id=? AND user_id=?",
                (label, device, user))

    async def online(self, device: str, *, connected: bool = True) -> None:
        assert await self.presence.upsert(
            device_id=device, connected=connected, received_at=_now(),
            credential_generation=None, source="mesh") is True

    async def report(self, device: str, state: dict, *, age: float = 0.0) -> None:
        if self.queue is not None and not age:
            # The way it arrives in operation: the executor's channel post.
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.queue),
                                        base_url="http://queue.invalid") as client:
                answer = await client.post(
                    MESH_DEVICE_HELPER_READY_PATH, json={"device_id": device, "helper": state},
                    headers={"X-Oracle-Mesh-Secret": CHANNEL})
            assert answer.status_code == 200, answer.text
            return
        assert await self.drives.upsert_helper_ready(
            device_id=device, state=state,
            received_at=_now() - timedelta(seconds=age)) is True

    def chat(self, *, drives="wired", history=None):
        app = create_app(Settings(runtime_mode="mock", session_secret=SESSION_SECRET,
                                  public_base_url=ORIGIN))
        app.state.pc_device_pairing_store = self.pairing
        app.state.mesh_device_presence_store = self.presence
        if drives == "wired":
            app.state.mesh_device_drive_store = self.drives
        elif drives is not None:
            app.state.mesh_device_drive_store = drives
        app.state.history_store = history if history is not None else _NoHistory()
        return app


class _NoHistory:
    """The list must not read a dispatch, a run or anything else from history."""

    def __getattr__(self, name):
        raise AssertionError("the PC list touched the history store: " + name)


async def pairings(app, *, user=OWNER):
    token = sid_session_token(app.state.settings, user, now=int(_now().timestamp()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                                headers={"Origin": ORIGIN},
                                cookies={SESSION_COOKIE: token}) as session:
        return await session.get(PC_PAIRING_PATH)


def by_node(response) -> dict[str, dict]:
    assert response.status_code == 200, response.text
    return {link["mesh_node_id"]: link for link in response.json()["links"]}


def words(link) -> tuple:
    return link["command_ready"], link["command_ready_reason"]


@pytest.fixture(params=["local", "queue"])
def world(request):
    value = World(request.param)
    yield value
    value.connection.close()


def test_list_says_what_each_connected_pc_reported(world):
    cases = {
        "ready": (READY, 0, ("ready", None)),
        "missing": (MISSING, 0, ("not_ready", "helper_missing")),
        "stopped": (STOPPED, 0, ("not_ready", "helper_stopped")),
        "nosession": (NO_SESSION, 0, ("not_ready", "no_user_session")),
        "unreadable": (UNKNOWN_STATE, 0, ("unknown", None)),
        "stale": (MISSING, 181, ("unknown", None)),
        "silent": (None, 0, ("unknown", None)),
    }

    async def scenario():
        for name, (state, age, _expected) in cases.items():
            world.link(node(name))
            await world.online(node(name))
            if state is not None:
                await world.report(node(name), state, age=age)
        return by_node(await pairings(world.chat()))

    links = run(scenario())
    assert set(links) == {node(name) for name in cases}
    for name, (_state, _age, expected) in cases.items():
        link = links[node(name)]
        assert words(link) == expected, (world.shape, name)
        assert link["online"] is True
        assert (link["last_user_session_failure_at"] is not None) == (expected[0] == "not_ready")


def test_helper_coming_up_turns_not_ready_into_ready(world):
    async def scenario():
        world.link(node("pc"))
        await world.online(node("pc"))
        app = world.chat()
        before_any_report = by_node(await pairings(app))[node("pc")]
        await world.report(node("pc"), MISSING)
        missing = by_node(await pairings(app))[node("pc")]
        await world.report(node("pc"), READY)
        ready = by_node(await pairings(app))[node("pc")]
        await world.report(node("pc"), STOPPED)
        stopped = by_node(await pairings(app))[node("pc")]
        return before_any_report, missing, ready, stopped

    before_any_report, missing, ready, stopped = run(scenario())
    # Known before any command was sent - and nothing is claimed with no report.
    assert words(before_any_report) == ("unknown", None)
    assert words(missing) == ("not_ready", "helper_missing")
    assert words(ready) == ("ready", None) and ready["last_user_session_failure_at"] is None
    assert words(stopped) == ("not_ready", "helper_stopped")


def test_a_pc_that_is_not_connected_now_is_never_called_ready_or_not_ready(world):
    async def scenario():
        for name, state in (("offline", READY), ("neverseen", MISSING)):
            world.link(node(name))
            await world.report(node(name), state)
        await world.online(node("offline"), connected=False)
        return by_node(await pairings(world.chat()))

    links = run(scenario())
    for name in ("offline", "neverseen"):
        assert links[node(name)]["online"] is False
        assert words(links[node(name)]) == ("unknown", None)
        assert links[node(name)]["last_user_session_failure_at"] is None


def test_another_accounts_pc_is_neither_read_nor_shown(world):
    asked = []

    class Spy:
        def __init__(self, inner):
            self._inner = inner

        async def load_helper_ready(self, *, device_id):
            asked.append(device_id)
            return await self._inner.load_helper_ready(device_id=device_id)

    async def scenario():
        world.link(node("mine"))
        world.link(node("theirs"), user=OTHER)
        world.link(node("shared"))
        world.link(node("shared"), user=OTHER)
        for name, state in (("mine", MISSING), ("theirs", READY), ("shared", READY)):
            await world.online(node(name))
            await world.report(node(name), state)
        app = world.chat(drives=Spy(world.drives))
        mine = await pairings(app)
        seen_for_owner = list(asked)
        asked.clear()
        theirs = await pairings(app, user=OTHER)
        return mine, seen_for_owner, theirs, list(asked)

    mine, seen_for_owner, theirs, seen_for_other = run(scenario())
    assert set(by_node(mine)) == {node("mine"), node("shared")}
    assert sorted(seen_for_owner) == sorted([node("mine"), node("shared")])
    assert node("theirs") not in mine.text
    assert words(by_node(mine)[node("mine")]) == ("not_ready", "helper_missing")
    assert set(by_node(theirs)) == {node("theirs"), node("shared")}
    assert sorted(seen_for_other) == sorted([node("theirs"), node("shared")])
    assert node("mine") not in theirs.text
    # A shared PC is one PC: both accounts see the same word for it.
    assert words(by_node(mine)[node("shared")]) == words(by_node(theirs)[node("shared")]) == (
        "ready", None)


def test_answer_carries_three_fields_and_none_of_the_raw_observation(world):
    async def scenario():
        world.link(node("pc"))
        await world.online(node("pc"))
        await world.report(node("pc"), MISSING)
        return await pairings(world.chat())

    response = run(scenario())
    link = by_node(response)[node("pc")]
    assert {"command_ready", "command_ready_reason", "last_user_session_failure_at"} <= set(link)
    for raw in ("pipe_open", "task_present", "install_dir_present", "interactive_session",
                "helper_build", "state_json", "9f2acb5916c0", CHANNEL, SERVICE,
                "nonce_sha256", "result_sha256", "command_text"):
        assert raw not in response.text, raw
    assert link["last_user_session_failure_at"].endswith("Z")


def test_signed_out_reader_gets_nothing(world):
    async def scenario():
        world.link(node("pc"))
        await world.online(node("pc"))
        await world.report(node("pc"), READY)
        app = world.chat()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                                    headers={"Origin": ORIGIN}) as session:
            return await session.get(PC_PAIRING_PATH)

    response = run(scenario())
    assert response.status_code == 401
    assert "command_ready" not in response.text


# ---- faults, absence, and what is gone -------------------------------------------
def test_a_failing_readiness_store_never_fails_the_list():
    world = World("local")

    class Broken:
        async def load_helper_ready(self, *, device_id):
            raise RuntimeError("store unavailable")

    async def scenario():
        world.link(node("pc"))
        await world.online(node("pc"))
        results = []
        for drives in (Broken(), object(), None):
            results.append(by_node(await pairings(world.chat(drives=drives)))[node("pc")])
        return results

    for link in run(scenario()):
        # The cloud Worker shape wires no device store at all: same answer.
        assert link["online"] is True
        assert words(link) == ("unknown", None)
    world.connection.close()


def test_the_history_reading_is_gone_and_the_list_names_no_dispatch():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.pc_command_ready_store")
    routes = (ROOT / "apps" / "padiem-chat" / "app" / "pc_device_pairing_routes.py").read_text(
        encoding="utf-8")
    judge = (ROOT / "apps" / "padiem-chat" / "app" / "pc_command_ready.py").read_text(
        encoding="utf-8")
    for source in (routes, judge):
        assert "latest_user_mode_results_for_owner" not in source
        assert "oracle_mesh_dispatch" not in source
        # No private store method is reached for from either file (#7990's fault).
        assert "store._all" not in source and "._all(" not in source
    assert "not_executed" not in routes
    assert "load_command_ready(readiness" in routes


def test_error_answer_keeps_the_code_and_adds_the_remedy():
    # Unchanged from #7975: the user-session error text still offers the remedy.
    from app.mcp_gateway_session import _failure

    failed = _failure("user_session_unavailable")
    assert failed["code"] == "user_session_unavailable"
    assert HELP in failed["answer"]
    generic = _failure("user_helper_timeout")
    assert HELP not in generic["answer"]
