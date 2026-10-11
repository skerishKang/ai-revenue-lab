"""Durable explicitly user-approved Claw memory persistence (#2331).

Authority boundary:
- P01/Core owns generic Memory trust/write-policy semantics (not reimplemented here).
- B54 owns proposal meaning and user-approval UX semantics.
- B62 persists/presents only explicitly user-approved, bounded public-safe records.
- Control Plane remains canonical identity/tenant authority.

This module stores only bounded public-safe proposal fields that the signed-in
owner explicitly approves. Pending/unapproved proposals are never written here.
Rejection never creates a row. Storage reuses the existing PADIEM_CHAT_DB D1
binding; no new database authority is introduced and no DDL runs at request
time (schema lives in migrations/011_claw_approved_memory.sql only).

Persisted columns are limited to: id, user_id, workspace_id, memory_type,
name, note, source_channel, status, created_at, updated_at. Request text,
provider/internal material, session material, OAuth material, object keys and
artifact bytes are never persisted or projected.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

MAX_APPROVED_MEMORIES = 30
MAX_MEMORY_TYPE_CHARS = 64
MAX_MEMORY_NAME_CHARS = 120
MAX_MEMORY_NOTE_CHARS = 500

_ALLOWED_CHANNELS = frozenset({"kakao", "sms", "email", "telegram", "discord", "other"})
_MEMORY_TYPE_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_MEMORY_ID_RE = re.compile(r"^mem_[0-9a-f]{32}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Caller-supplied ownership fields are forbidden in the approve payload. The
# server always binds ownership from the signed-in session/tenant authority.
_FORBIDDEN_OWNER_KEYS = frozenset({
    "user_id", "owner", "owner_id", "tenant_id", "tenant", "workspace_id", "workspace",
})


class ApprovedMemoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CanonicalApprovedProposal:
    memory_type: str
    name: str
    note: str | None
    source_channel: str | None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _memory_id() -> str:
    return "mem_" + uuid.uuid4().hex


def _clean_bounded(value: object, *, label: str, limit: int, allow_empty: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApprovedMemoryError(f"{label} 형식이 올바르지 않습니다.")
    if _CONTROL_RE.search(value):
        raise ApprovedMemoryError(f"{label} 형식이 올바르지 않습니다.")
    text = " ".join(value.split())
    if not text:
        if allow_empty:
            return None
        raise ApprovedMemoryError(f"{label} 형식이 올바르지 않습니다.")
    if len(text) > limit:
        raise ApprovedMemoryError(f"{label} 형식이 올바르지 않습니다.")
    return text


def canonicalize_proposal(proposal: object) -> CanonicalApprovedProposal:
    """Validate a public-safe proposal echoed from preview/execute and canonicalize it.

    Only the bounded public-safe fields (type/name/note/source_channel) are
    accepted. Any ownership binding smuggled in the payload is rejected. Extra
    unknown keys are ignored and never persisted.
    """
    if not isinstance(proposal, dict):
        raise ApprovedMemoryError("proposal 형식이 올바르지 않습니다.")
    for key in _FORBIDDEN_OWNER_KEYS:
        if key in proposal:
            raise ApprovedMemoryError("proposal 형식이 올바르지 않습니다.")
    raw_type = proposal.get("type")
    if not isinstance(raw_type, str) or not _MEMORY_TYPE_RE.fullmatch(raw_type.strip()):
        raise ApprovedMemoryError("proposal 형식이 올바르지 않습니다.")
    memory_type = raw_type.strip()[:MAX_MEMORY_TYPE_CHARS]
    name = _clean_bounded(proposal.get("name"), label="proposal.name", limit=MAX_MEMORY_NAME_CHARS)
    if name is None:
        raise ApprovedMemoryError("proposal 형식이 올바르지 않습니다.")
    note = _clean_bounded(proposal.get("note"), label="proposal.note", limit=MAX_MEMORY_NOTE_CHARS, allow_empty=True)
    channel: str | None = None
    if proposal.get("source_channel") is not None:
        raw_channel = proposal.get("source_channel")
        if not isinstance(raw_channel, str):
            raise ApprovedMemoryError("proposal 형식이 올바르지 않습니다.")
        normalized = raw_channel.strip().lower()
        if normalized not in _ALLOWED_CHANNELS:
            raise ApprovedMemoryError("proposal 형식이 올바르지 않습니다.")
        channel = normalized
    return CanonicalApprovedProposal(memory_type=memory_type, name=name, note=note, source_channel=channel)


def validate_memory_id(value: object) -> str:
    if not isinstance(value, str) or not _MEMORY_ID_RE.fullmatch(value.strip()):
        raise ApprovedMemoryError("memory_id 형식이 올바르지 않습니다.")
    return value.strip()


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    to_py = getattr(row, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _rows_from_result(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    rows = getattr(result, "results", None)
    if rows is None and isinstance(result, dict):
        rows = result.get("results")
    if rows is None:
        return []
    out = []
    for row in rows:
        item = _row_to_dict(row)
        if item is not None:
            out.append(item)
    return out


def _public_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_id": str(row.get("id", "")),
        "workspace_id": str(row.get("workspace_id", "")),
        "memory_type": str(row.get("memory_type", "")),
        "name": str(row.get("name", "")),
        "note": row.get("note") if row.get("note") is not None else None,
        "source_channel": row.get("source_channel") if row.get("source_channel") is not None else None,
        "status": str(row.get("status", "approved")),
        "created_at": str(row.get("created_at", "")),
        "updated_at": str(row.get("updated_at", "")),
    }


class ApprovedMemoryStore(Protocol):
    async def approve_memory(self, *, user_id: str, workspace_id: str, proposal: CanonicalApprovedProposal) -> dict[str, Any]: ...
    async def list_approved_memories(self, *, user_id: str, workspace_id: str, limit: int = MAX_APPROVED_MEMORIES) -> list[dict[str, Any]]: ...
    async def get_approved_memory(self, *, user_id: str, workspace_id: str, memory_id: str) -> dict[str, Any] | None: ...


class D1ApprovedMemoryStore:
    """Cloudflare D1 adapter. All dynamic values use prepared statement binds."""

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

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _rows_from_result(await statement.run())

    async def approve_memory(self, *, user_id: str, workspace_id: str, proposal: CanonicalApprovedProposal) -> dict[str, Any]:
        if not user_id or not workspace_id:
            raise ApprovedMemoryError("ownership is required")
        if not isinstance(proposal, CanonicalApprovedProposal):
            raise ApprovedMemoryError("proposal 형식이 올바르지 않습니다.")
        now = _now_iso()
        memory_id = _memory_id()
        await self._run(
            "INSERT INTO claw_approved_memory (id, user_id, workspace_id, memory_type, name, note, source_channel, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)",
            memory_id, user_id, workspace_id, proposal.memory_type, proposal.name,
            proposal.note, proposal.source_channel, now, now,
        )
        row = await self._first(
            "SELECT id, workspace_id, memory_type, name, note, source_channel, status, created_at, updated_at "
            "FROM claw_approved_memory WHERE id=? AND user_id=? AND workspace_id=?",
            memory_id, user_id, workspace_id,
        )
        if not row:
            raise ApprovedMemoryError("approved memory write failed")
        return _public_projection(row)

    async def list_approved_memories(self, *, user_id: str, workspace_id: str, limit: int = MAX_APPROVED_MEMORIES) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), MAX_APPROVED_MEMORIES))
        rows = await self._all(
            "SELECT id, workspace_id, memory_type, name, note, source_channel, status, created_at, updated_at "
            "FROM claw_approved_memory WHERE user_id=? AND workspace_id=? ORDER BY created_at DESC LIMIT ?",
            user_id, workspace_id, bounded,
        )
        return [_public_projection(row) for row in rows]

    async def get_approved_memory(self, *, user_id: str, workspace_id: str, memory_id: str) -> dict[str, Any] | None:
        validated = validate_memory_id(memory_id)
        row = await self._first(
            "SELECT id, workspace_id, memory_type, name, note, source_channel, status, created_at, updated_at "
            "FROM claw_approved_memory WHERE id=? AND user_id=? AND workspace_id=?",
            validated, user_id, workspace_id,
        )
        return _public_projection(row) if row else None
