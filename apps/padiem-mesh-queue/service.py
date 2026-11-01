"""#5881 follow-on — the 컴2 PC queue service: the existing claim lane, run on CPython.

This is not a port. The route functions and the store code are imported from the Chat
app exactly as they are, and run here against a local SQLite database behind the same
D1 statement surface (`app.d1_sqlite.SqliteD1`). The claim, lease, nonce, renewal-409,
cancellation and consumption rules therefore have one implementation, not two that can
drift — which is the reason this lane exists at all: the failures being escaped
(`NoGilError`, `Worker exceeded CPU time limit`) are the Cloudflare Python runtime's, and
Free-plan ceilings cannot be raised.

What is served (the executor's claim lane):
    POST /api/claw/connector/mesh-reads/poll
    POST /api/claw/connector/mesh-reads/renew
    POST /api/claw/connector/mesh-reads/cancel
    POST /api/claw/connector/mesh-reads/busy     (#6113: who is working on this PC now)
    POST /api/claw/connector/mesh-reads/lane-status   (#82: counts, ages and the beat)
    POST /api/claw/connector/mesh-reads/drives        (latest drive inventory)
    POST /api/claw/connector/mesh-reads/drives/targets (active linked PC ids)
    GET  /health                      (pending/working counts, no secret, no content)

The lane-status read is the Chat route function itself, imported and served here, so the
numbers a monitor reads after the cutover come from the same SQL that produced them
before it. It accepts either the channel secret or a separate read-only watch secret
(`MESH_QUEUE_WATCH_READ_SECRET_FILE`, optional); every claim/stop/consume leg keeps
refusing the watch secret, exactly as it does in the Worker.

What is deliberately NOT served here: the result submission. Framing the answer and
writing the conversation rows stay in the Chat Worker; this service owns only the atomic
`consume` decision, which the Chat Worker will ask for over the service-to-service call.

Configuration is files and environment, mirroring the executor's own unit:
    MESH_QUEUE_DB_PATH              default /opt/padiem/mesh-queue/queue.sqlite3
    MESH_QUEUE_CHANNEL_SECRET_FILE   mode-0600 file, same secret the Worker holds
    MESH_QUEUE_OWNERSHIP_MAP_FILE    the deployment Mesh target map (JSON)
    MESH_QUEUE_EXECUTION_MODE        default mesh
    MESH_QUEUE_SERVICE_SECRET_FILE   mode-0600 file; absent means no store door
    MESH_QUEUE_WATCH_READ_SECRET_FILE mode-0600 file; absent means the read-only leg
                                    keeps the channel-secret-only behaviour (#82)
    MESH_QUEUE_LEGACY_MAP_LANE      "off" composes the channel source without any
                                    ownership map (the retired lane authorizes nobody),
                                    so the queue never depends on a map it does not use
    MESH_QUEUE_REQUEST_LOG          off (default) | refusals | all - whether the store
                                    door prints one line per call (path, allowlisted
                                    method name, status, ms, and whether the proof
                                    matched). refusals prints only non-2xx, so a healthy
                                    lane prints nothing; arguments, the secret, the
                                    header and any caller-supplied name are never printed.
                                    Two further fixed lines appear only when the door had
                                    to do something it should not have: MESH_QUEUE_
                                    STORE_FAILURE (the exception's class name, from a list)
                                    and MESH_QUEUE_TXN_RECOVERED (a transaction found open
                                    and closed before the call).

The service binds 127.0.0.1:8797. The executor reaches it there with
`ORACLE_MESH_QUEUE_ORIGIN`; the Chat Worker reaches it through the tunnel. Neither
address is published anywhere else, and the queue never listens on a public interface.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.d1_sqlite import SqliteD1
from background_history import QueueHistoryStore
from pc_output_store import PcOutputStore, PC_OUTPUT_METHODS
from app.mesh_device_presence_store import D1MeshDevicePresenceStore
from app.mesh_device_drive_store import D1MeshDeviceDriveStore
from app.mesh_device_drive_routes import (
    MESH_DEVICE_DRIVES_PATH, MESH_DEVICE_DRIVE_TARGETS_PATH,
    mesh_device_drive_report, mesh_device_drive_targets,
)
from app.oracle_mesh_lease_renew_routes import (
    ORACLE_MESH_READ_RENEW_PATH, oracle_mesh_read_renew,
)
from app.oracle_mesh_read_return_routes import (
    ORACLE_MESH_READ_BUSY_PATH, ORACLE_MESH_READ_CANCEL_PATH,
    ORACLE_MESH_READ_LANE_STATUS_PATH, ORACLE_MESH_READ_POLL_PATH,
    RETIRED_OWNERSHIP_MAP, build_oracle_mesh_return_source, oracle_mesh_read_busy_check,
    oracle_mesh_read_cancel_check, oracle_mesh_read_lane_status,
    oracle_mesh_read_poll,
)
from app.pc_device_pairing_store import D1PcPairingStore

from internal_store import (
    DISPATCH_METHODS, DRIVE_METHODS, INTERNAL_STORE_PATH, PAIRING_METHODS, PRESENCE_METHODS,
    make_internal_handler,
)
from schema import open_queue

DEFAULT_DB_PATH = "/opt/padiem/mesh-queue/queue.sqlite3"
HEALTH_PATH = "/health"
#: This service is passive: quiet traffic is normal, so "no request lately" says
#: nothing. What says something is a health read that stops answering - the same
#: store the lane runs on, asked on a schedule, with a deadline. Three failed
#: answers and the process exits so systemd's Restart=always brings a clean one.
LIVENESS_INTERVAL_SECONDS = 60
LIVENESS_DEADLINE_SECONDS = 20
LIVENESS_FAILURES_BEFORE_RESTART = 3
LIVENESS_ANSWERED = "answered"
LIVENESS_FAILED = "failed"
EXIT_UNRESPONSIVE = 87

__all__ = ["DEFAULT_DB_PATH", "EXIT_UNRESPONSIVE", "HEALTH_PATH", "LIVENESS_ANSWERED",
           "LIVENESS_FAILED", "app_from_environment", "create_app", "liveness_check",
           "liveness_rounds", "read_secret_file", "start_liveness_watchdog",
           "store_resolvers"]


async def _forwarded_run_ownership(run_id: Any, user_id: Any) -> bool:
    """Ownership, answered where the run rows live — which is not this database.

    `create_oracle_mesh_dispatch` guards a staging with "is this run this user's". On D1
    that reads `claw_run_history`; the queue does not own conversation rows by design, so
    the same query raised `no such table` here and every dispatch creation failed with 502
    the moment the switch went live (2026-10-30 14:11). The Worker establishes the owner
    before it forwards: all four dispatch routes fetch `get_claw_run(uid, run_id)`, compare
    the workspace and conversation, and answer 404 without calling the queue. The only
    caller of this door is that Worker, and the door itself only opens for a caller that
    presents the service secret (`proof=ok`). So the queue's answer is "the forwarded
    owner stands", and it refuses only an argument that is not a usable identity at all.
    """

    return (isinstance(run_id, str) and bool(run_id)
            and isinstance(user_id, str) and bool(user_id))


def store_resolvers():
    """Which allowlisted name is answered by which assembled object.

    A name can only reach an object the queue declared here, so the RPC cannot be
    pointed at anything else the process happens to hold.
    """

    def by_holder(attribute):
        return lambda state: getattr(state, attribute, None)

    table = {}
    for name in DISPATCH_METHODS:
        table[name] = by_holder("history_store")
    for name in PAIRING_METHODS:
        table[name] = by_holder("pc_device_pairing_store")
    for name in PRESENCE_METHODS:
        table[name] = by_holder("mesh_device_presence_store")
    for name in DRIVE_METHODS:
        table[name] = by_holder("mesh_device_drive_store")
    for name in PC_OUTPUT_METHODS:
        table[name] = by_holder("pc_output_store")
    return table


def read_secret_file(path: str, *, label: str) -> str:
    """Read one mode-restricted file. Values are never logged and never returned empty."""

    if not isinstance(path, str) or not path:
        raise ValueError("%s path is required" % label)
    with open(path, encoding="utf-8") as handle:
        value = handle.read().strip()
    if not value:
        raise ValueError("%s is empty" % label)
    return value


def _no_store(content: dict[str, Any]) -> JSONResponse:
    return JSONResponse(content, headers={"Cache-Control": "no-store"})


def create_app(*, db_path: str | None = None, channel_secret: str,
               ownership_map: str | None = None, mode: str = "mesh",
               service_secret: str | None = None, watch_secret: str | None = None,
               connection: Any = None, legacy_map_lane: bool = True,
               request_log: str = "off", output_directory: str | None = None) -> Starlette:
    """Assemble the queue app on the real route functions, with the store on SQLite."""

    if not isinstance(channel_secret, str) or not 16 <= len(channel_secret) <= 256:
        raise ValueError("the deployment channel secret is required")
    if legacy_map_lane:
        try:
            mapping = json.loads(ownership_map)
        except (TypeError, ValueError) as exc:
            raise ValueError("the ownership map must be JSON text") from exc
        if not isinstance(mapping, list) or not mapping:
            raise ValueError("the ownership map must be a non-empty JSON array")
    else:
        # #5573 follow-up: the retired lane authorizes nobody, so this service composes
        # without a map at all - a cutover must not wait for a V2 nobody will read.
        mapping = list(RETIRED_OWNERSHIP_MAP)

    if connection is not None:
        database = connection if isinstance(connection, SqliteD1) else SqliteD1(connection)
    else:
        database = SqliteD1(open_queue(db_path or DEFAULT_DB_PATH)[0])

    async def health(_request: Request) -> JSONResponse:
        """The three counts the cutover decision is made from, and nothing else.

        A dispatch that is being executed is still `pending` here — the state only
        leaves pending when a result lands — so "claimed" is `pending` under a nonce.
        The lane may only be switched while `unclaimed`, `claimed` and `received` are
        all zero, because those are exactly the rows a second authority could race.
        """

        rows = await database.prepare(
            "SELECT state, CASE WHEN nonce_sha256 IS NULL THEN 'unclaimed' ELSE "
            "'claimed' END AS held, COUNT(*) AS n FROM oracle_mesh_dispatch "
            "WHERE state IN ('pending','received','store_failed') "
            "GROUP BY state, held").all()
        pending_unclaimed = pending_claimed = delivered = 0
        for row in rows:
            count = int(row.get("n") or 0)
            if row.get("state") == "pending":
                if row.get("held") == "unclaimed":
                    pending_unclaimed += count
                else:
                    pending_claimed += count
            else:
                # received and store_failed both mean a result is waiting to land, so
                # the switch must not happen while any of them is non-zero.
                delivered += count
        return _no_store({"ok": True, "queue": "mesh",
                          "pending_unclaimed": pending_unclaimed,
                          "pending_claimed": pending_claimed,
                          "received": delivered})

    app = Starlette(routes=[
        Route(HEALTH_PATH, health, methods=["GET"]),
        Route(ORACLE_MESH_READ_POLL_PATH, oracle_mesh_read_poll, methods=["POST"]),
        Route(MESH_DEVICE_DRIVES_PATH, mesh_device_drive_report, methods=["POST"]),
        Route(MESH_DEVICE_DRIVE_TARGETS_PATH, mesh_device_drive_targets, methods=["POST"]),
        Route(ORACLE_MESH_READ_RENEW_PATH, oracle_mesh_read_renew, methods=["POST"]),
        Route(ORACLE_MESH_READ_CANCEL_PATH, oracle_mesh_read_cancel_check,
              methods=["POST"]),
        Route(ORACLE_MESH_READ_BUSY_PATH, oracle_mesh_read_busy_check,
              methods=["POST"]),
        # #82: the monitor's read. One handler, one SQL, served here and in the Worker.
        Route(ORACLE_MESH_READ_LANE_STATUS_PATH, oracle_mesh_read_lane_status,
              methods=["POST"]),
    ])
    app.state.history_store = QueueHistoryStore(database, run_ownership=_forwarded_run_ownership)
    app.state.mesh_device_presence_store = D1MeshDevicePresenceStore(database)
    app.state.mesh_device_drive_store = D1MeshDeviceDriveStore(database)
    app.state.pc_device_pairing_store = D1PcPairingStore(database)
    app.state.queue_database = database
    output_root = output_directory or os.environ.get("PADIEM_OUTPUT_STORE_DIR") or str(
        pathlib.Path(db_path or DEFAULT_DB_PATH).parent / "pc-outputs")
    app.state.pc_output_store = PcOutputStore(output_root, history_store=app.state.history_store)
    # The same composition the Worker root performs, run once here from files. An
    # unusable secret or map leaves the source None, and every channel route then
    # answers its documented 503 rather than serving an unauthenticated claim.
    app.state.oracle_mesh_return_source = build_oracle_mesh_return_source(
        mapping, channel_secret, mode, watch_secret)
    if app.state.oracle_mesh_return_source is None:
        raise ValueError("the queue refused to compose the channel source")
    if service_secret is not None:
        # Added after the state exists: the handler reads the objects at call time, so
        # an allowlisted name can only ever reach what is wired here.
        app.routes.append(Route(
            INTERNAL_STORE_PATH,
            make_internal_handler(state=app.state, service_secret=service_secret,
                                  resolvers=store_resolvers(),
                                  request_log=request_log),
            methods=["POST"]))
    return app


async def _liveness_ask(database: Any) -> bool:
    rows = await database.prepare(
        "SELECT COUNT(*) AS n FROM oracle_mesh_dispatch").all()
    return isinstance(rows, list)


def liveness_check(database: Any,
                   *, deadline: float = LIVENESS_DEADLINE_SECONDS,
                   pool: Any = None) -> str:
    """One health read of the store the lane runs on, bounded in wall-clock time.

    The query is plain SQLite, so a statement that stops answering is a statement
    that has stopped: the bound is held by a thread waiting on the answer, which is
    the only way to time out a call that blocks inside the database rather than
    cooperatively. A caller that expects a wedge wants no cooperation from it. The
    price of that thread is that the connection must be opened for it — which is
    what `app.d1_sqlite.connect` does, and the only way this service opens one.
    """

    owner = pool is None
    if owner:
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mesh-queue-liveness")
    try:
        future = pool.submit(lambda: asyncio.run(_liveness_ask(database)))
        try:
            return LIVENESS_ANSWERED if future.result(timeout=deadline) else LIVENESS_FAILED
        except Exception:
            return LIVENESS_FAILED
    finally:
        if owner:
            pool.shutdown(wait=False)


def liveness_rounds(database: Any, *, interval: float = LIVENESS_INTERVAL_SECONDS,
                    deadline: float = LIVENESS_DEADLINE_SECONDS,
                    sleep: Any = time.sleep, exit_process: Any = None,
                    pool: Any = None, check: Any = None) -> int:
    """Count failed health reads and give up on a service that stops answering.

    Silence on the lane is normal — nobody is forced to poll — so this watches the
    one thing that must always answer: the store behind the claim route. Three in a
    row and the process ends on its own exit code; `Restart=always` brings a clean
    one, and the exit is loud in the journal where a hung process is not.
    """

    ask = liveness_check if check is None else check
    failures = 0
    while True:
        sleep(interval)
        if ask(database, deadline=deadline, pool=pool) == LIVENESS_ANSWERED:
            failures = 0
            continue
        failures += 1
        if failures < LIVENESS_FAILURES_BEFORE_RESTART:
            continue
        print("mesh-queue watchdog: %d health reads did not answer; exiting for a "
              "supervised restart" % failures, file=sys.stderr, flush=True)
        if exit_process is None:
            return failures
        exit_process(EXIT_UNRESPONSIVE)


def _exit_unresponsive(code: int) -> None:
    """End the whole process from the watchdog thread.

    `sys.exit` in a thread ends only that thread, which is the difference between a wedge
    that is loud in the journal and a service that stays `active` while serving nobody.
    The database is WAL, so leaving without closing it is crash-safe.
    """

    os._exit(code)


def start_liveness_watchdog(database: Any) -> ThreadPoolExecutor:
    """Run the liveness rounds on their own thread, away from the serving loop."""

    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mesh-queue-liveness")
    pool.submit(liveness_rounds, database, pool=pool, exit_process=_exit_unresponsive)
    return pool


def app_from_environment() -> Starlette:
    """Build the service from the unit's environment, refusing to guess material.

    The internal call is only served when a service secret is installed: without it the
    queue still answers the executor (which is all PR-A needs), and the Chat Worker's
    later switch is what turns this half on.
    """

    service_secret_file = os.environ.get("MESH_QUEUE_SERVICE_SECRET_FILE", "").strip()
    watch_secret_file = os.environ.get("MESH_QUEUE_WATCH_READ_SECRET_FILE", "").strip()
    legacy_map_lane = (os.environ.get("MESH_QUEUE_LEGACY_MAP_LANE", "").strip().lower()
                       != "off")
    app = create_app(
        db_path=os.environ.get("MESH_QUEUE_DB_PATH", DEFAULT_DB_PATH),
        channel_secret=read_secret_file(
            os.environ.get("MESH_QUEUE_CHANNEL_SECRET_FILE",
                           "/opt/padiem/oracle-mesh/channel-secret.txt"),
            label="channel secret"),
        ownership_map=(read_secret_file(
            os.environ.get("MESH_QUEUE_OWNERSHIP_MAP_FILE",
                           "/opt/padiem/mesh-queue/ownership-map.json"),
            label="ownership map") if legacy_map_lane else None),
        legacy_map_lane=legacy_map_lane,
        mode=os.environ.get("MESH_QUEUE_EXECUTION_MODE", "mesh"),
        service_secret=(read_secret_file(service_secret_file, label="queue service secret")
                        if service_secret_file else None),
        watch_secret=(read_secret_file(watch_secret_file, label="watch read secret")
                      if watch_secret_file else None),
        request_log=os.environ.get("MESH_QUEUE_REQUEST_LOG", "off"),
    )
    start_liveness_watchdog(app.state.queue_database)
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app_from_environment(), host="127.0.0.1", port=8797, log_level="warning")
