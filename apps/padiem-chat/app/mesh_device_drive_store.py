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
from padiem_ai_core.pc_helper_ready import HELPER_READY_FLAGS, HelperReadyError, validate_helper_ready

from .history import _row_to_dict
from .d1_rows import rows_from_result
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
        sha = observed.get("helper_sha256")
        release = observed.get("helper_version")
        version = observed.get("mesh_agent_version")
        healthy = stamp if (observed["helper_build"] is not None
                            and all(observed[key] is True for key in HELPER_READY_FLAGS)) else None
        await self.db.prepare(
            "INSERT INTO mesh_device_helper_ready "
            "(device_id, state_json, received_at, helper_sha256, helper_version, mesh_agent_version, last_healthy_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(device_id) DO UPDATE SET "
            "state_json=excluded.state_json, received_at=excluded.received_at, "
            "helper_sha256=excluded.helper_sha256, helper_version=excluded.helper_version, "
            "mesh_agent_version=excluded.mesh_agent_version, "
            "last_healthy_at=CASE WHEN mesh_device_helper_ready.last_healthy_at IS NULL "
            "OR julianday(excluded.last_healthy_at) > julianday(mesh_device_helper_ready.last_healthy_at) "
            "THEN excluded.last_healthy_at ELSE mesh_device_helper_ready.last_healthy_at END"
        ).bind(device, json.dumps(observed, sort_keys=True, separators=(",", ":")),
               stamp, sha, release, version, healthy).run()
        target = observed.get("update_target_sha256")
        result = observed.get("update_result")
        outcome = ("rollback" if result == "rollback" else
                   "failed" if result in ("hash_mismatch", "signature_mismatch", "download_failed") else
                   "updated" if target == sha and result in ("success", "current") else None)
        if target and outcome:
            await self.db.prepare(
                "INSERT INTO pc_helper_rollout_outcomes (device_id, release_sha256, outcome, received_at) "
                "VALUES (?,?,?,?) ON CONFLICT(device_id, release_sha256) DO UPDATE SET "
                "outcome=excluded.outcome, received_at=excluded.received_at "
                "WHERE julianday(excluded.received_at)>=julianday(pc_helper_rollout_outcomes.received_at)"
            ).bind(device, target, outcome, stamp).run()
        stored = await self.load_helper_ready(device_id=device)
        return stored == {"device_id": device, "state": observed, "received_at": stamp}

    async def load_rollout_outcomes(self, *, sha256: str) -> dict[str, str]:
        result = await self.db.prepare(
            "SELECT device_id, outcome FROM pc_helper_rollout_outcomes WHERE release_sha256=?"
        ).bind(sha256).run()
        return {row["device_id"]: row["outcome"] for item in rows_from_result(result)
                if (row := _row_to_dict(item)) is not None}

    async def load_helper_ready(self, *, device_id: str, include_versions: bool = False) -> dict[str, Any] | None:
        """The last observation and when the server received it, or ``None``."""
        device = _device(device_id)
        row = _row_to_dict(await self.db.prepare(
            "SELECT device_id, state_json, received_at, helper_sha256, helper_version, mesh_agent_version, "
            "last_healthy_at FROM mesh_device_helper_ready "
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
        result = {"device_id": device, "state": state, "received_at": row["received_at"]}
        if include_versions:
            result["helper_sha256"] = row.get("helper_sha256")
            result["helper_version"] = row.get("helper_version")
            result["mesh_agent_version"] = row.get("mesh_agent_version")
            result["last_healthy_at"] = row.get("last_healthy_at")
        return result


__all__ = ["D1MeshDeviceDriveStore", "MeshDeviceDriveStoreError"]
