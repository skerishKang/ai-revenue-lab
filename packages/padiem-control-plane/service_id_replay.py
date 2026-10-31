"""Replay defence for the signed private RPC lanes (#6417).

The shared verifier refuses a request whose id it has already seen inside the
clock window. Where that memory lives is the Worker's choice, and it must be
durable: an in-isolate dictionary would forget everything on the next cold
start, so the default store here is the Durable Object's own SQLite, which
already holds that Worker's canonical state.

Nothing here is a new authority or a new paid service. The table is one row per
request id, deleted once its window has passed, so it holds at most the traffic
of one 300 s window.
"""

from __future__ import annotations

import time
from typing import Any, Callable

__all__ = [
    "DurableObjectServiceIdReplayGuard",
    "MemoryServiceIdReplayStore",
    "SqliteServiceIdReplayStore",
]

_TABLE = "service_request_ids"
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS service_request_ids ("
    "service_id TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)"
)
_PRUNE = "DELETE FROM service_request_ids WHERE expires_at<=?"


def _rows(cursor: Any) -> list[Any]:
    if hasattr(cursor, "toArray"):
        return list(cursor.toArray())
    return list(cursor)


class MemoryServiceIdReplayStore:
    """Process-local store; the tests' stand-in, never the deployment default."""

    def __init__(self, *, clock: Callable[[], int] | None = None) -> None:
        self._seen: dict[str, int] = {}
        self._clock = clock or (lambda: int(time.time()))

    async def claim(self, service_id: str, *, expires_at: int) -> bool:
        current = int(self._clock())
        self._seen = {key: value for key, value in self._seen.items() if value > current}
        if service_id in self._seen:
            return False
        self._seen[service_id] = int(expires_at)
        return True


class SqliteServiceIdReplayStore:
    """The Durable Object's own SQLite, using the storage API the DO already has.

    ``claim`` is two statements, which is atomic enough here because a Durable
    Object runs one request at a time; the primary key makes the insert itself
    idempotent as well.
    """

    def __init__(self, storage: Any, *, clock: Callable[[], int] | None = None) -> None:
        self._storage = storage
        self._clock = clock or (lambda: int(time.time()))
        storage.sql.exec(_SCHEMA)
        storage.sql.exec(_PRUNE, int(self._clock()))

    async def claim(self, service_id: str, *, expires_at: int) -> bool:
        current = int(self._clock())
        existing = _rows(
            self._storage.sql.exec(
                "SELECT service_id FROM service_request_ids WHERE service_id=?",
                service_id,
            )
        )
        if existing:
            return False
        self._storage.sql.exec(
            "INSERT OR REPLACE INTO service_request_ids (service_id, expires_at) VALUES (?, ?)",
            service_id,
            max(int(expires_at), current + 1),
        )
        return True


class DurableObjectServiceIdReplayGuard:
    """The verifier's view of a Worker DO that owns the replay table.

    The Worker composes this with the same stub its RPC methods already use, so
    the guard lives in that Worker's canonical Durable Object — no second
    namespace, binding or service is created for it.
    """

    def __init__(self, stub: Any) -> None:
        self._stub = stub

    async def claim(self, service_id: str, *, expires_at: int) -> bool:
        answer = await self._stub.claim_service_id(
            {"service_id": service_id, "expires_at": int(expires_at)}
        )
        if not isinstance(answer, dict) or answer.get("ok") is not True:
            return False
        return answer.get("claimed") is True
