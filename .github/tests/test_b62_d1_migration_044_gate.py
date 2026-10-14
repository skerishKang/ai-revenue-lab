"""#4672: strict source-only D1 044 production schema classifier regression."""
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "b62_d1_migration_044_schema.py"
spec = importlib.util.spec_from_file_location("d1_044", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def payload():
    cols = [
        {"cid": i, "name": name, "type": typ, "notnull": nullable, "pk": pk, "dflt_value": None}
        for i, (name, typ, nullable, pk) in enumerate(module.COLUMNS)
    ]
    ddl = """CREATE TABLE b66_ai_turn_attempt (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        product_scope TEXT NOT NULL CHECK (product_scope = 'b66-quote'),
        turn_token TEXT NOT NULL CHECK (length(turn_token) = 32),
        model_id TEXT NOT NULL,
        request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
        state TEXT NOT NULL CHECK (state IN ('claimed', 'completed')),
        conversation_id TEXT,
        created_at TEXT NOT NULL,
        PRIMARY KEY (user_id, product_scope, turn_token),
        CHECK ((state = 'claimed' AND conversation_id IS NULL)
            OR (state = 'completed' AND conversation_id IS NOT NULL))
    )"""
    index_ddl = "CREATE INDEX idx_b66_attempt_owner_state ON b66_ai_turn_attempt (user_id, product_scope, state, created_at)"
    objs = [{"name": module.TABLE, "type": "table", "sql": ddl},
            {"name": module.INDEX, "type": "index", "sql": index_ddl}]
    ilist = [{"name": module.INDEX, "unique": 0, "origin": "c", "partial": 0}]
    xinfo = [{"seqno": i, "name": n, "cid": i, "desc": 0, "key": 1}
             for i, n in enumerate(("user_id", "product_scope", "state", "created_at"))]
    xinfo.append({"seqno": 4, "name": None, "cid": -1, "desc": 0, "key": 0})
    return {"success": True, "result": [
        {"success": True, "results": objects}
        for objects in (objs, cols, ilist, xinfo)
    ]}


def test_exact():
    assert module.classify(payload()) == "exact"


def test_missing_is_only_pre_migration():
    value = payload()
    for section in value["result"]:
        section["results"] = []
    assert module.classify(value) == "pre_044"


def test_missing_index_fails_closed():
    value = payload()
    value["result"][0]["results"].pop()
    assert module.classify(value) == "drift"


def test_wrong_owner_pk_fails_closed():
    value = payload()
    value["result"][1]["results"][0]["pk"] = 0
    assert module.classify(value) == "drift"


def test_removed_product_check_fails_closed():
    value = payload()
    value["result"][0]["results"][0]["sql"] = "CREATE TABLE b66_ai_turn_attempt (id INTEGER)"
    assert module.classify(value) == "drift"


def test_wrong_index_key_fails_closed():
    value = payload()
    value["result"][3]["results"][2]["name"] = "turn_token"
    assert module.classify(value) == "drift"


def test_malformed_d1_response_is_invalid_evidence():
    import pytest
    with pytest.raises(module.InvalidEvidence):
        module.classify({"success": True, "result": [{}]})


def test_metadata_query_readonly():
    sql = module.SQL.upper()
    assert "SQLITE_MASTER" in sql and "PRAGMA TABLE_INFO" in sql
    assert "PRAGMA INDEX_LIST" in sql and "PRAGMA INDEX_XINFO" in sql
    for forbidden in ("INSERT ", "DELETE ", "UPDATE ", "DROP ", "ALTER ", "SELECT *", "FROM USERS", "FROM MESSAGES"):
        assert forbidden not in sql
