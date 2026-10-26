"""070 widens only Mesh presence and preserves every 067 receipt."""
import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("migration_070", ROOT / ".github/scripts/b62_d1_migration_070_schema.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def payload(db):
    db.row_factory = sqlite3.Row
    return {"success": True, "result": [
        {"success": True, "results": [dict(row) for row in db.execute(sql)]}
        for sql in module.QUERY.split(";") if sql.strip()
    ]}


def test_rebuild_preserves_rows_and_accepts_mesh_only_null_generation():
    db = sqlite3.connect(":memory:")
    old, new = module.source()
    db.executescript(old)
    db.execute("INSERT INTO mesh_device_presence VALUES ('pc@old+1',1,'2026-10-26T01:00:00Z',3)")
    assert module.classify(payload(db)) == ("067", 1)
    db.executescript(new)
    assert tuple(db.execute("SELECT * FROM mesh_device_presence").fetchone()) == ('pc@old+1',1,'2026-10-26T01:00:00Z',3,'broker')
    db.execute("INSERT INTO mesh_device_presence VALUES ('pc@mesh+2',1,'2026-10-26T01:00:00Z',NULL,'mesh')")
    assert module.classify(payload(db)) == ("070", 2)
    try:
        db.execute("INSERT INTO mesh_device_presence VALUES ('bad',1,'now',NULL,'broker')")
        raise AssertionError("Broker null generation accepted")
    except sqlite3.IntegrityError:
        pass
    db.close()


def test_drift_is_not_accepted():
    db = sqlite3.connect(":memory:")
    db.executescript("CREATE TABLE mesh_device_presence(device_id TEXT)")
    assert module.classify(payload(db))[0] == "DRIFT"
    db.close()


def test_gate_pins_main_binding_authorization_and_count_preservation():
    text = (ROOT / ".github/workflows/b62-d1-migration-070-gate.yml").read_text()
    for required in ('environment: production', 'APPLY_B62_MESH_PRESENCE_070_FROM_EXACT_MAIN',
                     'PADIEM_CHAT_DB', '067|070', 'env.STATE != \'070\'',
                     'test "${POST_COUNT}" = "${BEFORE_COUNT}"', '070_mesh_device_presence_source.sql',
                     'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"'):
        assert required in text, required


if __name__ == "__main__":
    test_rebuild_preserves_rows_and_accepts_mesh_only_null_generation()
    test_drift_is_not_accepted()
    test_gate_pins_main_binding_authorization_and_count_preservation()
    print("B62_MESH_PRESENCE_070_SOURCE=PASS")
