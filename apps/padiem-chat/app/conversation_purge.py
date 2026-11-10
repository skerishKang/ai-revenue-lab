"""Retention purge for owner-deleted conversations (#7388).

Deleting a conversation no longer deletes rows: ``HistoryStore.delete_conversation``
sets ``conversations.deleted_at`` and every product read excludes the row, so the
conversation disappears from the browser immediately. 대표 결정(2026-11-10) keeps
the row, its messages and the R2 full originals for 30 days and then deletes all
three server-side, with no user-facing restore.

This module is that second pass. It runs after the expired-row pass on the same
daily host timer, sheds at most one bounded batch per run, and deletes one
conversation inside one transaction (messages first, then the marked row). The
messages delete is explicit because the host connection does not enforce
``ON DELETE CASCADE`` — the exact reason the pre-#7388 code left orphan messages
behind. Both statements carry the marker predicate, so a conversation an operator
restored between the read and the write keeps its messages.

The R2 originals are deleted only after the rows are committed: a doomed
conversation's full text is never removed while the row still exists, and a
failed object delete leaves an unreachable object rather than a half-deleted
conversation.

The result names only counts: never a conversation id, a message id or content.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

DEFAULT_RETENTION_DAYS = 30
DEFAULT_BATCH = 100

RETENTION_DAYS_ENV = "PADIEM_CHAT_CONVERSATION_RETENTION_DAYS"

#: Kept in step with ``app.history`` by
#: ``tests/test_7388_conversation_soft_delete.py``: the purge removes an R2
#: original only under the same "this row is a bounded preview" rule the store
#: used to write it.
MAX_HISTORY_MESSAGE_CHARS = 8000
HISTORY_PREVIEW_SUFFIX = "\n[저장 미리보기: 전체 내용 중 일부만 저장되었습니다.]"

_FULL_KEY_PREFIX = "claw-model-context/v1/"
_FULL_KEY_SUFFIX = ".utf8"

_ORPHAN_ERROR = "no such column: deleted_at"


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def retention_days_from_env(env: dict[str, str] | None = None) -> int:
    """The retention window, in days. Off means "use 30"; there is no zero."""

    source = os.environ if env is None else env
    return _positive_int(source.get(RETENTION_DAYS_ENV), DEFAULT_RETENTION_DAYS)


def _cutoff(now: datetime, retention_days: int) -> str:
    deadline = now.astimezone(timezone.utc) - timedelta(days=retention_days)
    return deadline.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _full_key(conversation_id: str, message_id: str) -> str:
    return f"{_FULL_KEY_PREFIX}{conversation_id}/{message_id}{_FULL_KEY_SUFFIX}"


def _is_bounded_preview(content: Any) -> bool:
    text = str(content or "")
    return (
        len(text) == MAX_HISTORY_MESSAGE_CHARS
        and text.endswith(HISTORY_PREVIEW_SUFFIX)
    )


def _rows(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    rows = result.get("results")
    return list(rows) if isinstance(rows, list) else []


def _changes(result: Any) -> int:
    if not isinstance(result, dict):
        return 0
    meta = result.get("meta") or {}
    changes = meta.get("changes")
    return int(changes) if changes is not None else 0


async def _has_marker_column(binding: Any) -> bool:
    """An environment behind migration 105 reports zero instead of failing.

    The purge is a timer, not a request: a schema one migration behind must not
    turn the daily pass into a red unit before the deploy that adds the column.
    """

    try:
        await binding.prepare(
            "SELECT 1 FROM conversations WHERE deleted_at IS NOT NULL LIMIT 1"
        ).all()
    except Exception as exc:
        if _ORPHAN_ERROR in str(exc) or "no such table: conversations" in str(exc):
            return False
        raise
    return True


async def purge_deleted_conversations(
    binding: Any,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    batch_size: int = DEFAULT_BATCH,
    dry_run: bool = False,
    now: datetime | None = None,
    delete_full_keys: Callable[[list[str]], Awaitable[None]] | None = None,
) -> dict[str, int]:
    """Shed one bounded batch of conversations whose retention window closed.

    Returns ``{"conversations": n, "messages": n, "r2_keys": n}`` — rows deleted,
    or rows a dry run would delete. A dry run counts against the same marker
    predicate, so it reports what a real pass would shed and never deletes.
    """

    if retention_days < 0:
        raise ValueError("retention_days must not be negative")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    result = {"conversations": 0, "messages": 0, "r2_keys": 0}
    cutoff = _cutoff(now or datetime.now(timezone.utc), retention_days)
    if not await _has_marker_column(binding):
        return result

    listed = await binding.prepare(
        "SELECT id FROM conversations "
        "WHERE deleted_at IS NOT NULL AND deleted_at < ? "
        "ORDER BY deleted_at ASC LIMIT ?"
    ).bind(cutoff, batch_size).run()
    conversation_ids = [str(row.get("id")) for row in _rows(listed)]
    if not conversation_ids:
        return result

    for conversation_id in conversation_ids:
        messages = await binding.prepare(
            "SELECT id, content FROM messages WHERE conversation_id=?"
        ).bind(conversation_id).all()
        message_rows = list(messages)
        full_keys = [
            _full_key(conversation_id, str(row.get("id")))
            for row in message_rows
            if _is_bounded_preview(row.get("content"))
        ]
        if dry_run:
            result["conversations"] += 1
            result["messages"] += len(message_rows)
            result["r2_keys"] += len(full_keys)
            continue

        # Both statements carry the marker predicate, and the batch is one
        # transaction: a restore that lands first keeps the messages, and a
        # failure rolls the whole conversation back.
        outcome = await binding.batch([
            binding.prepare(
                "DELETE FROM messages WHERE conversation_id=? AND EXISTS ("
                "SELECT 1 FROM conversations WHERE id=? "
                "AND deleted_at IS NOT NULL AND deleted_at < ?)"
            ).bind(conversation_id, conversation_id, cutoff),
            binding.prepare(
                "DELETE FROM conversations WHERE id=? "
                "AND deleted_at IS NOT NULL AND deleted_at < ?"
            ).bind(conversation_id, cutoff),
        ])
        conversation_changes = _changes(outcome[1] if len(outcome) > 1 else None)
        if conversation_changes < 1:
            # The row was restored (or shed by another pass) after the read.
            continue
        result["conversations"] += conversation_changes
        result["messages"] += _changes(outcome[0])
        if delete_full_keys is not None and full_keys:
            await delete_full_keys(full_keys)
            result["r2_keys"] += len(full_keys)

    return result
