"""#5553 server-recorded Mesh device presence receipt.

One row per canonical PC device. The Oracle/COM2 Mesh executor reports the
device's MeshCentral connection on its existing authenticated poll; the Chat
server itself derives the canonical device id from the deployment ownership
map, resolves the device's current Broker credential generation and stamps its
own receipt time. No request value becomes a device identity, an owner or a
generation.

The row is one ONLINE evidence kind for the canonical local-access authority
(#5695), never an execution grant: dispatch authorization is unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from padiem_ai_core.pc_device_identity import is_pc_device_id

from .history import _row_to_dict

_MAX_GENERATION = 1_000_000


class MeshDevicePresenceStoreError(RuntimeError):
    """Store error; never carries device, account or credential material."""


def _device(value: Any) -> str:
    if not is_pc_device_id(value):
        raise MeshDevicePresenceStoreError("device_id must be one canonical PC identity")
    return value


def _stamp(value: Any) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MeshDevicePresenceStoreError("trusted aware receipt time required")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _generation(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_GENERATION:
        raise MeshDevicePresenceStoreError("credential generation must be a bounded integer")
    return value


class MeshDevicePresenceStore(Protocol):
    async def upsert(
        self, *, device_id: str, connected: bool, received_at: datetime,
        credential_generation: int,
    ) -> bool: ...

    async def load(self, device_id: str) -> dict[str, Any] | None: ...


class D1MeshDevicePresenceStore:
    """Cloudflare D1 adapter over ``mesh_device_presence`` (migration 067)."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _row_to_dict(await statement.first())

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.run()

    async def upsert(
        self, *, device_id: str, connected: bool, received_at: datetime,
        credential_generation: int,
    ) -> bool:
        device = _device(device_id)
        if type(connected) is not bool:
            raise MeshDevicePresenceStoreError("connected must be a boolean")
        stamp = _stamp(received_at)
        generation = _generation(credential_generation)
        await self._run(
            "INSERT INTO mesh_device_presence "
            "(device_id, connected, received_at, credential_generation) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET "
            "connected=excluded.connected, received_at=excluded.received_at, "
            "credential_generation=excluded.credential_generation",
            device, 1 if connected else 0, stamp, generation,
        )
        stored = await self.load(device)
        return (
            stored is not None
            and stored["connected"] is connected
            and stored["received_at"] == stamp
            and stored["credential_generation"] == generation
        )

    async def load(self, device_id: str) -> dict[str, Any] | None:
        device = _device(device_id)
        row = await self._first(
            "SELECT device_id, connected, received_at, credential_generation "
            "FROM mesh_device_presence WHERE device_id=?",
            device,
        )
        if not isinstance(row, dict):
            return None
        connected = row.get("connected")
        generation = row.get("credential_generation")
        received_at = row.get("received_at")
        if (
            row.get("device_id") != device
            or connected not in (0, 1)
            or type(connected) is not int
            or not isinstance(received_at, str)
            or not received_at
            or type(generation) is not int
            or not 1 <= generation <= _MAX_GENERATION
        ):
            return None
        return {
            "device_id": device,
            "connected": connected == 1,
            "received_at": received_at,
            "credential_generation": generation,
        }


__all__ = [
    "D1MeshDevicePresenceStore",
    "MeshDevicePresenceStore",
    "MeshDevicePresenceStoreError",
]
