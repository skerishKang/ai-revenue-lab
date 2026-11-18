"""Latest complete drive inventory per server-resolved Mesh PC (#6460).

This inventory is metadata, never a root approval or execution grant. Reads for
the browser occur only after the existing device-directory owner check.

#7987 keeps one more observation from the same executor round beside it: whether
the PC's user-session helper can take a command. It is the same kind of row -
latest value per device, stamped by the server - and it is display evidence
only. It lives on this store so both deployment shapes (the queue and the local
database) serve it through the object they already wire.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from padiem_ai_core.pc_drive_inventory import DriveInventoryError, validate_drive_inventory
from padiem_ai_core.pc_helper_ready import HelperReadyError, validate_helper_ready

from .history import _row_to_dict
from .mesh_device_presence_store import _device, _stamp


class MeshDeviceDriveStoreError(RuntimeError):
    """Unusable store data; no reported metadata appears in the error."""


class D1MeshDeviceDriveStore:
    """D1/SQLite adapter over migration 086's mesh_device_drives table."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def upsert_drives(
        self, *, device_id: str, drives: list[dict[str, Any]], received_at: datetime,
    ) -> bool:
        device, stamp = _device(device_id), _stamp(received_at)
        snapshot = validate_drive_inventory(drives)
        await self.db.prepare(
            "INSERT INTO mesh_device_drives (device_id, drives_json, received_at) "
            "VALUES (?, ?, ?) ON CONFLICT(device_id) DO UPDATE SET "
            "drives_json=excluded.drives_json, received_at=excluded.received_at"
        ).bind(device, json.dumps(snapshot, separators=(",", ":")), stamp).run()
        stored = await self.load_drives(device_id=device)
        return stored == {"device_id": device, "drives": snapshot, "received_at": stamp}

    async def load_drives(self, *, device_id: str) -> dict[str, Any] | None:
        device = _device(device_id)
        row = _row_to_dict(await self.db.prepare(
            "SELECT device_id, drives_json, received_at FROM mesh_device_drives "
            "WHERE device_id=?"
        ).bind(device).first())
        if row is None:
            return None
        try:
            drives = validate_drive_inventory(json.loads(row["drives_json"]))
            stamp = datetime.fromisoformat(row["received_at"].replace("Z", "+00:00"))
            if row["device_id"] != device or _stamp(stamp) != row["received_at"]:
                raise ValueError("invalid stored snapshot")
        except (KeyError, TypeError, ValueError, DriveInventoryError) as exc:
            raise MeshDeviceDriveStoreError("drive snapshot unavailable") from exc
        return {"device_id": device, "drives": drives, "received_at": row["received_at"]}

    async def upsert_helper_ready(
        self, *, device_id: str, state: dict[str, Any], received_at: datetime,
    ) -> bool:
        """#7987: replace this PC's readiness with what the executor just observed."""
        device, stamp = _device(device_id), _stamp(received_at)
        observed = validate_helper_ready(state)
        await self.db.prepare(
            "INSERT INTO mesh_device_helper_ready (device_id, state_json, received_at) "
            "VALUES (?, ?, ?) ON CONFLICT(device_id) DO UPDATE SET "
            "state_json=excluded.state_json, received_at=excluded.received_at"
        ).bind(device, json.dumps(observed, sort_keys=True, separators=(",", ":")), stamp).run()
        stored = await self.load_helper_ready(device_id=device)
        return stored == {"device_id": device, "state": observed, "received_at": stamp}

    async def load_helper_ready(self, *, device_id: str) -> dict[str, Any] | None:
        """The last observation and when the server received it, or ``None``."""
        device = _device(device_id)
        row = _row_to_dict(await self.db.prepare(
            "SELECT device_id, state_json, received_at FROM mesh_device_helper_ready "
            "WHERE device_id=?"
        ).bind(device).first())
        if row is None:
            return None
        try:
            state = validate_helper_ready(json.loads(row["state_json"]))
            stamp = datetime.fromisoformat(row["received_at"].replace("Z", "+00:00"))
            if row["device_id"] != device or _stamp(stamp) != row["received_at"]:
                raise ValueError("invalid stored readiness")
        except (KeyError, TypeError, ValueError, HelperReadyError) as exc:
            raise MeshDeviceDriveStoreError("helper readiness unavailable") from exc
        return {"device_id": device, "state": state, "received_at": row["received_at"]}


__all__ = ["D1MeshDeviceDriveStore", "MeshDeviceDriveStoreError"]
