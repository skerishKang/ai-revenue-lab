"""#5034 — the 065 Web Push subscription migration gate.

Pins the deploy-gate contract for ``065_claw_push_subscriptions.sql``:

- SOURCE_PINNED=PASS (the reviewed file is the pinned one)
- ADDITIVE_ONLY=PASS (no delete/update/drop/alter/trigger/view)
- SHAPE_MATCHES=PASS (columns and index are the reviewed ones)
- OWNER_SCOPING=PASS (one endpoint is one row per account)
- IDEMPOTENT=PASS (re-applying the file changes nothing)
- CLASSIFY=PASS (missing / exact / drift are distinguished)
- WORKFLOW_WIRED=PASS (the deploy gate runs the 065 preflight)
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_065_schema.py"
MIGRATION = ROOT / "apps/padiem-chat/migrations/065_claw_push_subscriptions.sql"
TABLE = "claw_push_subscription"
INDEX = "idx_claw_push_subscription_owner"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_065", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(rows):
    """A D1 /query response: one statement block per entry."""
    return {
        "success": True,
        "result": [{"success": True, "results": block} for block in rows],
    }


def _exact_payload():
    helper = _load_helper()
    columns = [
        {"name": name, "type": kind, "notnull": notnull, "pk": pk}
        for name, kind, notnull, pk in helper.EXPECTED_COLUMNS
    ]
    indexes = [
        {"name": INDEX, "origin": "c", "unique": 0, "partial": 0},
    ]
    return _result(
        [
            [{"name": TABLE, "type": "table", "sql": "CREATE TABLE claw_push_subscription (...)"}],
            columns,
            indexes,
        ]
    )


# --------------------------------------------------------------------------
# source contract
# --------------------------------------------------------------------------


def test_source_is_pinned() -> None:
    helper = _load_helper()
    digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    assert helper.PINNED_SHA256 == digest, "the pinned 065 digest must match the file"


def test_offline_contract_passes() -> None:
    helper = _load_helper()
    # Raises on any contract violation.
    helper.source()


def test_migration_is_additive_only() -> None:
    text = MIGRATION.read_text(encoding="utf-8")
    body = "\n".join(line.split("--", 1)[0] for line in text.splitlines()).lower()
    for forbidden in (
        "delete from",
        "update ",
        "drop table",
        "drop index",
        "alter table",
        "create trigger",
        "create view",
    ):
        assert forbidden not in body, f"065 must stay additive: {forbidden}"
    assert f"create table if not exists {TABLE}" in body
    assert f"create index if not exists {INDEX}" in body


def test_migration_creates_the_reviewed_shape() -> None:
    helper = _load_helper()
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(MIGRATION.read_text(encoding="utf-8"))
        shape = tuple(
            (row[1], str(row[2]).upper(), int(row[3]), int(row[5]))
            for row in db.execute(f"PRAGMA table_info({TABLE})").fetchall()
        )
        assert shape == helper.EXPECTED_COLUMNS
    finally:
        db.close()


def test_owner_scoping_and_idempotency() -> None:
    db = sqlite3.connect(":memory:")
    try:
        text = MIGRATION.read_text(encoding="utf-8")
        db.executescript(text)

        def insert(ident: str, member: str, endpoint: str) -> None:
            db.execute(
                f"INSERT INTO {TABLE} (id, workspace_id, member_id, endpoint, p256dh, "
                "auth, scope, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (ident, "ws", member, endpoint, "k", "a", "s", "t", "t"),
            )

        insert("push_a", "usr_1", "https://push.test/a")
        # The same endpoint twice for one account is refused.
        with pytest.raises(sqlite3.IntegrityError):
            insert("push_a2", "usr_1", "https://push.test/a")
        # A second device for the same account is fine.
        insert("push_b", "usr_1", "https://push.test/b")
        # The same endpoint for another account is a separate row.
        insert("push_c", "usr_2", "https://push.test/a")
        assert db.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0] == 3

        # Re-applying the reviewed file is a no-op.
        db.executescript(text)
        assert db.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0] == 3
    finally:
        db.close()


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------


def test_classify_exact() -> None:
    helper = _load_helper()
    assert helper.classify(_exact_payload()) == "exact"


def test_classify_missing() -> None:
    helper = _load_helper()
    assert helper.classify(_result([[], [], []])) == "missing"


def test_classify_drift_on_wrong_shape() -> None:
    helper = _load_helper()
    payload = _exact_payload()
    payload["result"][1]["results"] = payload["result"][1]["results"][:-1]
    assert helper.classify(payload) == "drift"


def test_classify_drift_on_missing_index() -> None:
    helper = _load_helper()
    payload = _exact_payload()
    payload["result"][2]["results"] = []
    assert helper.classify(payload) == "drift"


# --------------------------------------------------------------------------
# workflow wiring
# --------------------------------------------------------------------------


def test_deploy_gate_runs_the_065_preflight() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "b62_d1_migration_065_schema.py" in text
    assert "B62_D1_MIGRATION_065_SCHEMA=EXACT" in text
    assert "MIGRATION_065_PREDEPLOY=EXACT" in text
    # The migration file itself must trigger the gate.
    assert "065_claw_push_subscriptions.sql" in text
