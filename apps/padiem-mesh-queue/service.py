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
    GET  /health                      (pending/working counts, no secret, no content)

What is deliberately NOT served here: the result submission. Framing the answer and
writing the conversation rows stay in the Chat Worker; this service owns only the atomic
`consume` decision, which the Chat Worker will ask for over the service-to-service call.

Configuration is files and environment, mirroring the executor's own unit:
    MESH_QUEUE_DB_PATH              default /opt/padiem/mesh-queue/queue.sqlite3
    MESH_QUEUE_CHANNEL_SECRET_FILE   mode-0600 file, same secret the Worker holds
    MESH_QUEUE_OWNERSHIP_MAP_FILE    the deployment Mesh target map (JSON)
    MESH_QUEUE_EXECUTION_MODE        default mesh
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore
from app.mesh_device_presence_store import D1MeshDevicePresenceStore
from app.oracle_mesh_lease_renew_routes import (
    ORACLE_MESH_READ_RENEW_PATH, oracle_mesh_read_renew,
)
from app.oracle_mesh_read_return_routes import (
    ORACLE_MESH_READ_BUSY_PATH, ORACLE_MESH_READ_CANCEL_PATH, ORACLE_MESH_READ_POLL_PATH,
    build_oracle_mesh_return_source, oracle_mesh_read_busy_check,
    oracle_mesh_read_cancel_check, oracle_mesh_read_poll,
)
from app.pc_device_pairing_store import D1PcPairingStore

from internal_store import (
    DISPATCH_METHODS, INTERNAL_STORE_PATH, PAIRING_METHODS, PRESENCE_METHODS,
    make_internal_handler,
)
from schema import open_queue

DEFAULT_DB_PATH = "/opt/padiem/mesh-queue/queue.sqlite3"
HEALTH_PATH = "/health"

__all__ = ["DEFAULT_DB_PATH", "HEALTH_PATH", "create_app", "read_secret_file",
           "store_resolvers"]


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
               ownership_map: str, mode: str = "mesh", service_secret: str | None = None,
               connection: Any = None) -> Starlette:
    """Assemble the queue app on the real route functions, with the store on SQLite."""

    if not isinstance(channel_secret, str) or not 16 <= len(channel_secret) <= 256:
        raise ValueError("the deployment channel secret is required")
    try:
        mapping = json.loads(ownership_map)
    except (TypeError, ValueError) as exc:
        raise ValueError("the ownership map must be JSON text") from exc
    if not isinstance(mapping, list) or not mapping:
        raise ValueError("the ownership map must be a non-empty JSON array")

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
        Route(ORACLE_MESH_READ_RENEW_PATH, oracle_mesh_read_renew, methods=["POST"]),
        Route(ORACLE_MESH_READ_CANCEL_PATH, oracle_mesh_read_cancel_check,
              methods=["POST"]),
        Route(ORACLE_MESH_READ_BUSY_PATH, oracle_mesh_read_busy_check,
              methods=["POST"]),
    ])
    app.state.history_store = D1HistoryStore(database)
    app.state.mesh_device_presence_store = D1MeshDevicePresenceStore(database)
    app.state.pc_device_pairing_store = D1PcPairingStore(database)
    # The same composition the Worker root performs, run once here from files. An
    # unusable secret or map leaves the source None, and every channel route then
    # answers its documented 503 rather than serving an unauthenticated claim.
    app.state.oracle_mesh_return_source = build_oracle_mesh_return_source(
        mapping, channel_secret, mode)
    if app.state.oracle_mesh_return_source is None:
        raise ValueError("the queue refused to compose the channel source")
    if service_secret is not None:
        # Added after the state exists: the handler reads the objects at call time, so
        # an allowlisted name can only ever reach what is wired here.
        app.routes.append(Route(
            INTERNAL_STORE_PATH,
            make_internal_handler(state=app.state, service_secret=service_secret,
                                  resolvers=store_resolvers()),
            methods=["POST"]))
    return app


def app_from_environment() -> Starlette:
    """Build the service from the unit's environment, refusing to guess material.

    The internal call is only served when a service secret is installed: without it the
    queue still answers the executor (which is all PR-A needs), and the Chat Worker's
    later switch is what turns this half on.
    """

    service_secret_file = os.environ.get("MESH_QUEUE_SERVICE_SECRET_FILE", "").strip()
    return create_app(
        db_path=os.environ.get("MESH_QUEUE_DB_PATH", DEFAULT_DB_PATH),
        channel_secret=read_secret_file(
            os.environ.get("MESH_QUEUE_CHANNEL_SECRET_FILE",
                           "/opt/padiem/oracle-mesh/channel-secret.txt"),
            label="channel secret"),
        ownership_map=read_secret_file(
            os.environ.get("MESH_QUEUE_OWNERSHIP_MAP_FILE",
                           "/opt/padiem/mesh-queue/ownership-map.json"),
            label="ownership map"),
        mode=os.environ.get("MESH_QUEUE_EXECUTION_MODE", "mesh"),
        service_secret=(read_secret_file(service_secret_file, label="queue service secret")
                        if service_secret_file else None),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app_from_environment(), host="127.0.0.1", port=8797, log_level="warning")
