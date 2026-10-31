#!/usr/bin/env python3
"""Offline queue-to-D1 dispatch export and verification. Never connects to D1."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sqlite3
import sys
import time

TABLE = "oracle_mesh_dispatch"
CLAIM_FIELDS = {"nonce_sha256", "claimed_until"}


def instant(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string")
    try:
        moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("timestamp requires a timezone")
    return moment.astimezone(dt.timezone.utc)


def read_db(path):
    connection = sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro",
                                 uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def columns(db):
    rows = db.execute("PRAGMA table_info(oracle_mesh_dispatch)").fetchall()
    if not rows:
        raise ValueError("dispatch table missing")
    return {row["name"]: row["type"].upper() for row in rows}


def schema(source, target):
    src, dst = columns(source), columns(target)
    missing = set(src) - set(dst)
    added = set(dst) - set(src)
    if (missing | added) - CLAIM_FIELDS:
        raise ValueError("unsupported schema difference")
    if "nonce_sha256" not in src or "claimed_until" not in src:
        raise ValueError("queue claim columns missing")
    if any(src[k] != dst[k] for k in set(src) & set(dst)):
        raise ValueError("column type mismatch")
    return list(dst), sorted(missing), sorted(added)


def snapshot(source, target, now, deadline):
    names, omitted, added = schema(source, target)
    counts = {"completed_or_other": 0, "result_in_progress": 0, "expired": 0, "active_claim": 0}
    active, output = [], []
    legacy_claim_count = 0
    for row in source.execute("SELECT * FROM oracle_mesh_dispatch ORDER BY dispatch_id"):
        if time.monotonic() >= deadline:
            raise TimeoutError("time limit")
        data = dict(row)
        if data["state"] != "pending":
            category = "result_in_progress" if data["state"] in {"received", "store_failed"} else "completed_or_other"
            counts[category] += 1
            continue
        if instant(data["expires_at"]) <= now:
            counts["expired"] += 1
            continue
        lease = data["claimed_until"]
        if data["nonce_sha256"] is not None and lease is not None and instant(lease) > now:
            counts["active_claim"] += 1
            active.append(data["dispatch_id"])
            continue
        if data["nonce_sha256"] is not None and lease is None:
            legacy_claim_count += 1
        output.append({name: data.get(name) for name in names})
    return {"columns": names, "rows": output, "excluded": counts,
            "active_claim_ids": active, "legacy_nonce_without_lease": legacy_claim_count,
            "claim_columns_omitted": omitted,
            "claim_columns_initialized": added}


def literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return "CAST(X'" + value.encode("utf-8").hex() + "' AS TEXT)"
    raise ValueError("unsupported SQLite value type")


def sql_text(payload):
    names = payload["columns"]
    quoted = ",".join('"' + n.replace('"', '""') + '"' for n in names)
    lines = ["BEGIN TRANSACTION;"]
    for row in payload["rows"]:
        lines.append("INSERT INTO oracle_mesh_dispatch (" + quoted + ") VALUES (" +
                     ",".join(literal(row[name]) for name in names) + ");")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def write_new(path, content):
    with open(path, "x", encoding="utf-8", newline="\n") as out:
        out.write(content)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "verify"))
    parser.add_argument("--queue", required=True, help="offline SQLite snapshot")
    parser.add_argument("--d1-schema", required=True, help="offline SQLite schema copy")
    parser.add_argument("--json", required=True)
    parser.add_argument("--sql", required=True)
    args = parser.parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    deadline = time.monotonic() + 60
    with read_db(args.queue) as source, read_db(args.d1_schema) as target:
        for db in (source, target):
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        payload = snapshot(source, target, now, deadline)
        if args.action == "export":
            if pathlib.Path(args.json).exists() or pathlib.Path(args.sql).exists():
                raise ValueError("output already exists")
            write_new(args.json, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            try:
                write_new(args.sql, sql_text(payload))
            except Exception:
                pathlib.Path(args.json).unlink(missing_ok=True)
                raise
        else:
            saved = json.loads(pathlib.Path(args.json).read_text(encoding="utf-8"))
            if saved != payload or pathlib.Path(args.sql).read_text(encoding="utf-8") != sql_text(saved):
                raise ValueError("source, export or eligibility changed; export again")
        print(json.dumps({"action": args.action, "eligible": len(payload["rows"]),
                          "excluded": payload["excluded"],
                          "active_claim_ids": payload["active_claim_ids"],
                          "legacy_nonce_without_lease": payload["legacy_nonce_without_lease"],
                          "claim_columns_omitted": payload["claim_columns_omitted"],
                          "claim_columns_initialized": payload["claim_columns_initialized"]}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, sqlite3.Error, TimeoutError):
        print("backfill failed: invalid input, schema, timestamp or changed snapshot",
              file=sys.stderr)
        sys.exit(1)
