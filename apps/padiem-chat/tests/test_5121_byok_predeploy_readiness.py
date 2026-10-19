"""#5121 PADIEM Custom (BYOK) pre-deployment readiness classifier.

All evidence below is produced from the checked-in migration 053 running on
SQLite and from the name-only Worker secret inventory shapes. The classifier
must distinguish READY / BLOCKED_BY_SECRET / BLOCKED_BY_MIGRATION / FAILED,
name only the failing stage, and never project a secret value, a sealed
credential or any other row value.

A present-but-wrong key is not provable from metadata; that fail-closed path is
already covered by ``test_5121_byok_key_separation.py`` and is not duplicated
here.
"""
from __future__ import annotations

import base64
import json
import re
import sqlite3
from pathlib import Path

import pytest

from scripts import byok_predeploy_readiness as readiness

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
MIGRATION_053 = MIGRATIONS / "053_chat_custom_provider_credentials.sql"
SECRET = readiness.SECRET_NAME
ENVELOPE = base64.b64encode(b"iv-12-bytes!" + b"ciphertext-16b..").decode("ascii")
TIMESTAMP = 1760000000


def connection(*, migration: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO users (id) VALUES (?)", [("owner",), ("other",)])
    if migration:
        conn.executescript(MIGRATION_053.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def add_credential(
    conn: sqlite3.Connection,
    *,
    user_id: str = "owner",
    provider_id: str = "opencode-go",
    key_last4: str = "abcd",
    envelope: str = ENVELOPE,
    created_at: int = TIMESTAMP,
    updated_at: int = TIMESTAMP,
) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO chat_custom_provider_credentials "
        "(user_id, provider_id, key_last4, sealed_credential, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, provider_id, key_last4, envelope, created_at, updated_at),
    )
    conn.commit()


def envelope(rows: list[list[dict]]) -> dict:
    """D1 HTTP query-endpoint shape: one entry per executed statement."""
    return {
        "success": True,
        "result": [{"success": True, "results": values} for values in rows],
    }


def schema_payload(conn: sqlite3.Connection) -> dict:
    table = readiness.TABLE
    return envelope(
        [
            [
                dict(row)
                for row in conn.execute(
                    "SELECT name, type, sql FROM sqlite_master WHERE name = ?",
                    (table,),
                )
            ],
            [dict(row) for row in conn.execute(f"PRAGMA table_info({table})")],
            [dict(row) for row in conn.execute(f"PRAGMA foreign_key_list({table})")],
        ]
    )


def integrity_payload(conn: sqlite3.Connection) -> dict:
    row = dict(conn.execute(readiness.INTEGRITY_SQL).fetchone())
    return envelope([[row]])


def wrangler_secrets(*names: str) -> list[dict]:
    return [{"name": name, "type": "secret_text"} for name in names]


def evaluate(
    conn: sqlite3.Connection,
    *,
    secret_names: tuple[str, ...] = (SECRET,),
    with_integrity: bool = True,
    local_secret: str | None = None,
) -> dict:
    return readiness.evaluate(
        secret_payload=wrangler_secrets(*secret_names),
        schema_payload=schema_payload(conn),
        integrity_payload=integrity_payload(conn) if with_integrity else None,
        local_secret=local_secret,
    )


# ---------------------------------------------------------------------------
# READY
# ---------------------------------------------------------------------------


def test_ready_when_secret_migration_and_ownership_are_exact():
    conn = connection()
    add_credential(conn)

    result = evaluate(conn, local_secret="k" * readiness.MIN_SECRET_CHARS)

    assert result == {
        "state": "READY",
        "secret_ready": True,
        "secret_strength": "OK",
        "migration_053": "EXACT",
        "d1_ownership": "OK",
        "blockers": [],
    }


def test_empty_credential_table_is_ready_without_inventing_rows():
    conn = connection()

    result = evaluate(conn)

    assert result["state"] == "READY"
    assert result["migration_053"] == "EXACT"
    assert result["d1_ownership"] == "EMPTY"


def test_secret_strength_is_not_assumed_when_not_inspected():
    conn = connection()
    add_credential(conn)

    result = evaluate(conn)

    assert result["secret_strength"] == "NOT_INSPECTED"
    assert result["state"] == "READY"


# ---------------------------------------------------------------------------
# BLOCKED_BY_MIGRATION / FAILED schema
# ---------------------------------------------------------------------------


def test_missing_migration_053_blocks_by_migration_only():
    conn = connection(migration=False)

    result = evaluate(conn, with_integrity=False)

    assert result["state"] == "BLOCKED_BY_MIGRATION"
    assert result["migration_053"] == "MISSING"
    assert result["d1_ownership"] == "UNKNOWN"
    assert result["blockers"] == ["MIGRATION_053_MISSING"]


def test_schema_drift_is_failed_not_ready():
    conn = connection(migration=False)
    conn.executescript(
        """CREATE TABLE chat_custom_provider_credentials (
             user_id TEXT NOT NULL,
             provider_id TEXT NOT NULL,
             key_last4 TEXT NOT NULL,
             sealed_credential TEXT NOT NULL,
             created_at TEXT NOT NULL,
             updated_at INTEGER NOT NULL,
             PRIMARY KEY (user_id, provider_id)
           );"""
    )
    conn.commit()

    result = evaluate(conn, with_integrity=False)

    assert result["state"] == "FAILED"
    assert result["migration_053"] == "DRIFT"
    assert result["blockers"] == ["MIGRATION_053_DRIFT"]


def test_missing_owner_foreign_key_is_schema_drift():
    conn = connection(migration=False)
    conn.executescript(
        """CREATE TABLE chat_custom_provider_credentials (
             user_id TEXT NOT NULL,
             provider_id TEXT NOT NULL,
             key_last4 TEXT NOT NULL,
             sealed_credential TEXT NOT NULL,
             created_at INTEGER NOT NULL,
             updated_at INTEGER NOT NULL,
             PRIMARY KEY (user_id, provider_id)
           );"""
    )
    conn.commit()

    assert readiness.classify_schema(schema_payload(conn)) == "DRIFT"


# ---------------------------------------------------------------------------
# FAILED ownership integrity
# ---------------------------------------------------------------------------


def test_orphan_owner_is_failed_and_reported_without_row_values():
    conn = connection()
    add_credential(conn, user_id="ghost")

    status, counts = readiness.classify_integrity(integrity_payload(conn))
    result = evaluate(conn)

    assert status == "VIOLATION"
    assert counts["orphan_users"] == 1
    assert result["state"] == "FAILED"
    assert result["d1_ownership"] == "VIOLATION"
    assert result["blockers"] == ["D1_OWNERSHIP_VIOLATION"]


def test_malformed_envelope_and_last4_are_failed():
    conn = connection()
    add_credential(conn, key_last4="bad", envelope="not base64/at all$$")

    status, counts = readiness.classify_integrity(integrity_payload(conn))

    assert status == "VIOLATION"
    assert counts["invalid_last4"] == 1
    assert counts["invalid_envelope"] == 1


def test_inverted_timestamp_is_failed():
    conn = connection()
    add_credential(conn, created_at=TIMESTAMP, updated_at=TIMESTAMP - 1)

    status, counts = readiness.classify_integrity(integrity_payload(conn))

    assert status == "VIOLATION"
    assert counts["invalid_timestamps"] == 1


def test_absent_integrity_evidence_is_never_assumed_clean():
    conn = connection()
    add_credential(conn)

    result = evaluate(conn, with_integrity=False)

    assert result["state"] == "FAILED"
    assert result["d1_ownership"] == "UNKNOWN"
    assert result["blockers"] == ["D1_INTEGRITY_EVIDENCE_MISSING"]


# ---------------------------------------------------------------------------
# BLOCKED_BY_SECRET
# ---------------------------------------------------------------------------


def test_missing_dedicated_secret_blocks_by_secret():
    conn = connection()
    add_credential(conn)

    result = evaluate(conn, secret_names=("OTHER_SECRET",))

    assert result["state"] == "BLOCKED_BY_SECRET"
    assert result["secret_ready"] is False
    assert result["blockers"] == ["SECRET_MISSING"]


def test_both_blockers_are_reported_with_secret_precedence():
    conn = connection(migration=False)

    result = evaluate(conn, secret_names=(), with_integrity=False)

    assert result["state"] == "BLOCKED_BY_SECRET"
    assert result["migration_053"] == "MISSING"
    assert result["blockers"] == ["SECRET_MISSING", "MIGRATION_053_MISSING"]


def test_weak_local_secret_blocks_without_echoing_it(monkeypatch, capsys, tmp_path):
    weak = "too-short-secret-value"
    monkeypatch.setenv(SECRET, weak)
    conn = connection()
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text(json.dumps(wrangler_secrets(SECRET)), encoding="utf-8")
    d1_file = tmp_path / "d1.json"
    d1_file.write_text(json.dumps(schema_payload(conn)), encoding="utf-8")
    integrity_file = tmp_path / "integrity.json"
    integrity_file.write_text(json.dumps(integrity_payload(conn)), encoding="utf-8")

    code = readiness.main(
        [
            "check",
            "--secrets", str(secrets_file),
            "--d1", str(d1_file),
            "--integrity", str(integrity_file),
            "--inspect-local-key",
        ]
    )
    output = capsys.readouterr()

    assert code == 2
    assert "BYOK_PREDEPLOY_STATE=BLOCKED_BY_SECRET" in output.out
    assert "SECRET_STRENGTH=WEAK" in output.out
    assert "BYOK_BLOCKERS=SECRET_WEAK" in output.out
    assert weak not in output.out + output.err


def test_secret_value_in_inventory_is_never_printed(capsys, tmp_path):
    planted = "sk-live-planted-value-must-not-print"
    conn = connection()
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text(
        json.dumps([{"name": SECRET, "type": "secret_text", "value": planted}]),
        encoding="utf-8",
    )
    d1_file = tmp_path / "d1.json"
    d1_file.write_text(json.dumps(schema_payload(conn)), encoding="utf-8")
    integrity_file = tmp_path / "integrity.json"
    integrity_file.write_text(json.dumps(integrity_payload(conn)), encoding="utf-8")

    code = readiness.main(
        [
            "check",
            "--secrets", str(secrets_file),
            "--d1", str(d1_file),
            "--integrity", str(integrity_file),
        ]
    )
    output = capsys.readouterr()

    assert code == 0
    assert planted not in output.out + output.err


# ---------------------------------------------------------------------------
# FAILED invalid evidence
# ---------------------------------------------------------------------------


def test_invalid_secret_evidence_fails_closed_without_echoing_payload(
    capsys, tmp_path,
):
    planted = "sk-live-bad-evidence"
    conn = connection()
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text(json.dumps({"unexpected": planted}), encoding="utf-8")
    d1_file = tmp_path / "d1.json"
    d1_file.write_text(json.dumps(schema_payload(conn)), encoding="utf-8")

    code = readiness.main(
        ["check", "--secrets", str(secrets_file), "--d1", str(d1_file)]
    )
    output = capsys.readouterr()

    assert code == 1
    assert "BYOK_PREDEPLOY_STATE=FAILED" in output.out
    assert "BYOK_BLOCKERS=EVIDENCE_INVALID" in output.out
    assert planted not in output.out + output.err


def test_failed_d1_statement_fails_closed_without_echoing_rows(capsys, tmp_path):
    planted = "raw-row-value"
    conn = connection()
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text(json.dumps(wrangler_secrets(SECRET)), encoding="utf-8")
    d1_file = tmp_path / "d1.json"
    d1_file.write_text(
        json.dumps(
            {"success": False, "error": planted, "result": [{"success": False}]}
        ),
        encoding="utf-8",
    )

    code = readiness.main(
        ["check", "--secrets", str(secrets_file), "--d1", str(d1_file)]
    )
    output = capsys.readouterr()

    assert code == 1
    assert "BYOK_PREDEPLOY_STATE=FAILED" in output.out
    assert "BYOK_BLOCKERS=D1_SCHEMA_EVIDENCE_INVALID" in output.out
    assert planted not in output.out + output.err


def test_unreadable_evidence_file_reports_bounded_failure(capsys, tmp_path):
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text("{not-json", encoding="utf-8")
    d1_file = tmp_path / "d1.json"
    d1_file.write_text("{}", encoding="utf-8")

    code = readiness.main(
        ["check", "--secrets", str(secrets_file), "--d1", str(d1_file)]
    )
    output = capsys.readouterr()

    assert code == 1
    assert "BYOK_BLOCKERS=EVIDENCE_INVALID" in output.out


def test_negative_counters_are_invalid_evidence():
    payload = envelope(
        [[{key: 0 for key in readiness.COUNTER_KEYS} | {"orphan_users": -1}]]
    )

    assert readiness.classify_integrity(payload)[0] == "INVALID_EVIDENCE"


# ---------------------------------------------------------------------------
# Evidence collectors are read-only and value-free
# ---------------------------------------------------------------------------


def test_query_sql_is_read_only():
    statements = [
        value.strip()
        for value in readiness.METADATA_SQL.split(";")
        if value.strip()
    ] + [readiness.INTEGRITY_SQL.strip()]

    for statement in statements:
        lowered = statement.lower()
        assert lowered.startswith(("select", "pragma"))
        for forbidden in (
            "insert ", "update ", "delete ", "drop ", "alter ",
            "create ", "attach ", "detach ", "replace ", "vacuum",
        ):
            assert forbidden not in lowered


def test_integrity_sql_projects_only_aggregate_counters():
    aliases = [
        alias.lower()
        for alias in re.findall(
            r"\bAS\s+([a-z0-9_]+)", readiness.INTEGRITY_SQL, flags=re.IGNORECASE
        )
    ]

    assert aliases == list(readiness.COUNTER_KEYS)
    assert "select *" not in readiness.INTEGRITY_SQL.lower()


def test_integrity_evidence_returns_no_row_values():
    conn = connection()
    add_credential(conn)

    row = dict(conn.execute(readiness.INTEGRITY_SQL).fetchone())

    assert tuple(row) == readiness.COUNTER_KEYS


def test_write_query_emits_a_d1_http_body_and_refuses_overwrite(tmp_path, capsys):
    target = tmp_path / "query.json"

    assert readiness.main(["write-query", str(target)]) == 0
    body = json.loads(target.read_text(encoding="utf-8"))
    assert body == {"sql": readiness.METADATA_SQL}
    assert "ROW_VALUES_OUTPUT=0" in capsys.readouterr().out

    assert readiness.main(["write-query", str(target)]) == 1


def test_write_integrity_query_emits_aggregate_only_sql(tmp_path, capsys):
    target = tmp_path / "integrity.json"

    assert readiness.main(["write-integrity-query", str(target)]) == 0
    body = json.loads(target.read_text(encoding="utf-8"))
    assert body == {"sql": readiness.INTEGRITY_SQL}
    assert "AGGREGATE_ONLY" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Secret inventory and CLI exit codes
# ---------------------------------------------------------------------------


def test_secret_parser_accepts_wrangler_worker_and_plain_shapes():
    assert readiness.secret_names(wrangler_secrets(SECRET)) == (SECRET,)
    assert readiness.secret_names([SECRET, "OTHER"]) == (SECRET, "OTHER")
    assert readiness.secret_names(
        {"success": True, "result": {"bindings": [{"name": SECRET}]}}
    ) == (SECRET,)
    assert readiness.secret_names({"bindings": [{"name": SECRET}]}) == (SECRET,)
    assert readiness.secret_names({"secrets": [SECRET]}) == (SECRET,)


@pytest.mark.parametrize(
    "payload",
    [
        {"success": True, "result": "not-a-list"},
        {"success": True, "result": [{"type": "secret_text"}]},
        [{"name": "   "}],
        [1],
        "string",
    ],
)
def test_secret_parser_refuses_unknown_shapes(payload):
    with pytest.raises(readiness.InvalidEvidence):
        readiness.secret_names(payload)


def test_check_d1_exit_codes(capsys, tmp_path):
    exact = tmp_path / "exact.json"
    exact.write_text(json.dumps(schema_payload(connection())), encoding="utf-8")
    missing = tmp_path / "missing.json"
    missing.write_text(
        json.dumps(schema_payload(connection(migration=False))), encoding="utf-8"
    )

    assert readiness.main(["check-d1", str(exact)]) == 0
    assert "B62_BYOK_D1_SCHEMA=EXACT" in capsys.readouterr().out
    assert readiness.main(["check-d1", str(missing)]) == 2
    assert "B62_BYOK_D1_SCHEMA=MISSING" in capsys.readouterr().out


def test_check_integrity_exit_codes(capsys, tmp_path):
    clean = connection()
    add_credential(clean)
    dirty = connection()
    add_credential(dirty, user_id="ghost")
    clean_file = tmp_path / "clean.json"
    clean_file.write_text(json.dumps(integrity_payload(clean)), encoding="utf-8")
    dirty_file = tmp_path / "dirty.json"
    dirty_file.write_text(json.dumps(integrity_payload(dirty)), encoding="utf-8")

    assert readiness.main(["check-integrity", str(clean_file)]) == 0
    assert readiness.main(["check-integrity", str(dirty_file)]) == 1
    out = capsys.readouterr().out
    assert "D1_OWNERSHIP=OK" in out
    assert "D1_OWNERSHIP=VIOLATION" in out


def test_check_ready_exit_code_zero(capsys, tmp_path):
    conn = connection()
    add_credential(conn)
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text(json.dumps(wrangler_secrets(SECRET)), encoding="utf-8")
    d1_file = tmp_path / "d1.json"
    d1_file.write_text(json.dumps(schema_payload(conn)), encoding="utf-8")
    integrity_file = tmp_path / "integrity.json"
    integrity_file.write_text(json.dumps(integrity_payload(conn)), encoding="utf-8")

    code = readiness.main(
        [
            "check",
            "--secrets", str(secrets_file),
            "--d1", str(d1_file),
            "--integrity", str(integrity_file),
        ]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "BYOK_PREDEPLOY_STATE=READY" in out
    assert "SECRET_VALUES_OUTPUT=0" in out
    assert "ROW_VALUES_OUTPUT=0" in out
    assert "PRODUCTION_MUTATION=0" in out


def test_check_blocked_by_migration_exit_code_two(capsys, tmp_path):
    conn = connection(migration=False)
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text(json.dumps(wrangler_secrets(SECRET)), encoding="utf-8")
    d1_file = tmp_path / "d1.json"
    d1_file.write_text(json.dumps(schema_payload(conn)), encoding="utf-8")

    code = readiness.main(
        ["check", "--secrets", str(secrets_file), "--d1", str(d1_file)]
    )
    out = capsys.readouterr().out

    assert code == 2
    assert "BYOK_PREDEPLOY_STATE=BLOCKED_BY_MIGRATION" in out
    assert "MIGRATION_053=MISSING" in out
