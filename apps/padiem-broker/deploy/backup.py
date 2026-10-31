#!/usr/bin/env python3
"""Daily broker SQLite snapshot — counts and hashes only, never row content.

VACUUM INTO gives an in-engine snapshot (no half-copied page while a session or
material write is in flight). The copy is reopened and verified before rotation
may replace an older backup. The broker pepper is NOT part of this backup and
must never be copied into the backup folder (design §4).
"""
import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path

TABLES = (
    "local_agent_broker_state",
    "local_agent_broker_used_command_id",
    "local_agent_command_material",
    "local_agent_http_session",
)


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts = {}
    for table in TABLES:
        try:
            counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.DatabaseError:
            counts[table] = -1
    return counts


def snapshot(db_path: Path, dest_dir: Path, keep: int) -> dict:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"broker-{stamp}.sqlite3"
    source = sqlite3.connect(str(db_path), timeout=20)
    try:
        source.execute("VACUUM INTO ?", (str(target),))
        source_counts = _counts(source)
    finally:
        source.close()

    copy = sqlite3.connect(str(target))
    try:
        integrity = copy.execute("PRAGMA integrity_check").fetchone()[0]
        copy_counts = _counts(copy)
        if integrity != "ok" or copy_counts != source_counts:
            raise ValueError("unverifiable snapshot")
        # Purge expired material from the disposable snapshot only; never mutate live DB.
        cutoff = dt.datetime.now(dt.timezone.utc).isoformat()
        invalid = copy.execute(
            "SELECT COUNT(*) FROM local_agent_command_material WHERE julianday(expires_at) IS NULL"
        ).fetchone()[0]
        if invalid:
            raise ValueError("invalid material expiry")
        copy.execute("DELETE FROM local_agent_command_material WHERE julianday(expires_at) <= julianday(?)", (cutoff,))
        copy.commit()
        copy_counts = _counts(copy)
    except (sqlite3.DatabaseError, ValueError):
        copy.close()
        target.unlink(missing_ok=True)
        raise SystemExit("BROKER_BACKUP=FAIL reason=unverifiable_snapshot")
    finally:
        copy.close()
    backups = sorted(dest_dir.glob("broker-*.sqlite3"))
    removed = 0
    for stale in (backups[:-keep] if keep > 0 else []):
        stale.unlink()
        removed += 1
    return {"file": target.name, "counts": copy_counts, "removed": removed}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--keep", type=int, default=7)
    args = parser.parse_args(argv)
    db_path = Path(args.db)
    if not db_path.is_file():
        print("BROKER_BACKUP=SKIPPED reason=database_absent", flush=True)
        return 0
    result = snapshot(db_path, Path(args.dest), args.keep)
    rows = " ".join(f"{name.replace('local_agent_', '')}={count}" for name, count in result["counts"].items())
    print(f"BROKER_BACKUP=PASS file={result['file']} removed={result['removed']} {rows}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
