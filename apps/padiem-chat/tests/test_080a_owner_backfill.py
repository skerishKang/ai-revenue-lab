from pathlib import Path
import sqlite3

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

def test_080_then_backfill_only_unambiguous_matching_owners():
    db = sqlite3.connect(":memory:")
    db.executescript("""
    CREATE TABLE users(id TEXT PRIMARY KEY);
    CREATE TABLE claw_document_metadata(document_id TEXT PRIMARY KEY, tenant_id TEXT, object_key TEXT, filename TEXT);
    CREATE TABLE claw_run_history(artifact_document_id TEXT, user_id TEXT);
    CREATE TABLE claw_conversation_artifact_index(artifact_id TEXT, user_id TEXT, workspace_ref TEXT, location_ref TEXT);
    INSERT INTO users VALUES ('alice'), ('bob');
    """)
    digest = "a" * 64
    def add(doc, owner="alice", filename="file.xlsx"):
        key = f"workspaces/team/claw/web-office/{owner}/team/{doc}/{digest}/{filename}"
        db.execute("INSERT INTO claw_document_metadata VALUES (?,?,?,?)", (doc,"team",key,filename))
        return key
    add("path")
    db.execute("INSERT INTO claw_document_metadata VALUES (?,?,?,?)",("run","team","elsewhere","file.xlsx"))
    db.execute("INSERT INTO claw_run_history VALUES (?,?)",("run","bob"))
    add("conflict")
    db.execute("INSERT INTO claw_run_history VALUES (?,?)",("conflict","bob"))
    add("index_mismatch")
    db.execute("INSERT INTO claw_conversation_artifact_index VALUES (?,?,?,?)",("index_mismatch","bob","team","elsewhere"))
    add("run_mismatch")
    db.execute("INSERT INTO claw_run_history VALUES (?,?)",("run_mismatch",None))
    key = add("index_match")
    db.execute("INSERT INTO claw_conversation_artifact_index VALUES (?,?,?,?)",("index_match","alice","team",key))
    add("existing")
    db.executescript((MIGRATIONS/"080_claw_document_metadata_user_id.sql").read_text())
    db.execute("UPDATE claw_document_metadata SET user_id='bob' WHERE document_id='existing'")
    sql=(MIGRATIONS/"080a_claw_document_metadata_user_id_backfill.sql").read_text()
    for _ in range(2):
        db.executescript(sql)
        rows=dict(db.execute("SELECT document_id,user_id FROM claw_document_metadata"))
        assert rows == {"path":"alice","run":"bob","conflict":None,"index_mismatch":None,
                        "run_mismatch":None,"index_match":"alice","existing":"bob"}
