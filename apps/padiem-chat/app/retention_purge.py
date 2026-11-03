"""Deletion of records whose retention period the owner has already decided.

Stage 1 (``app.expired_purge``) sheds one-shot rows whose whole meaning dies at
their deadline. This module is the second stage: rows that keep their meaning
but whose *retention period* has run out. The periods are the ones the owner
settled on 2026-11-03 (``docs/legal/RETENTION_DECISION_20261103.md`` in the
legal drafts lane; summarized in ``docs/operations/RETENTION_ENFORCE_20261103.md``):

* ``account_deletion_audit`` — one year. The row is what refuses an old session
  after a withdrawal, so it must outlive the withdrawal by the decided year and
  no longer. It holds only a user-id hash and a timestamp.
* ``padiem_mcp_audit`` — 90 days (service logs / audit records).

Deliberately absent, and the reason each stays absent:

* identity, conversation, message, attachment, project-file, bookAI record and
  consent tables — the owner's periods for content are "until the user deletes
  it", which is a user action, not a cutoff this timer may apply;
* ``padiem_mcp_audit`` rows younger than the period, and every row without a
  parseable timestamp: an unknown age is not evidence of expiry;
* PC screen captures and PC work counters — they have no server-side table
  (captures live on the user's PC, the counter is a metric), so nothing here
  can date them. That is recorded in the enforcement doc, not guessed at.

The table list is explicit, never inferred from the schema. A run names only
tables and row counts: never a row's content and never a row identifier. Each
table sheds at most one batch per run so a backlog decays over several daily
ticks instead of holding the writer lock for a long single DELETE.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .local_cron import _entry_mode

STATUS_PREFIX = "CHAT_RETENTION_PURGE="

DEFAULT_BATCH = 1000

BATCH_ENV = "PADIEM_CHAT_RETENTION_PURGE_BATCH"
DISABLED_ENV = "PADIEM_CHAT_RETENTION_PURGE_DISABLED"


@dataclass(frozen=True)
class RetentionTarget:
    """One decided period, applied to one dated column.

    Every timestamp column here is a fixed-width UTC ISO string, so a
    lexicographic comparison against an equally formatted cutoff is
    order-correct. A row whose timestamp is NULL or unparsable sorts below the
    cutoff and would be deleted by a plain comparison, so the WHERE clause also
    requires a four-digit year: an unknown age is kept, never shed.
    """

    table: str
    column: str
    retention_days: int


RETENTION_TARGETS: tuple[RetentionTarget, ...] = (
    RetentionTarget("account_deletion_audit", "deleted_at", 365),
    RetentionTarget("padiem_mcp_audit", "created_at", 90),
)


def batch_size_from_env(env: dict[str, str] | None = None) -> int:
    source = os.environ if env is None else env
    try:
        value = int(str(source.get(BATCH_ENV) or "").strip())
    except ValueError:
        return DEFAULT_BATCH
    return value if value > 0 else DEFAULT_BATCH


def disabled_from_env(env: dict[str, str] | None = None) -> bool:
    """An operator can stop the retention pass without uninstalling the timer."""
    source = os.environ if env is None else env
    return str(source.get(DISABLED_ENV) or "").strip().lower() in {"1", "true", "yes"}


def _cutoff(now: datetime, retention_days: int) -> str:
    deadline = now.astimezone(timezone.utc) - timedelta(days=retention_days)
    return deadline.replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def _table_exists(binding: Any, table: str) -> bool:
    row = await binding.prepare(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?"
    ).bind(table).first()
    return row is not None


async def purge_expired_by_retention(
    binding: Any,
    *,
    batch_size: int = DEFAULT_BATCH,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, int]:
    """Shed one bounded batch per target table. Returns ``{table: rows}``.

    A table the database does not have (an environment behind on migrations)
    reports 0 rows and is skipped; a present table whose DELETE fails is a real
    storage fault and still raises, so the timer exits non-zero.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    moment = now or datetime.now(timezone.utc)
    result: dict[str, int] = {}
    for target in RETENTION_TARGETS:
        if not await _table_exists(binding, target.table):
            result[target.table] = 0
            continue
        cutoff = _cutoff(moment, target.retention_days)
        # `>= '1000-01-01'` keeps NULL and malformed timestamps: an unreadable
        # age is not proof that the period expired.
        where = (
            f"{target.column} IS NOT NULL AND {target.column} >= '1000-01-01'"
            f" AND {target.column} < ?"
        )
        if dry_run:
            row = await binding.prepare(
                f"SELECT COUNT(*) AS n FROM {target.table} WHERE {where}"
            ).bind(cutoff).first()
            result[target.table] = int(row["n"]) if row and row.get("n") is not None else 0
            continue
        outcome = await binding.prepare(
            f"DELETE FROM {target.table} WHERE rowid IN ("
            f"SELECT rowid FROM {target.table} WHERE {where} LIMIT ?)"
        ).bind(cutoff, batch_size).run()
        changes = (outcome.get("meta") or {}).get("changes") if isinstance(outcome, dict) else None
        result[target.table] = int(changes) if changes is not None else 0
    return result


async def _run_once_async(environ: dict[str, str], *, dry_run: bool) -> str:
    _entry_mode(environ)  # same entry contract as app.local_cron / expired_purge
    batch_size = batch_size_from_env(environ)

    from .d1_sqlite import SqliteD1, connect
    from .local_cpython import local_data_dir

    data_dir = local_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    connection = connect(str(data_dir / "chat.sqlite3"))
    try:
        counts = await purge_expired_by_retention(
            SqliteD1(connection), batch_size=batch_size, dry_run=dry_run
        )
    finally:
        connection.close()
    detail = json.dumps(counts, sort_keys=True, separators=(",", ":"))
    mode = "dry_run" if dry_run else "ok"
    return f"{STATUS_PREFIX}{mode} detail={detail}"


def run_once(environ: dict[str, str] | None = None, *, dry_run: bool = False) -> str:
    """Evaluate one retention pass and return the stable status line."""
    env = os.environ if environ is None else environ
    try:
        _entry_mode(env)
    except Exception:
        return STATUS_PREFIX + "SKIPPED reason=cpython_host_entry_required"
    if disabled_from_env(env):
        return STATUS_PREFIX + "SKIPPED reason=disabled_by_env"
    try:
        return asyncio.run(_run_once_async(env, dry_run=dry_run))
    except sqlite3.OperationalError:
        return STATUS_PREFIX + "STORAGE_ERROR reason=database_unavailable"
    except Exception:
        return STATUS_PREFIX + "ERROR reason=retention_purge_failed"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in args
    remaining = [item for item in args if item != "--dry-run"]
    if remaining not in ([], ["--once"]):
        print(STATUS_PREFIX + "INVALID_ARGUMENT", flush=True)
        return 2
    status = run_once(dry_run=dry_run)
    print(status, flush=True)
    # The timer reads the exit status, not the line: a failed pass must not
    # leave a oneshot Result=success behind.
    if status.startswith(STATUS_PREFIX + "ok ") or status.startswith(STATUS_PREFIX + "dry_run "):
        return 0
    if status.startswith(STATUS_PREFIX + "ERROR") or status.startswith(
        STATUS_PREFIX + "STORAGE_ERROR"
    ):
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
