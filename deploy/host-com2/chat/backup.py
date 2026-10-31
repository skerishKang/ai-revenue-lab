#!/usr/bin/env python3
"""Daily snapshot of the COM2 Chat SQLite database. Counts and hashes only.

VACUUM INTO takes an in-engine snapshot, so a claim/write in flight can never
yield a half-copied page. The copy is then opened and verified (integrity_check
plus row counts of the four user-facing tables) BEFORE rotation replaces an
older backup — an unreadable backup must never outlive a readable one.
"""
import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path

TABLES = ("users", "conversations", "messages", "projects")


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
    target = dest_dir / f"chat-{stamp}.sqlite3"
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
    finally:
        copy.close()
    if integrity != "ok" or copy_counts != source_counts:
        target.unlink(missing_ok=True)
        raise SystemExit("CHAT_COM2_BACKUP=FAIL reason=unverifiable_snapshot")

    backups = sorted(dest_dir.glob("chat-*.sqlite3"))
    removed = 0
    for stale in backups[:-keep] if keep > 0 else []:
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
        print("CHAT_COM2_BACKUP=SKIPPED reason=database_absent", flush=True)
        return 0
    result = snapshot(db_path, Path(args.dest), args.keep)
    rows = " ".join(f"{name}={count}" for name, count in result["counts"].items())
    print(f"CHAT_COM2_BACKUP=PASS file={result['file']} removed={result['removed']} {rows}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
