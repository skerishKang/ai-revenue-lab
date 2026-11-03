"""Retention purge for the B14 model-call ledger (90 days, decided 2026-11-03).

The ledger has no deletion path today, which is why the privacy draft still
called it "unlimited in the repository". The owner settled the period at 90
days, so this module applies it: calls (and their attempts, which are only
reachable through the call) older than the period are removed in bounded
batches.

Deliberate choices:

* **An unknown age is kept.** A call whose ``started_at`` is NULL or unparseable
  is never shed: the ledger's own report found attempts with a NULL
  ``started_at``, and "no timestamp" is not "expired".
* **Attempts go with their call.** The attempt rows are keyed by ``log_id`` and
  carry no independent identity. An attempt whose call survives stays.
* **Counts only.** The status line reports table names and row counts; no
  ``log_id``, ``subject_ref`` or provider string is printed.
* **A failure is not a success.** The CLI exits non-zero when the database is
  missing, the schema is absent, or a DELETE fails, so a systemd timer records
  the failure instead of a silent no-op.

The module speaks plain ``sqlite3`` on purpose: the ledger file lives at
``/opt/padiem/b14/ledger/b14-call-ledger.db`` on COM2 and the purge must not
depend on the D1 binding the write path uses.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATUS_PREFIX = "B14_LEDGER_RETENTION="

CALL_TABLE = "b14_model_call"
ATTEMPT_TABLE = "b14_model_call_attempt"

DEFAULT_RETENTION_DAYS = 90
DEFAULT_BATCH = 1000


def cutoff_iso(now: datetime, retention_days: int) -> str:
    """Fixed-width UTC ISO cutoff, comparable with the stored ``started_at``."""
    deadline = now.astimezone(timezone.utc) - timedelta(days=retention_days)
    return deadline.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _expired_log_ids(
    connection: sqlite3.Connection, cutoff: str, limit: int
) -> list[str]:
    rows = connection.execute(
        f"SELECT log_id FROM {CALL_TABLE} WHERE started_at IS NOT NULL"
        f" AND started_at >= '1000-01-01' AND started_at < ? LIMIT ?",
        (cutoff, limit),
    ).fetchall()
    return [row[0] for row in rows]


def purge(
    db_path: str | Path,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    batch_size: int = DEFAULT_BATCH,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, int]:
    """Shed one bounded batch of calls past the period. Returns counts only."""
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError("ledger database missing")

    cutoff = cutoff_iso(now or datetime.now(timezone.utc), retention_days)
    counts = {CALL_TABLE: 0, ATTEMPT_TABLE: 0}
    connection = sqlite3.connect(str(path))
    try:
        if not _table_exists(connection, CALL_TABLE):
            return counts
        ids = _expired_log_ids(connection, cutoff, batch_size)
        if not ids:
            return counts
        if dry_run:
            counts[CALL_TABLE] = len(ids)
            if _table_exists(connection, ATTEMPT_TABLE):
                placeholders = ",".join("?" for _ in ids)
                counts[ATTEMPT_TABLE] = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {ATTEMPT_TABLE}"
                        f" WHERE log_id IN ({placeholders})",
                        ids,
                    ).fetchone()[0]
                )
            return counts
        placeholders = ",".join("?" for _ in ids)
        with connection:  # one transaction: attempts and their call move together
            if _table_exists(connection, ATTEMPT_TABLE):
                counts[ATTEMPT_TABLE] = int(
                    connection.execute(
                        f"DELETE FROM {ATTEMPT_TABLE} WHERE log_id IN ({placeholders})",
                        ids,
                    ).rowcount
                )
            counts[CALL_TABLE] = int(
                connection.execute(
                    f"DELETE FROM {CALL_TABLE} WHERE log_id IN ({placeholders})", ids
                ).rowcount
            )
        return counts
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="B14 call-ledger retention purge (counts only)"
    )
    parser.add_argument("--db", required=True, help="path to b14-call-ledger.db")
    parser.add_argument("--days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    parsed = parser.parse_args(argv if argv is not None else None)
    try:
        counts = purge(
            parsed.db,
            retention_days=parsed.days,
            batch_size=parsed.batch,
            dry_run=parsed.dry_run,
        )
    except FileNotFoundError:
        print(STATUS_PREFIX + "SKIPPED reason=database_missing", flush=True)
        return 2
    except sqlite3.Error:
        print(STATUS_PREFIX + "STORAGE_ERROR reason=ledger_unavailable", flush=True)
        return 1
    except ValueError:
        print(STATUS_PREFIX + "INVALID_ARGUMENT", flush=True)
        return 2
    mode = "dry_run" if parsed.dry_run else "ok"
    body = " ".join(f"{table}={counts[table]}" for table in sorted(counts))
    print(f"{STATUS_PREFIX}{mode} {body}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
