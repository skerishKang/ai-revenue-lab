"""Synthetic tests for the Chat COM2 -> D1 handback gate (#5115).

The gate is the rollback path option (가) of #6197: the delta COM2 accepted
since the cutover baseline, applied back to D1. These tests use small synthetic
SQLite files only; nothing touches Production D1 and no workflow is dispatched.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPTS = ROOT / ".github" / "scripts"
WORKFLOW = ROOT / ".github" / "workflows" / "chat-d1-handback-gate.yml"


def load_gate():
    spec = importlib.util.spec_from_file_location(
        "chat_d1_handback_gate", SCRIPTS / "chat_d1_handback_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load_gate()


def _db(path: Path, rows: dict[str, list[tuple]], skip_tables: tuple[str, ...] = ()) -> Path:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT, note TEXT)")
    connection.execute(
        "CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id TEXT, title TEXT)"
    )
    connection.execute("CREATE TABLE oracle_mesh_dispatch (id TEXT PRIMARY KEY, state TEXT)")
    connection.execute("CREATE TABLE d1_migrations (id INTEGER PRIMARY KEY, name TEXT)")
    for table in skip_tables:
        connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, v TEXT)')
    for table, values in rows.items():
        for value in values:
            placeholders = ", ".join("?" for _ in value)
            connection.execute(f'INSERT INTO "{table}" VALUES ({placeholders})', value)
    connection.commit()
    connection.close()
    return path


@pytest.fixture()
def pair(tmp_path: Path):
    baseline = _db(
        tmp_path / "baseline.sqlite3",
        {
            "users": [("u1", "owner", None), ("u2", "guest", None), ("u3", "gone", None)],
            "conversations": [("c1", "u1", "first")],
            "oracle_mesh_dispatch": [("d1", "queued")],
            "d1_migrations": [(1, "001")],
        },
    )
    handback = _db(
        tmp_path / "handback.sqlite3",
        {
            "users": [("u1", "owner", "edited"), ("u2", "guest", None), ("u4", "new", None)],
            "conversations": [("c1", "u1", "first"), ("c2", "u1", "second")],
            "oracle_mesh_dispatch": [("d1", "queued"), ("d2", "drained")],
            "d1_migrations": [(1, "001"), (2, "002")],
        },
    )
    return baseline, handback


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_plan_counts_each_kind_of_change(pair):
    baseline, handback = pair
    plan = gate.build_plan(baseline, handback)

    users = plan["tables"]["users"]
    assert users == {
        "added": 1,          # u4
        "changed": 1,        # u1 note
        "removed": 1,        # u3
        "baseline_rows": 3,
        "handback_rows": 3,
    }
    conversations = plan["tables"]["conversations"]
    assert conversations["added"] == 1 and conversations["changed"] == 0
    assert plan["statement_count"] == 4
    assert json.loads(plan["keys"]["removed"]["users"][0]) == ["u3"]


def test_owned_and_bookkeeping_tables_never_travel(pair):
    baseline, handback = pair
    plan = gate.build_plan(baseline, handback)

    assert "oracle_mesh_dispatch" not in plan["tables"]
    assert "d1_migrations" not in plan["tables"]
    assert set(plan["tables"]) == {"users", "conversations"}


def test_plan_and_verify_never_write_either_file(pair, tmp_path):
    baseline, handback = pair
    before = (_sha(baseline), _sha(handback))
    plan_path = tmp_path / "plan.json"

    assert gate.main([
        "plan", "--baseline", str(baseline), "--handback", str(handback), "--out", str(plan_path),
    ]) == gate.EXIT_OK
    assert gate.main([
        "verify", "--baseline", str(baseline), "--handback", str(handback), "--plan", str(plan_path),
    ]) == gate.EXIT_OK

    assert (_sha(baseline), _sha(handback)) == before
    # Only the plan file the operator asked for exists.
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "baseline.sqlite3", "handback.sqlite3", "plan.json",
    ]


def test_verify_fails_when_the_source_moved_after_the_plan(pair, tmp_path):
    baseline, handback = pair
    plan_path = tmp_path / "plan.json"
    gate.main([
        "plan", "--baseline", str(baseline), "--handback", str(handback), "--out", str(plan_path),
    ])

    connection = sqlite3.connect(handback)
    connection.execute("UPDATE users SET note='late' WHERE id='u2'")
    connection.commit()
    connection.close()

    assert gate.main([
        "verify", "--baseline", str(baseline), "--handback", str(handback), "--plan", str(plan_path),
    ]) == gate.EXIT_REFUSED


def test_apply_refuses_and_writes_no_sql_when_the_plan_drifted(pair, tmp_path):
    baseline, handback = pair
    plan_path = tmp_path / "plan.json"
    gate.main([
        "plan", "--baseline", str(baseline), "--handback", str(handback), "--out", str(plan_path),
    ])

    connection = sqlite3.connect(handback)
    connection.execute("INSERT INTO users VALUES ('u9','late','x')")
    connection.commit()
    connection.close()

    out = tmp_path / "handback.sql"
    assert gate.main([
        "apply", "--baseline", str(baseline), "--handback", str(handback),
        "--plan", str(plan_path), "--out", str(out),
    ]) == gate.EXIT_REFUSED
    assert not out.exists()


def test_apply_without_an_approved_plan_is_refused(pair, tmp_path):
    baseline, handback = pair
    out = tmp_path / "handback.sql"
    assert gate.main([
        "apply", "--baseline", str(baseline), "--handback", str(handback), "--out", str(out),
    ]) == gate.EXIT_REFUSED
    assert not out.exists()


def test_applied_sql_round_trips_the_handback_state(pair, tmp_path):
    baseline, handback = pair
    plan_path = tmp_path / "plan.json"
    gate.main([
        "plan", "--baseline", str(baseline), "--handback", str(handback), "--out", str(plan_path),
    ])
    out = tmp_path / "handback.sql"
    assert gate.main([
        "apply", "--baseline", str(baseline), "--handback", str(handback),
        "--plan", str(plan_path), "--out", str(out),
    ]) == gate.EXIT_OK

    sql = out.read_text(encoding="utf-8")
    assert sql.startswith("-- Chat COM2 -> D1 handback")
    assert "BEGIN IMMEDIATE;" in sql and sql.rstrip().endswith("COMMIT;")
    assert "INSERT INTO \"users\"" in sql
    assert "UPDATE \"users\"" in sql
    assert "DELETE FROM \"users\"" in sql

    replay = tmp_path / "replay.sqlite3"
    replay.write_bytes(baseline.read_bytes())
    connection = sqlite3.connect(replay)
    connection.executescript(sql)
    connection.commit()
    connection.close()

    # After the handback, D1 holds exactly the COM2 rows: the delta is empty.
    assert gate.build_plan(replay, handback)["statement_count"] == 0


def test_a_table_without_a_primary_key_is_refused(tmp_path):
    baseline = _db(tmp_path / "baseline.sqlite3", {"users": [("u1", "owner", None)]})
    handback = _db(tmp_path / "handback.sqlite3", {"users": [("u1", "owner", None)]})
    connection = sqlite3.connect(handback)
    connection.execute("CREATE TABLE loose (a TEXT, b TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(gate.GateError) as excinfo:
        gate.build_plan(baseline, handback)
    assert "CHAT_HANDBACK_NO_PRIMARY_KEY" in str(excinfo.value)


def test_schema_mismatch_is_refused(tmp_path):
    baseline = _db(tmp_path / "baseline.sqlite3", {"users": [("u1", "owner", None)]})
    handback = _db(tmp_path / "handback.sqlite3", {"users": [("u1", "owner", None)]})
    connection = sqlite3.connect(handback)
    connection.execute("CREATE TABLE only_on_com2 (id TEXT PRIMARY KEY)")
    connection.commit()
    connection.close()

    with pytest.raises(gate.GateError) as excinfo:
        gate.build_plan(baseline, handback)
    assert "CHAT_HANDBACK_SCHEMA_MISMATCH" in str(excinfo.value)


def test_workflow_keeps_the_repo_gate_contract():
    text = WORKFLOW.read_text(encoding="utf-8")

    for token in (
        "workflow_dispatch",
        "refs/heads/main",
        "^[0-9a-f]{40}$",
        "_CHAT_D1_HANDBACK_${TARGET_SHA}",
        "persist-credentials: false",
        "environment:",
        "production",
        "mode == 'verify'",
        "chat_d1_handback_gate.py plan",
        "chat_d1_handback_gate.py verify",
        "chat_d1_handback_gate.py apply",
        "retention-days:",
    ):
        assert token in text, token

    # validate -> checkout -> verify main -> download -> plan/verify -> apply -> after-check
    phases = [
        "Validate dispatch before checkout",
        "Checkout the exact target SHA",
        "Verify main still points at the target SHA",
        "Download the baseline snapshot and the COM2 handback copy",
        "- name: plan",
        "- name: verify",
        "- name: apply",
        "- name: Apply the handback SQL to D1 in one transaction",
        "- name: Verify D1 now equals the handback snapshot",
    ]
    positions = [text.index(phase) for phase in phases]
    assert positions == sorted(positions)
