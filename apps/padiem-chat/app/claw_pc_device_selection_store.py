"""#5015 owner/workspace-scoped preferred PC target.

The selection is a **preference**, not an execution grant:

* it is written only after the canonical Broker directory confirms the device
  belongs to this owner/workspace and is currently usable;
* every execution path re-reads the Broker directory and the deployment Mesh
  target, so an offline, revoked, foreign or unmapped saved value is refused or
  reported - another PC is never substituted silently;
* it is scoped by the server-resolved owner and workspace, never by a browser
  supplied account or tenant.

The existing ``PADIEM_CHAT_DB`` D1 is reused; no request-time DDL is allowed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from padiem_ai_core.pc_device_identity import is_pc_device_id

from .history import _row_to_dict

_MAX_OWNER_CHARS = 160
_MAX_WORKSPACE_CHARS = 160


class PcDeviceSelectionStoreError(RuntimeError):
    """Store error; never carries device, account or credential material."""


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise PcDeviceSelectionStoreError(f"{name} must be bounded non-empty text")
    return value


def _device_id(value: Any) -> str:
    if not is_pc_device_id(value):
        raise PcDeviceSelectionStoreError("device_id must be one bounded device identifier")
    return value


class PcDeviceSelectionStore(Protocol):
    async def load(self, *, owner_id: str, workspace_id: str) -> str | None: ...

    async def save(
        self, *, owner_id: str, workspace_id: str, device_id: str, now: datetime,
    ) -> bool: ...

    async def replace_superseded_devices(
        self, *, owner_id: str, superseded_device_ids: list[str],
        device_id: str, now: datetime,
    ) -> bool: ...


class D1PcDeviceSelectionStore:
    """Cloudflare D1 adapter. Every value is a prepared-statement bind."""

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

    async def load(self, *, owner_id: str, workspace_id: str) -> str | None:
        owner = _text(owner_id, "owner_id", _MAX_OWNER_CHARS)
        workspace = _text(workspace_id, "workspace_id", _MAX_WORKSPACE_CHARS)
        row = await self._first(
            "SELECT device_id FROM claw_pc_device_selection "
            "WHERE user_id=? AND workspace_id=?",
            owner, workspace,
        )
        value = row.get("device_id") if isinstance(row, dict) else None
        # A malformed stored row is treated as no preference, never as a PC.
        return value if is_pc_device_id(value) else None

    async def save(
        self, *, owner_id: str, workspace_id: str, device_id: str, now: datetime,
    ) -> bool:
        owner = _text(owner_id, "owner_id", _MAX_OWNER_CHARS)
        workspace = _text(workspace_id, "workspace_id", _MAX_WORKSPACE_CHARS)
        device = _device_id(device_id)
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise PcDeviceSelectionStoreError("trusted aware time required")
        stamp = now.isoformat().replace("+00:00", "Z")
        await self._run(
            "INSERT INTO claw_pc_device_selection "
            "(user_id, workspace_id, device_id, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, workspace_id) DO UPDATE SET "
            "device_id=excluded.device_id, updated_at=excluded.updated_at",
            owner, workspace, device, stamp,
        )
        return await self.load(owner_id=owner, workspace_id=workspace) == device

    async def replace_superseded_devices(
        self, *, owner_id: str, superseded_device_ids: list[str],
        device_id: str, now: datetime,
    ) -> bool:
        """Move only this owner's saved preferences off links just superseded."""
        owner = _text(owner_id, "owner_id", _MAX_OWNER_CHARS)
        device = _device_id(device_id)
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise PcDeviceSelectionStoreError("trusted aware time required")
        if not isinstance(superseded_device_ids, list) or len(superseded_device_ids) > 100:
            raise PcDeviceSelectionStoreError("superseded_device_ids must be a bounded list")
        old_devices = list(dict.fromkeys(
            _device_id(value) for value in superseded_device_ids
        ))
        if not old_devices:
            return True
        if device in old_devices:
            raise PcDeviceSelectionStoreError("replacement cannot be superseded")
        stamp = now.isoformat().replace("+00:00", "Z")
        placeholders = ",".join("?" for _ in old_devices)
        await self._run(
            "UPDATE claw_pc_device_selection SET device_id=?, updated_at=? "
            f"WHERE user_id=? AND device_id IN ({placeholders})",
            device, stamp, owner, *old_devices,
        )
        remaining = await self._first(
            "SELECT COUNT(*) AS remaining FROM claw_pc_device_selection "
            f"WHERE user_id=? AND device_id IN ({placeholders})",
            owner, *old_devices,
        )
        return isinstance(remaining, dict) and remaining.get("remaining") == 0


async def sync_superseded_device_selections(
    store: Any, *, link: dict[str, Any], now: datetime,
) -> bool:
    """Carry queue-confirmed same-machine replacements into Chat preferences."""
    old_devices = link.get("_superseded_mesh_node_ids")
    if not isinstance(old_devices, list) or not old_devices:
        return True
    owner = link.get("user_id")
    new_device = link.get("mesh_node_id")
    if not isinstance(owner, str) or not isinstance(new_device, str):
        raise PcDeviceSelectionStoreError("replacement link identity is missing")
    updater = getattr(store, "replace_superseded_devices", None)
    if not callable(updater):
        return False
    return await updater(
        owner_id=owner,
        superseded_device_ids=old_devices,
        device_id=new_device,
        now=now,
    )


__all__ = [
    "D1PcDeviceSelectionStore",
    "PcDeviceSelectionStore",
    "PcDeviceSelectionStoreError",
    "sync_superseded_device_selections",
]
