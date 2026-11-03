"""#5553 server-recorded Mesh device presence receipt.

One row per canonical PC device. The Oracle/COM2 Mesh executor reports the
device's MeshCentral connection on its existing authenticated poll; the Chat
server itself derives the canonical device id from the deployment ownership
map and stamps its own receipt time. Broker generation is retained when
resolved; requirement 6 permits a Mesh-only receipt with source='mesh' and
NULL generation, without requiring Broker registration. No request value becomes a device identity, an owner or a
generation.

The row is one ONLINE evidence kind for the canonical local-access authority
(#5695), never an execution grant: dispatch authorization is unchanged.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Protocol

from padiem_ai_core.pc_device_identity import is_pc_device_id

from .history import _row_to_dict

_MAX_GENERATION = 1_000_000
#: One machine may serve several accounts (adopt keys links by the pair), but
#: a count beyond this is not a deployment state any caller of ours produces.
_MAX_ACCOUNT_REFS = 8
_MAX_ACCOUNT_REF_CHARS = 320


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


def _account_refs(value: Any) -> str | None:
    """The owner accounts one presence row is recorded for, JSON-encoded.

    #6695 PR-2: the receipt binds the device to the accounts the pairing
    directory answered with (the map's single ref on a legacy row) at record
    time, so a later reader can scope by owner from the row itself instead of
    re-deriving ownership on every read. ``None`` writes the row exactly as
    before; anything malformed is a store error, never a partial write.
    """
    if value is None:
        return None
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_ACCOUNT_REFS:
        raise MeshDevicePresenceStoreError(
            "account_refs must be a list of 1..8 owner accounts")
    refs: list[str] = []
    for entry in value:
        if (
            not isinstance(entry, str) or not entry
            or len(entry) > _MAX_ACCOUNT_REF_CHARS
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in entry)
        ):
            raise MeshDevicePresenceStoreError(
                "account_ref must be a bounded visible string")
        if entry not in refs:
            refs.append(entry)
    return json.dumps(refs)


class MeshDevicePresenceStore(Protocol):
    async def upsert(
        self, *, device_id: str, connected: bool, received_at: datetime,
        credential_generation: int | None, source: str = "broker",
        account_refs: list[str] | None = None,
    ) -> bool: ...

    async def load(self, device_id: str) -> dict[str, Any] | None: ...


class D1MeshDevicePresenceStore:
    """Cloudflare D1 adapter over ``mesh_device_presence`` (migrations 067 + 070 + 091)."""

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
        credential_generation: int | None, source: str = "broker",
        account_refs: list[str] | None = None,
    ) -> bool:
        device = _device(device_id)
        if type(connected) is not bool:
            raise MeshDevicePresenceStoreError("connected must be a boolean")
        stamp = _stamp(received_at)
        if source not in ("broker", "mesh"):
            raise MeshDevicePresenceStoreError("presence source invalid")
        generation = (None if source == "mesh" and credential_generation is None
                      else _generation(credential_generation))
        refs_json = _account_refs(account_refs)
        # #6694 (A): a connected beat also stamps the moment the node was last
        # actually seen connected; a disconnected beat keeps the old value, so
        # an offline row can still name its last contact.
        last_connected = stamp if connected else None
        if refs_json is None:
            # No owner list given: the exact statement every deployment ran
            # before PR-2, so a database (or a queue proxy) that has not taken
            # migration 091 yet keeps working unchanged.
            await self._run(
                "INSERT INTO mesh_device_presence "
                "(device_id, connected, received_at, credential_generation, source, "
                " last_connected_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(device_id) DO UPDATE SET "
                "connected=excluded.connected, received_at=excluded.received_at, "
                "credential_generation=excluded.credential_generation, source=excluded.source, "
                "last_connected_at=CASE WHEN excluded.connected=1 "
                "THEN excluded.last_connected_at "
                "ELSE mesh_device_presence.last_connected_at END",
                device, 1 if connected else 0, stamp, generation, source, last_connected,
            )
        else:
            await self._run(
                "INSERT INTO mesh_device_presence "
                "(device_id, connected, received_at, credential_generation, source, "
                " last_connected_at, account_refs_json) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(device_id) DO UPDATE SET "
                "connected=excluded.connected, received_at=excluded.received_at, "
                "credential_generation=excluded.credential_generation, source=excluded.source, "
                "last_connected_at=CASE WHEN excluded.connected=1 "
                "THEN excluded.last_connected_at "
                "ELSE mesh_device_presence.last_connected_at END, "
                "account_refs_json=excluded.account_refs_json",
                device, 1 if connected else 0, stamp, generation, source, last_connected,
                refs_json,
            )
        stored = await self.load(device)
        return (
            stored is not None
            and stored["connected"] is connected
            and stored["received_at"] == stamp
            and stored["credential_generation"] == generation
            and stored["source"] == source
            and stored["account_refs"] == (
                None if refs_json is None else json.loads(refs_json))
        )

    async def load(self, device_id: str) -> dict[str, Any] | None:
        device = _device(device_id)
        row = await self._first(
            "SELECT device_id, connected, received_at, credential_generation, source, "
            "last_connected_at, account_refs_json FROM mesh_device_presence "
            "WHERE device_id=?",
            device,
        )
        if not isinstance(row, dict):
            return None
        connected = row.get("connected")
        generation = row.get("credential_generation")
        source = row.get("source")
        received_at = row.get("received_at")
        last_connected_at = row.get("last_connected_at")
        if (
            row.get("device_id") != device
            or connected not in (0, 1)
            or type(connected) is not int
            or not isinstance(received_at, str)
            or not received_at
            or source not in ("broker", "mesh")
            or not (source == "mesh" and generation is None or
                    type(generation) is int and 1 <= generation <= _MAX_GENERATION)
            or not (last_connected_at is None or isinstance(last_connected_at, str))
        ):
            return None
        # #6695 PR-2: the owner accounts the row was recorded for. A missing or
        # NULL column is a pre-091 row and stays account-less; anything present
        # but malformed fails closed rather than decoding into a wrong owner.
        raw_refs = row.get("account_refs_json")
        account_refs = None
        if raw_refs is not None:
            if not isinstance(raw_refs, str) or not raw_refs:
                return None
            try:
                parsed_refs = json.loads(raw_refs)
            except ValueError:
                return None
            if (
                not isinstance(parsed_refs, list)
                or not 1 <= len(parsed_refs) <= _MAX_ACCOUNT_REFS
                or any(
                    not isinstance(item, str) or not item
                    or len(item) > _MAX_ACCOUNT_REF_CHARS
                    for item in parsed_refs
                )
            ):
                return None
            account_refs = parsed_refs
        return {
            "device_id": device,
            "connected": connected == 1,
            "received_at": received_at,
            "credential_generation": generation,
            "source": source,
            # When the node is connected right now, this is the same moment as
            # `received_at`; when it is not, it is the last connected beat.
            "last_connected_at": (
                received_at if connected == 1 else (last_connected_at or None)
            ),
            "account_refs": account_refs,
        }


__all__ = [
    "D1MeshDevicePresenceStore",
    "MeshDevicePresenceStore",
    "MeshDevicePresenceStoreError",
]
