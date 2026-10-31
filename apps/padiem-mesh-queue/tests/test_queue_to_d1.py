"""Offline rollback export against the real dispatch migrations."""
from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
QUEUE = ROOT / "apps/padiem-mesh-queue"
TOOL = QUEUE / "tools/queue_to_d1.py"
MIGRATIONS = ROOT / "apps/padiem-chat/migrations"
NAMES = (
    "047_oracle_mesh_dispatch.sql", "048_oracle_mesh_command.sql",
    "049_oracle_mesh_command_result_meta.sql",
    "063_oracle_mesh_dispatch_tool_call_scope.sql",
    "074_oracle_mesh_dispatch_claim_lease.sql",
)


def make_db(path, *, lease=True):
    db = sqlite3.connect(path)
    for name in NAMES if lease else NAMES[:-1]:
        db.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    db.close()


def add(db, key, owner, state="pending", expires="2099-01-01T00:00:00Z",
        nonce=None, claimed_until=None):
    fields = {
        "dispatch_id": key, "user_id": owner, "run_id": key,
        "command_id": key, "tool_request_ref": key, "request_id": key,
        "revision_ref": key, "request_fingerprint": key, "account_ref": owner,
        "workspace_ref": owner, "device_id": "dev@mesh", "node_ref": "node",
        "root_ref": "root", "path_relative": "test.txt", "file_path": "test.txt",
        "state": state, "expires_at": expires, "created_at": "2026-01-01T00:00:00Z",
        "nonce_sha256": nonce, "claimed_until": claimed_until,
    }
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO oracle_mesh_dispatch (" + ",".join(fields) + ") VALUES (" +
            ",".join("?" for _ in fields) + ")", tuple(fields.values())
        )


def run(action, src, dst, out, sql):
    return subprocess.run(
        [sys.executable, str(TOOL), action, "--queue", str(src), "--d1-schema", str(dst),
         "--json", str(out), "--sql", str(sql)],
        capture_output=True, text=True, timeout=10,
    )


def test_export_verify_and_sql_roundtrip_real_migrations(tmp_path):
    src, dst, out, sql = (tmp_path / n for n in ("queue.db", "d1.db", "out.json", "out.sql"))
    make_db(src)
    make_db(dst)
    add(src, "a", "owner1")
    add(src, "b", "owner2", nonce="synthetic", claimed_until="2026-01-01T00:00:00Z")
    add(src, "c", "owner1", nonce="synthetic", claimed_until="2099-01-01T00:00:00Z")
    add(src, "d", "owner1", expires="2020-01-01T00:00:00Z")
    add(src, "e", "owner1", state="done")
    add(src, "g", "owner1", state="store_failed")
    exported = run("export", src, dst, out, sql)
    assert exported.returncode == 0, exported.stderr
    report = json.loads(exported.stdout)
    assert report["eligible"] == 2
    assert report["excluded"] == {"completed_or_other": 1, "result_in_progress": 1, "expired": 1, "active_claim": 1}
    assert report["active_claim_ids"] == ["c"]
    assert run("verify", src, dst, out, sql).returncode == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    with sqlite3.connect(dst) as connection:
        connection.executescript(sql.read_text(encoding="utf-8"))
        connection.row_factory = sqlite3.Row
        records = [dict(row) for row in connection.execute(
            "SELECT * FROM oracle_mesh_dispatch ORDER BY dispatch_id")]
    assert records == payload["rows"]
    assert [record["user_id"] for record in records] == ["owner1", "owner2"]
    assert records[1]["nonce_sha256"] == "synthetic"
    assert records[1]["claimed_until"] == "2026-01-01T00:00:00Z"
    # Refuse if the source changes between export and verification.
    add(src, "f", "owner3")
    assert run("verify", src, dst, out, sql).returncode != 0


def test_legacy_target_claim_column_is_reported(tmp_path):
    src, dst, out, sql = (tmp_path / n for n in ("q.db", "d.db", "o.json", "o.sql"))
    make_db(src)
    make_db(dst, lease=False)
    add(src, "a", "owner", nonce="synthetic", claimed_until="2026-01-01T00:00:00Z")
    result = run("export", src, dst, out, sql)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["claim_columns_omitted"] == ["claimed_until"]
    assert run("verify", src, dst, out, sql).returncode == 0


def test_active_claim_is_never_exported_and_tampering_is_detected(tmp_path):
    src, dst, out, sql = (tmp_path / n for n in ("q.db", "d.db", "o.json", "o.sql"))
    make_db(src)
    make_db(dst)
    add(src, "active", "owner", nonce="x", claimed_until="2099-01-01T00:00:00Z")
    assert run("export", src, dst, out, sql).returncode == 0
    assert json.loads(out.read_text(encoding="utf-8"))["rows"] == []
    sql.write_text("SELECT 1;\n", encoding="utf-8")
    assert run("verify", src, dst, out, sql).returncode != 0

def test_legacy_claim_and_existing_d1_row_are_not_silently_overwritten(tmp_path):
    src, dst, out, sql = (tmp_path / n for n in ("q.db", "d.db", "o.json", "o.sql"))
    make_db(src)
    make_db(dst)
    add(src, "a", "owner", nonce="synthetic", claimed_until=None)
    result = run("export", src, dst, out, sql)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["legacy_nonce_without_lease"] == 1
    assert run("verify", src, dst, out, sql).returncode == 0
    add(dst, "a", "different-owner")
    import pytest
    with sqlite3.connect(dst) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.executescript(sql.read_text(encoding="utf-8"))
        assert connection.execute("SELECT user_id FROM oracle_mesh_dispatch").fetchone()[0] == "different-owner"


def test_schema_mismatch_and_invalid_expiry_stop_without_exports(tmp_path):
    src, dst, out, sql = (tmp_path / n for n in ("q.db", "d.db", "o.json", "o.sql"))
    make_db(src)
    make_db(dst)
    add(src, "a", "owner", expires="not-a-date")
    assert run("export", src, dst, out, sql).returncode != 0
    assert not out.exists() and not sql.exists()
    with sqlite3.connect(src) as connection:
        connection.execute("DELETE FROM oracle_mesh_dispatch")
        connection.execute("ALTER TABLE oracle_mesh_dispatch ADD COLUMN extra TEXT")
    assert run("export", src, dst, out, sql).returncode != 0
    assert not out.exists() and not sql.exists()
