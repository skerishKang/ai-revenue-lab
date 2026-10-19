#!/usr/bin/env python3
"""#5121 PADIEM Custom (BYOK) read-only pre-deployment readiness.

The caller collects two bounded evidence files with existing read-only tools:

* ``write-query`` / ``write-integrity-query`` emit a JSON body for the
  Cloudflare D1 query endpoint: metadata and aggregate counts only, never a
  credential value. For ``wrangler d1 execute --file`` extract the ``sql``
  field into a ``.sql`` file, or run one statement per ``--command`` so the
  per-statement ``results`` survive;
* ``wrangler secret list --format json`` output contains secret names, never
  their values.

``check`` then classifies READY / BLOCKED_BY_SECRET / BLOCKED_BY_MIGRATION /
FAILED. Each blocker is reported separately so only the exact failing stage is
named. This module never mutates D1, the Worker or DNS, and it never displays a
secret value, a sealed credential, a row value, a database id or an account id.

The dedicated encryption secret's *presence* is provable from the Worker
inventory. A present-but-wrong key is not provable from metadata; that path is
covered by ``tests/test_5121_byok_key_separation.py`` (wrong key and missing
key both fail closed without leaking the provider key).

Exit codes: ``0`` READY, ``2`` BLOCKED_BY_SECRET/BLOCKED_BY_MIGRATION, ``1``
FAILED or invalid evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

TABLE = "chat_custom_provider_credentials"
SECRET_NAME = "PADIEM_CHAT_CUSTOM_KEY_SECRET"
MIN_SECRET_CHARS = 32

EXPECTED_COLUMNS = (
    ("user_id", "TEXT", 1, 1),
    ("provider_id", "TEXT", 1, 2),
    ("key_last4", "TEXT", 1, 0),
    ("sealed_credential", "TEXT", 1, 0),
    ("created_at", "INTEGER", 1, 0),
    ("updated_at", "INTEGER", 1, 0),
)
DDL_REQUIRED = (
    "user_id text not null references users(id) on delete cascade",
    "provider_id text not null",
    "key_last4 text not null",
    "sealed_credential text not null",
    "created_at integer not null",
    "updated_at integer not null",
    "primary key (user_id, provider_id)",
)
EXPECTED_FK = {
    "table": "users",
    "from": "user_id",
    "to": "id",
    "on_delete": "CASCADE",
}

METADATA_SQL = (
    "SELECT name, type, sql FROM sqlite_master "
    f"WHERE name = '{TABLE}';"
    f"PRAGMA table_info({TABLE});"
    f"PRAGMA foreign_key_list({TABLE});"
)

# Aggregate only: no credential, envelope, owner or timestamp value is
# projected. Every counter must be zero for a READY result.
INTEGRITY_SQL = f"""SELECT
  COUNT(*) AS total_rows,
  COALESCE(SUM(CASE WHEN u.id IS NULL THEN 1 ELSE 0 END), 0) AS orphan_users,
  COALESCE(SUM(CASE WHEN length(trim(c.user_id)) = 0 OR length(trim(c.provider_id)) = 0 THEN 1 ELSE 0 END), 0) AS invalid_owner,
  COALESCE(SUM(CASE WHEN length(c.key_last4) <> 4 THEN 1 ELSE 0 END), 0) AS invalid_last4,
  COALESCE(SUM(CASE WHEN length(c.sealed_credential) < 40 OR c.sealed_credential GLOB '*[^A-Za-z0-9+/=]*' THEN 1 ELSE 0 END), 0) AS invalid_envelope,
  COALESCE(SUM(CASE WHEN typeof(c.created_at) <> 'integer' OR typeof(c.updated_at) <> 'integer' OR c.updated_at < c.created_at THEN 1 ELSE 0 END), 0) AS invalid_timestamps
FROM {TABLE} c LEFT JOIN users u ON u.id = c.user_id;"""

COUNTER_KEYS = (
    "total_rows",
    "orphan_users",
    "invalid_owner",
    "invalid_last4",
    "invalid_envelope",
    "invalid_timestamps",
)

FATAL_BLOCKERS = frozenset(
    {
        "EVIDENCE_INVALID",
        "MIGRATION_053_DRIFT",
        "D1_SCHEMA_EVIDENCE_INVALID",
        "D1_INTEGRITY_EVIDENCE_MISSING",
        "D1_INTEGRITY_EVIDENCE_INVALID",
        "D1_OWNERSHIP_VIOLATION",
    }
)
SECRET_BLOCKERS = frozenset({"SECRET_MISSING", "SECRET_WEAK"})


class InvalidEvidence(ValueError):
    """Evidence is not the bounded shape this read-only classifier accepts."""


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", value).strip().lower() if isinstance(value, str) else ""


def _statement_rows(payload: object, expected: int) -> list[list[dict[str, Any]]]:
    """Accept the D1 HTTP envelope or the Wrangler JSON array shape."""
    if isinstance(payload, dict):
        if payload.get("success") is not True:
            raise InvalidEvidence("D1 response failed")
        entries = payload.get("result")
    elif isinstance(payload, list):
        entries = payload
    else:
        raise InvalidEvidence("D1 response shape unknown")
    if not isinstance(entries, list) or len(entries) != expected:
        raise InvalidEvidence("unexpected statement count")
    rows: list[list[dict[str, Any]]] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("success") is not True:
            raise InvalidEvidence("statement failed")
        values = entry.get("results")
        if not isinstance(values, list) or not all(
            isinstance(value, dict) for value in values
        ):
            raise InvalidEvidence("statement rows invalid")
        rows.append(values)
    return rows


def classify_schema(payload: object) -> str:
    """Return EXACT, MISSING, DRIFT or INVALID_EVIDENCE for migration 053."""
    try:
        objects, columns, foreign_keys = _statement_rows(payload, 3)
    except InvalidEvidence:
        return "INVALID_EVIDENCE"
    if not objects:
        return "MISSING" if not columns and not foreign_keys else "DRIFT"
    if len(objects) != 1:
        return "DRIFT"
    table = objects[0]
    if table.get("name") != TABLE or table.get("type") != "table":
        return "DRIFT"
    if len(columns) != len(EXPECTED_COLUMNS):
        return "DRIFT"
    for cid, (row, expected) in enumerate(zip(columns, EXPECTED_COLUMNS)):
        name, kind, notnull, pk = expected
        if (
            row.get("cid") != cid
            or row.get("name") != name
            or str(row.get("type", "")).upper() != kind
            or type(row.get("notnull")) is not int
            or row["notnull"] != notnull
            or type(row.get("pk")) is not int
            or row["pk"] != pk
            or row.get("dflt_value") is not None
        ):
            return "DRIFT"
    ddl = _norm(table.get("sql"))
    if not ddl.startswith("create table") or not all(
        fragment in ddl for fragment in DDL_REQUIRED
    ):
        return "DRIFT"
    if len(foreign_keys) != 1:
        return "DRIFT"
    foreign_key = foreign_keys[0]
    for key, expected in EXPECTED_FK.items():
        actual = foreign_key.get(key)
        if key == "on_delete":
            if str(actual).upper() != expected:
                return "DRIFT"
        elif actual != expected:
            return "DRIFT"
    return "EXACT"


def classify_integrity(payload: object) -> tuple[str, dict[str, int] | None]:
    """Return OK, EMPTY, VIOLATION or INVALID_EVIDENCE for owner integrity."""
    try:
        rows, = _statement_rows(payload, 1)
    except InvalidEvidence:
        return "INVALID_EVIDENCE", None
    if len(rows) != 1:
        return "INVALID_EVIDENCE", None
    row = rows[0]
    counts: dict[str, int] = {}
    for key in COUNTER_KEYS:
        value = row.get(key)
        if type(value) is not int or value < 0:
            return "INVALID_EVIDENCE", None
        counts[key] = value
    if any(counts[key] for key in COUNTER_KEYS[1:]):
        return "VIOLATION", counts
    return ("EMPTY" if counts["total_rows"] == 0 else "OK"), counts


def secret_names(payload: object) -> tuple[str, ...]:
    """Extract names only from Wrangler secret-list or Worker binding JSON."""
    items: object = payload
    if isinstance(payload, dict):
        if payload.get("success") is True:
            result = payload.get("result")
            items = result.get("bindings") if isinstance(result, dict) else result
        elif "bindings" in payload:
            items = payload.get("bindings")
        elif "secrets" in payload:
            items = payload.get("secrets")
        elif "result" in payload:
            items = payload.get("result")
    if not isinstance(items, list):
        raise InvalidEvidence("secret inventory shape unknown")
    names: list[str] = []
    for item in items:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name")
        else:
            raise InvalidEvidence("secret inventory entry invalid")
        if not isinstance(name, str) or not name.strip():
            raise InvalidEvidence("secret name invalid")
        names.append(name.strip())
    return tuple(names)


def evaluate(
    *,
    secret_payload: object,
    schema_payload: object,
    integrity_payload: object | None = None,
    local_secret: str | None = None,
) -> dict[str, Any]:
    """Combine bounded evidence into one state and an explicit blocker list."""
    blockers: list[str] = []

    try:
        names = secret_names(secret_payload)
    except InvalidEvidence:
        names = None
        secret_ready = False
        strength = "NOT_INSPECTED"
        blockers.append("EVIDENCE_INVALID")
    else:
        secret_ready = SECRET_NAME in names
        if not secret_ready:
            blockers.append("SECRET_MISSING")
        if local_secret is None:
            strength = "NOT_INSPECTED"
        elif len(local_secret.strip()) >= MIN_SECRET_CHARS:
            strength = "OK"
        else:
            strength = "WEAK"
            blockers.append("SECRET_WEAK")

    migration = classify_schema(schema_payload)
    if migration == "MISSING":
        blockers.append("MIGRATION_053_MISSING")
    elif migration == "DRIFT":
        blockers.append("MIGRATION_053_DRIFT")
    elif migration == "INVALID_EVIDENCE":
        blockers.append("D1_SCHEMA_EVIDENCE_INVALID")

    ownership = "UNKNOWN"
    if migration == "EXACT":
        if integrity_payload is None:
            blockers.append("D1_INTEGRITY_EVIDENCE_MISSING")
        else:
            ownership, _ = classify_integrity(integrity_payload)
            if ownership == "VIOLATION":
                blockers.append("D1_OWNERSHIP_VIOLATION")
            elif ownership == "INVALID_EVIDENCE":
                ownership = "UNKNOWN"
                blockers.append("D1_INTEGRITY_EVIDENCE_INVALID")

    blocker_set = set(blockers)
    if blocker_set & FATAL_BLOCKERS:
        state = "FAILED"
    elif blocker_set & SECRET_BLOCKERS:
        state = "BLOCKED_BY_SECRET"
    elif "MIGRATION_053_MISSING" in blocker_set:
        state = "BLOCKED_BY_MIGRATION"
    else:
        state = "READY"

    return {
        "state": state,
        "secret_ready": secret_ready,
        "secret_strength": strength,
        "migration_053": migration,
        "d1_ownership": ownership,
        "blockers": blockers,
    }


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InvalidEvidence("input unreadable") from exc


def _write_query(path: Path, sql: str) -> None:
    if path.exists():
        raise FileExistsError(str(path))
    path.write_text(json.dumps({"sql": sql}), encoding="utf-8")


def _emit(result: dict[str, Any]) -> None:
    blockers = ",".join(result["blockers"]) if result["blockers"] else "NONE"
    print(f"BYOK_PREDEPLOY_STATE={result['state']}")
    print(f"SECRET_READY={'YES' if result['secret_ready'] else 'NO'}")
    print(f"SECRET_STRENGTH={result['secret_strength']}")
    print(f"MIGRATION_053={result['migration_053']}")
    print(f"D1_OWNERSHIP={result['d1_ownership']}")
    print(f"BYOK_BLOCKERS={blockers}")
    print("SECRET_VALUES_OUTPUT=0")
    print("ROW_VALUES_OUTPUT=0")
    print("PRODUCTION_MUTATION=0")


def _exit_for(state: str) -> int:
    if state == "READY":
        return 0
    if state.startswith("BLOCKED_"):
        return 2
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only PADIEM Custom (BYOK) pre-deployment readiness.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    for name in ("write-query", "write-integrity-query"):
        command = sub.add_parser(name)
        command.add_argument("file", type=Path)

    check_d1 = sub.add_parser("check-d1")
    check_d1.add_argument("file", type=Path)

    check_integrity = sub.add_parser("check-integrity")
    check_integrity.add_argument("file", type=Path)

    check = sub.add_parser("check")
    check.add_argument("--secrets", type=Path, required=True)
    check.add_argument("--d1", type=Path, required=True)
    check.add_argument("--integrity", type=Path)
    check.add_argument(
        "--inspect-local-key",
        action="store_true",
        help="Validate PADIEM_CHAT_CUSTOM_KEY_SECRET length without printing it.",
    )

    args = parser.parse_args(argv)
    try:
        if args.mode == "write-query":
            _write_query(args.file, METADATA_SQL)
            print("BYOK_PREDEPLOY_QUERY=METADATA_ONLY")
            print("ROW_VALUES_OUTPUT=0")
            return 0
        if args.mode == "write-integrity-query":
            _write_query(args.file, INTEGRITY_SQL)
            print("BYOK_PREDEPLOY_QUERY=AGGREGATE_ONLY")
            print("ROW_VALUES_OUTPUT=0")
            return 0
        if args.mode == "check-d1":
            disposition = classify_schema(_read_json(args.file))
            print(f"B62_BYOK_D1_SCHEMA={disposition}")
            return 0 if disposition == "EXACT" else (2 if disposition == "MISSING" else 1)
        if args.mode == "check-integrity":
            ownership, _ = classify_integrity(_read_json(args.file))
            print(f"D1_OWNERSHIP={ownership}")
            return 0 if ownership in ("OK", "EMPTY") else 1
        if args.mode == "check":
            local_secret = None
            if args.inspect_local_key:
                import os

                local_secret = os.environ.get(SECRET_NAME)
            result = evaluate(
                secret_payload=_read_json(args.secrets),
                schema_payload=_read_json(args.d1),
                integrity_payload=(
                    _read_json(args.integrity) if args.integrity else None
                ),
                local_secret=local_secret,
            )
            _emit(result)
            return _exit_for(result["state"])
    except (InvalidEvidence, OSError, FileExistsError):
        print("BYOK_PREDEPLOY_STATE=FAILED")
        print("BYOK_BLOCKERS=EVIDENCE_INVALID")
        print("SECRET_VALUES_OUTPUT=0")
        print("ROW_VALUES_OUTPUT=0")
        print("PRODUCTION_MUTATION=0")
        return 1
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
