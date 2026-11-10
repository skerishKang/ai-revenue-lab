"""Operator-only restore of an owner-deleted conversation (#7388).

Deleting a conversation marks it (``conversations.deleted_at``) and every
product read hides it immediately. 대표 결정(2026-11-10): there is no user-facing
restore — the operator restores inside the 30-day window from the server, and
``app.conversation_purge`` deletes the row, its messages and the R2 originals
once the window closes.

This module is the whole restore authority, reached on the host through
``ops/restore_conversation.sh``. It returns one state word and never reads out
message content or a user identifier.
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from .conversation_purge import DEFAULT_RETENTION_DAYS, retention_days_from_env

DEFAULT_DB = "/opt/padiem/chat-com2/data/chat.sqlite3"

RESTORED = "ok"
NOT_FOUND = "not_found"
NOT_DELETED = "not_deleted"
WINDOW_CLOSED = "window_closed"

EXIT_CODES = {RESTORED: 0, NOT_FOUND: 3, NOT_DELETED: 4, WINDOW_CLOSED: 5}

_CONVERSATION_ID = re.compile(r"\Achat_[0-9a-f]{32}\Z")


def _cutoff(now: datetime, retention_days: int) -> str:
    deadline = now.astimezone(timezone.utc) - timedelta(days=retention_days)
    return deadline.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def restore_conversation(
    connection: sqlite3.Connection,
    conversation_id: str,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    now: datetime | None = None,
) -> str:
    """Clear the delete marker inside the window; never touch a live row.

    The window is enforced here and not only in the purge pass: a row whose
    marker is already older than the retention period is refused, because the
    daily pass is about to remove it and a restore would race that removal.
    """

    if not isinstance(conversation_id, str) or not _CONVERSATION_ID.match(conversation_id):
        raise ValueError("conversation_id must be a canonical conversation id")
    if retention_days < 0:
        raise ValueError("retention_days must not be negative")

    row = connection.execute(
        "SELECT deleted_at FROM conversations WHERE id=?", (conversation_id,)
    ).fetchone()
    if row is None:
        return NOT_FOUND
    deleted_at = row[0]
    if deleted_at is None:
        return NOT_DELETED
    cutoff = _cutoff(now or datetime.now(timezone.utc), retention_days)
    if str(deleted_at) < cutoff:
        return WINDOW_CLOSED
    connection.execute(
        "UPDATE conversations SET deleted_at=NULL WHERE id=? AND deleted_at=?",
        (conversation_id, deleted_at),
    )
    connection.commit()
    return RESTORED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="restore_conversation",
        description="Restore one owner-deleted conversation inside the retention window.",
    )
    parser.add_argument("conversation_id")
    parser.add_argument(
        "--db",
        default=os.environ.get("PADIEM_CHAT_DB", DEFAULT_DB),
        help="Chat SQLite file (default: the COM2 host database).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=retention_days_from_env(),
        help="Retention window in days (default: 30).",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    connection = sqlite3.connect(args.db)
    try:
        state = restore_conversation(
            connection, args.conversation_id, retention_days=args.days,
        )
    finally:
        connection.close()
    print(f"RESTORE={state.upper()} conversation={args.conversation_id}", flush=True)
    return EXIT_CODES[state]


if __name__ == "__main__":
    raise SystemExit(main())
