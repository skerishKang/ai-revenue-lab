"""#5015: migration 063 — one run, several trusted dispatches — and its release gate."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "migration_063", ROOT / ".github/scripts/b62_d1_migration_063_schema.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

WORKFLOW = ROOT / ".github/workflows/b62-claw-mesh-d1-migration-063-gate.yml"


def _open(*, pre: bool) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    if pre:
        module._pre_table(db)
    return db


def _payload(db: sqlite3.Connection) -> dict:
    db.row_factory = sqlite3.Row
    blocks = []
    for statement in module.QUERY.strip().split(";"):
        if statement.strip():
            blocks.append({
                "success": True,
                "results": [dict(row) for row in db.execute(statement)],
            })
    return {"success": True, "result": blocks}


def _count_payload(value: int) -> dict:
    return {"success": True, "result": [{"success": True, "results": [{"n": value}]}]}


def test_source_is_the_pinned_reviewed_file_and_replays_the_rebuild():
    text = module.source()
    assert module.PINNED_SHA256, "the reviewed 063 source must be pinned"
    import hashlib
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == module.PINNED_SHA256
    db = _open(pre=True)
    try:
        db.executescript(text)
        assert module.classify(_payload(db)) == "exact"
    finally:
        db.close()


def test_classify_reports_the_pre_063_shape_as_applicable():
    db = _open(pre=True)
    try:
        assert module.classify(_payload(db)) == "pre_063"
    finally:
        db.close()


def test_classify_reports_a_16_char_absent_table_as_missing():
    db = sqlite3.connect(":memory:")
    try:
        assert module.classify(_payload(db)) == "missing"
    finally:
        db.close()


def test_classify_reports_drift_instead_of_mutating_it():
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE oracle_mesh_dispatch (dispatch_id TEXT PRIMARY KEY)")
        assert module.classify(_payload(db)) == "drift"
    finally:
        db.close()


def test_classify_reports_drift_when_an_index_is_missing():
    db = _open(pre=True)
    try:
        db.executescript(module.source())
        db.execute("DROP INDEX idx_oracle_mesh_dispatch_tool_request")
        assert module.classify(_payload(db)) == "drift"
    finally:
        db.close()


def test_source_refuses_a_modified_file(tmp_path):
    tampered = tmp_path / "063_tampered.sql"
    tampered.write_text(
        module.MIGRATION.read_text(encoding="utf-8") + "\nDELETE FROM oracle_mesh_dispatch;\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exceeds the reviewed rebuild"):
        module.source(tampered)


def test_source_refuses_a_file_that_is_not_the_pinned_bytes(tmp_path, monkeypatch):
    tampered = tmp_path / "063_unpinned.sql"
    tampered.write_text(
        module.MIGRATION.read_text(encoding="utf-8") + "\n-- drift\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "MIGRATION", tampered)
    with pytest.raises(ValueError, match="pinned"):
        module.source()


def test_source_refuses_the_one_row_per_run_constraint():
    text = module.MIGRATION.read_text(encoding="utf-8")
    # The reviewed file explains the old constraint in prose only; the
    # executable shape must never declare it.
    assert "unique (user_id, run_id)" not in module.code(text)


def test_apply_emits_exactly_the_reviewed_file(tmp_path):
    target = tmp_path / "apply.json"
    module.main(["apply", str(target)])
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "sql": module.MIGRATION.read_text(encoding="utf-8"),
    }


def test_check_apply_rejects_an_unsuccessful_response(tmp_path):
    target = tmp_path / "response.json"
    target.write_text(json.dumps({
        "success": True,
        "result": [{"success": False, "results": []}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="unsuccessful"):
        module.main(["check-apply", str(target)])


def test_counts_must_be_preserved_across_the_rebuild(tmp_path):
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    unchanged = tmp_path / "unchanged.json"
    before.write_text(json.dumps(_count_payload(1)), encoding="utf-8")
    after.write_text(json.dumps(_count_payload(1)), encoding="utf-8")
    unchanged.write_text(json.dumps(_count_payload(2)), encoding="utf-8")
    module.main(["check-counts", str(before), str(after)])
    with pytest.raises(ValueError, match="changed"):
        module.main(["check-counts", str(before), str(unchanged)])
    module.main(["check-count-arg", str(after), "1"])
    with pytest.raises(ValueError, match="no-op"):
        module.main(["check-count-arg", str(after), "2"])


def test_classifier_states_are_the_four_reviewed_dispositions():
    db = _open(pre=True)
    try:
        pre = module.classify(_payload(db))
        db.executescript(module.source())
        exact = module.classify(_payload(db))
    finally:
        db.close()
    assert {pre, exact} == {"pre_063", "exact"}
    for state in ("missing", "pre_063", "exact", "drift"):
        assert state in WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_the_only_reviewed_mutation_path():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "APPLY_B62_D1_MIGRATION_063_FROM_EXACT_MAIN" in text
    assert "b62_d1_migration_063_schema.py" in text
    assert "environment: production" in text
    # No second deployment system: this gate never deploys or mutates bindings.
    assert "wrangler" not in text
    assert "WORKER_DEPLOYED=0" in text
    assert "BINDING_MUTATION=0" in text
