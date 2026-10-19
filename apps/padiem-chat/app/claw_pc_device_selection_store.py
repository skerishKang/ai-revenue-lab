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

import re
from datetime import datetime
from typing import Any, Protocol

from .history import _row_to_dict

_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_MAX_OWNER_CHARS = 160
_MAX_WORKSPACE_CHARS = 160


class PcDeviceSelectionStoreError(RuntimeError):
    """Store error; never carries device, account or credential material."""


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise PcDeviceSelectionStoreError(f"{name} must be bounded non-empty text")
    return value


def _device_id(value: Any) -> str:
    if not isinstance(value, str) or not _DEVICE_ID_RE.fullmatch(value):
        raise PcDeviceSelectionStoreError("device_id must be one bounded device identifier")
    return value


class PcDeviceSelectionStore(Protocol):
    async def load(self, *, owner_id: str, workspace_id: str) -> str | None: ...

    async def save(
        self, *, owner_id: str, workspace_id: str, device_id: str, now: datetime,
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
        return value if isinstance(value, str) and _DEVICE_ID_RE.fullmatch(value) else None

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


__all__ = [
    "D1PcDeviceSelectionStore",
    "PcDeviceSelectionStore",
    "PcDeviceSelectionStoreError",
]
