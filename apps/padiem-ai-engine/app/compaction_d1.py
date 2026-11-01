"""Owner-scoped D1 archive for compacted PC conversation context.

Uses the Engine's existing `ENGINE_CONTINUATION` D1 surface (the same SQLite
facade on the COM2 host). A row is immutable: the same source id with different
content is refused, so a summary can never point at altered evidence. No
content is logged or returned to a caller outside the authenticated owner.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

TABLE = "padiem_engine_context_archive_v1"

_INSERT = (
    f"INSERT OR IGNORE INTO {TABLE} "
    "(owner_scope, source_id, message_json, created_at) VALUES (?, ?, ?, ?)"
)
_SELECT_ONE = (
    f"SELECT message_json FROM {TABLE} WHERE owner_scope = ? AND source_id = ?"
)
_SELECT_MANY = (
    f"SELECT source_id, message_json FROM {TABLE} "
    "WHERE owner_scope = ? AND source_id = ?"
)


class D1ContextArchive:
    """The CompactionStore surface over D1; every method is async."""

    def __init__(self, binding: Any, *, owner: str) -> None:
        if binding is None:
            raise ValueError("a D1 binding is required")
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("owner must be a non-empty string")
        self._binding = binding
        self._owner = owner

    def _matches(self, owner: str) -> bool:
        return owner == self._owner

    async def probe(self) -> None:
        """Fail before a summary is written when the archive table is absent."""
        await self._binding.prepare(f"SELECT 1 FROM {TABLE} LIMIT 1").first()

    async def save(self, messages: Sequence[Mapping[str, Any]], *, owner: str) -> None:
        if not self._matches(owner):
            raise PermissionError("source unavailable for owner")
        created = datetime.now(timezone.utc).isoformat()
        for message in messages:
            source_id = message.get("id")
            if not isinstance(source_id, str) or not source_id:
                raise ValueError("each archived message needs a non-empty id")
            encoded = json.dumps(dict(message), ensure_ascii=False, sort_keys=True)
            await self._binding.prepare(_INSERT).bind(
                owner, source_id, encoded, created,
            ).run()
            row = await self._binding.prepare(_SELECT_ONE).bind(owner, source_id).first()
            if row is None or row.get("message_json") != encoded:
                raise ValueError("source id already has different content")

    async def recall(self, source_ids: Sequence[str], *, owner: str) -> list[dict[str, Any]]:
        if not self._matches(owner):
            raise PermissionError("source unavailable for owner")
        if isinstance(source_ids, (str, bytes)) or not all(
            isinstance(source_id, str) and source_id for source_id in source_ids
        ):
            raise ValueError("source_ids must be a sequence of non-empty ids")
        result: list[dict[str, Any]] = []
        for source_id in source_ids:
            row = await self._binding.prepare(_SELECT_MANY).bind(owner, source_id).first()
            if row is None:
                # Do not reveal whether another owner has the requested ID.
                raise PermissionError("source unavailable for owner")
            result.append(json.loads(row["message_json"]))
        return result


__all__ = ["D1ContextArchive"]
