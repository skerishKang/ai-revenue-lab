"""B62 deploy hard gate for the real 041 B66 slot + 042 conversation scope.

No Cloudflare credentials or application rows. SQLite fixtures execute the
unchanged real source migrations, then fetch schema metadata only.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_d1_migration_041_042_schema.py"
WORKFLOW = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
MIG = ROOT / "apps/padiem-chat/migrations"


def module():
    spec = importlib.util.spec_from_file_location("predeploy_041_042", SCRIPT)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def evidence(*, has_041=False, has_042=False, has_chat=True):
    conn = sqlite3.connect(":memory:")
    if has_chat:
        for name in ("001_auth_history.sql", "002_projects.sql"):
            conn.executescript((MIG/name).read_text(encoding="utf-8"))
    if has_041:
        conn.executescript((MIG/"041_b66_ai_conversation.sql").read_text(encoding="utf-8"))
    if has_042:
        conn.executescript((MIG/"042_conversation_product_scope.sql").read_text(encoding="utf-8"))
    sqls = [m.strip() for m in module().SCHEMA_SQL.split(";") if m.strip()]
    rows = [{"success": True, "results": [dict(zip(keys, row)) for row in conn.execute(query)]}
            for query, keys in zip(sqls, (
                ("name", "type", "sql"),
                ("cid", "name", "type", "notnull", "dflt_value", "pk"),
                ("cid", "name", "type", "notnull", "dflt_value", "pk"),
                ("seqno", "cid", "name", "desc", "coll", "key"),
                ("seq", "name", "unique", "origin", "partial"),
            ))]
    conn.close()
    return {"success": True, "result": rows}


def test_real_sql_migration_state_progression():
    classify = module().classify
    assert classify(evidence()) == "pre_041"
    assert classify(evidence(has_041=True)) == "pre_042"
    assert classify(evidence(has_041=True,has_042=True)) == "exact"
    assert classify(evidence(has_chat=False)) == "missing"
    # An out-of-order 042 ahead of 041 must never be considered ready.
    assert classify(evidence(has_042=True)) == "drift"


@pytest.mark.parametrize("mutate", [
    lambda p: p["result"].pop(),
    lambda p: p["result"][0]["results"].append(p["result"][0]["results"][0].copy()),
    lambda p: p["result"][1]["results"][3].update({"type": "TEXT"}),
    lambda p: p["result"][1]["results"][3].update({"dflt_value": "1"}),
    lambda p: p["result"][1]["results"][0].update({"notnull": 0}),
    lambda p: p["result"][0]["results"][0].update({"type": "view"}),
    lambda p: p["result"][0]["results"][0].update({"sql": "CREATE TABLE fake(x)"}),
    lambda p: p["result"][2]["results"][-1].update({"dflt_value": "'other'"}),
    lambda p: p["result"][2]["results"][-1].update({"type": "INTEGER"}),
    lambda p: p["result"][3]["results"][2].update({"desc": 0}),
    lambda p: p["result"][4]["results"][0].update({"partial": 1}),
    lambda p: p["result"][0]["results"].pop(),  # one schema object absent
    lambda p: p["result"][3]["results"].pop(),
])
def test_schema_drift_malformed_or_tampered_denied(mutate):
    payload = evidence(has_041=True, has_042=True)
    mutate(payload)
    classifier = module().classify
    try:
        assert classifier(payload) != "exact"
    except ValueError:
        pass


def test_missing_or_untrusted_evidence_fails_closed():
    checker = module()
    valid = evidence(has_041=True, has_042=True)
    for invalid in (None, [], {}, {"success": True},
                    {"success": False, "result": valid["result"]},
                    {"success": True, "result": [None]*5},
                    {"success": True, "result": [{"success": False, "results": []}]*5}):
        with pytest.raises(ValueError):
            checker.classify(invalid)


def test_query_has_only_metadata_selects_and_no_mutations():
    sql = module().SCHEMA_SQL
    statements = [part.strip().upper() for part in sql.split(";") if part.strip()]
    assert len(statements) == 5
    assert statements[0].startswith("SELECT NAME, TYPE, SQL FROM SQLITE_MASTER")
    assert all(statement.startswith("PRAGMA ") for statement in statements[1:])
    assert "FROM CONVERSATIONS" not in sql.upper()
    assert "FROM B66_AI_CONVERSATION" not in sql.upper()
    for forbidden in ("DELETE ", "UPDATE ", "INSERT ", "ALTER ", "DROP ", "CREATE ", "ATTACH "):
        assert forbidden not in sql.upper()


def test_cli_rejects_pre041_pre042_and_accepts_exact_without_identifiers(tmp_path, capsys):
    checker = module()
    file = tmp_path/"evidence.json"
    for status, a, b in (("pre_041",False,False),("pre_042",True,False),("exact",True,True)):
        file.write_text(json.dumps(evidence(has_041=a,has_042=b)), encoding="utf-8")
        result = checker.main(["check",str(file)])
        output=capsys.readouterr().out
        assert (result == 0) == (status == "exact")
        assert f"B62_D1_SCHEMA_041_042={status.upper()}" in output
        assert ("MIGRATION_041_042_PREDEPLOY=EXACT" in output) == (status == "exact")
    query_file=tmp_path/"query.json"
    assert checker.main(["write-query",str(query_file)]) == 0
    assert json.loads(query_file.read_text()) == {"sql":checker.SCHEMA_SQL}
    assert checker.main(["write-query",str(query_file)]) != 0


def test_production_deploy_uses_actual_readonly_live_schema_before_mutation():
    text = WORKFLOW.read_text(encoding="utf-8")
    probe = text.index("\n      - name: Prove migrations 041 and 042 B66 and Chat scope live schema before deploy")
    upload = text.index("\n      - name: Deploy production code preserving the full binding set")
    prior = text.index("\n      - name: Prove migration 040 receipt schema live state before deploy")
    assert prior < probe < upload
    step = text[probe:upload]
    assert "b62_d1_migration_041_042_schema.py write-query" in step
    assert "b62_d1_migration_041_042_schema.py check" in step
    assert "MIGRATION_041_042_PREDEPLOY=EXACT" in step
    assert "PADIEM_CHAT_DB" in text
    assert "/d1/database/${db_id}/query" in step
    assert "D1_SCHEMA_QUERY=READ_ONLY" in step
    assert "APPLICATION_ROW_READ=0" in step
    assert "D1_IDENTIFIER_OUTPUT=0" in step
    assert "PRODUCTION_MUTATION=0" in step
    assert "if: ${{ github.event_name == 'workflow_dispatch' &&" not in step


def test_workflow_source_contract_checks_both_real_migrations():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'test_b62_d1_migration_041_042_gate.py -q' in text
    assert 'apps/padiem-chat/migrations/041_b66_ai_conversation.sql' in text
    assert 'apps/padiem-chat/migrations/042_conversation_product_scope.sql' in text
    assert 'B62_D1_SCHEMA_041_042=EXACT' in text
    assert 'MIGRATION_041_042_PREDEPLOY=EXACT' in text
