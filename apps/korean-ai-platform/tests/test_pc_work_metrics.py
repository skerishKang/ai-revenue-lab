"""Final PC-turn counters annotate actual B14 usage, not a second ledger."""
from __future__ import annotations

import asyncio
import hashlib
import time

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.local_runtime import SqliteLedger
from app.pilot.call_ledger import CallRecord
from app.pilot.call_ledger_store import CallLedgerStore

REPORT = "/api/pilot/v1/internal/pc-turn-metrics"
RECENT = "/api/pilot/v1/admin/model-calls/pc-turns"
SUBJECT = "subject_fixture"
TURN = "pcturn_" + hashlib.sha256(b"synthetic-turn-one").hexdigest()
SECOND = "pcturn_" + hashlib.sha256(b"synthetic-turn-two").hexdigest()


def metrics(turn=TURN, **changes):
    result = {
        "schema_version": 1, "turn_id": turn,
        "pc_round_trips": 2, "calls": 2, "tool_calls": {
            "claw.pc.read_file": {
                "calls": 2, "pc_round_trips": 2, "truncation_count": 0,
                "truncated_bytes_known": 0, "truncated_bytes_unknown_count": 0,
                "timeout_count": 0,
            },
        },
        "truncation_count": 0, "truncated_bytes_known": 0,
        "truncated_bytes_unknown_count": 0, "truncated_bytes": 0,
        "timeout_count": 0, "model_calls": 1, "model_input_tokens": 100,
        "model_input_tokens_observed": 100, "model_input_tokens_missing_calls": 0,
        "model_input_tokens_estimated": 200.0, "tool_result_tokens_estimated": 25.0,
        "tool_result_input_ratio": 0.125, "token_ratio_basis": "utf8_bytes_div4_estimate",
        "outcome": "completed", "outcome_reason": "completed",
    }
    result.update(changes)
    return result


def envelope(turn=TURN, *, product="claw", subject=SUBJECT, measurement=None):
    return {"product": product, "subject_ref": subject, "session_ref": turn,
            "metrics": measurement if measurement is not None else metrics(turn)}


def insert(store, *, suffix="one", turn=TURN, product="claw", subject=SUBJECT,
           started="2026-11-01T12:00:00Z", selected_model_id=None):
    row = CallRecord(
        log_id="b14call_metrics_" + suffix, request_id="b14req_metrics_" + suffix,
        endpoint="/api/pilot/v1/chat/completions", product=product,
        subject_ref=subject, session_ref=turn, origin_request_id="trace_original",
        started_at=started, prompt_tokens=100, completion_tokens=20, total_tokens=120,
        token_source="measured",
        selected_model_id=selected_model_id,
    )
    assert asyncio.run(store.record(row)) == "written"
    return row.log_id


@pytest.fixture
def backed_client(tmp_path):
    ledger = SqliteLedger(tmp_path / "b14.sqlite3")
    ledger.apply_migrations()
    store = CallLedgerStore(ledger)
    app = create_app()
    app.state.call_ledger_store = store
    with TestClient(app) as client:
        yield client, store, ledger
    ledger.close()


def test_final_metrics_attach_once_preserve_tokens_and_recent_query_is_not_log_id(backed_client):
    client, store, db = backed_client
    first = insert(store)
    insert(store, suffix="two")  # One turn can have several real model calls.
    before = [tuple(row) for row in db.connect().execute(
        "SELECT log_id,request_id,prompt_tokens,completion_tokens,total_tokens,token_source "
        "FROM b14_model_call ORDER BY log_id")]
    report = client.post(REPORT, json=envelope())
    assert report.status_code == 200 and report.json()["ok"] is True
    assert report.json()["log_id"] == first
    assert client.post(REPORT, json=envelope()).json() == report.json()
    rows = db.connect().execute(
        "SELECT log_id,request_id,prompt_tokens,completion_tokens,total_tokens,token_source "
        "FROM b14_model_call ORDER BY log_id").fetchall()
    assert [tuple(row) for row in rows] == before
    assert db.connect().execute(
        "SELECT count(*) FROM b14_model_call WHERE pc_work_metrics_json IS NOT NULL"
    ).fetchone()[0] == 1
    response = client.get(RECENT + "?limit=1")
    assert response.status_code == 200
    body = response.json()
    assert body["unit"] == "pc_turn" and body["limit"] == 1
    assert body["summary"]["turn_count"] == 1
    assert body["turns"][0]["origin_request_id"] == "trace_original"
    assert body["turns"][0]["metrics"] == metrics()
    assert response.headers["cache-control"] == "no-store"


def test_no_synthetic_model_row_is_created_while_deferred_usage_is_pending(backed_client):
    client, store, db = backed_client
    result = client.post(REPORT, json=envelope())
    assert result.status_code == 409 and result.json()["error"]["code"] == "ledger_pending"
    assert db.connect().execute("SELECT count(*) FROM b14_model_call").fetchone()[0] == 0
    insert(store)
    assert client.post(REPORT, json=envelope()).status_code == 200


def test_unfinished_turns_remain_visible_once_without_guessing_abandonment(backed_client):
    client, store, _ = backed_client
    insert(store)
    insert(store, suffix="unfinished_second_call")
    before = client.get(RECENT).json()
    assert len(before["turns"]) == 1
    assert before["turns"][0]["metrics"] is None
    assert before["turns"][0]["metrics_status"] == "not_finalized"
    assert before["summary"]["turn_count"] == 1
    assert before["summary"]["measured_turn_count"] == 0
    assert before["summary"]["outcomes"] == {"not_finalized": 1}
    assert before["summary"]["counters"]["pc_round_trips"] == {
        "average": None, "max": None, "observed_turns": 0, "missing_turns": 1,
    }
    assert before["summary"]["timeout_ranking"] == []
    assert client.post(REPORT, json=envelope()).status_code == 200
    after = client.get(RECENT).json()
    assert len(after["turns"]) == 1
    assert after["turns"][0]["session_ref"] == before["turns"][0]["session_ref"]
    assert after["turns"][0]["metrics_status"] == "finalized"
    assert after["summary"]["measured_turn_count"] == 1


def test_recent_n_counts_unique_pc_turns_and_skips_ordinary_usage(backed_client):
    client, store, _ = backed_client
    insert(store)
    insert(store, suffix="same_turn")
    insert(store, suffix="second", turn=SECOND, started="2026-11-01T13:00:00Z")
    insert(store, suffix="ordinary", turn="ordinary_session", started="2026-11-01T14:00:00Z")
    rows = client.get(RECENT + "?limit=2").json()["turns"]
    assert [row["session_ref"] for row in rows] == [SECOND, TURN]
    assert len(client.get(RECENT + "?limit=1").json()["turns"]) == 1


@pytest.mark.parametrize("query", [
    "selected_model_id=synthetic_later_model",
    "request_id=b14req_metrics_later",
    "since=2026-11-01T12:30:00Z&until=2026-11-01T13:30:00Z",
])
def test_filter_matching_later_model_call_preserves_finalized_turn_anchor(backed_client, query):
    client, store, _ = backed_client
    anchor = insert(store, selected_model_id="synthetic_first_model")
    insert(store, suffix="later", selected_model_id="synthetic_later_model",
           started="2026-11-01T13:00:00Z")
    assert client.post(REPORT, json=envelope()).status_code == 200
    body = client.get(RECENT + "?" + query).json()
    assert len(body["turns"]) == 1
    assert body["turns"][0]["log_id"] == anchor
    assert body["turns"][0]["metrics_status"] == "finalized"
    assert body["summary"]["measured_turn_count"] == 1


def test_late_older_model_row_does_not_create_a_second_metrics_anchor(backed_client):
    client, store, db = backed_client
    anchor = insert(store)
    assert client.post(REPORT, json=envelope()).status_code == 200
    insert(store, suffix="late", started="2026-11-01T11:00:00Z")
    replay = client.post(REPORT, json=envelope())
    assert replay.status_code == 200 and replay.json()["log_id"] == anchor
    assert db.connect().execute(
        "SELECT count(*) FROM b14_model_call WHERE pc_work_metrics_json IS NOT NULL"
    ).fetchone()[0] == 1


def test_changed_report_is_a_conflict_not_a_rewrite(backed_client):
    client, store, _ = backed_client
    insert(store)
    client.post(REPORT, json=envelope())
    changed = metrics(outcome="failed", outcome_reason="execution_failed")
    response = client.post(REPORT, json=envelope(measurement=changed))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "metrics_conflict"
    assert client.get(RECENT).json()["turns"][0]["metrics"]["outcome"] == "completed"


@pytest.mark.parametrize("changed", [
    {"subject_ref": "another_subject"}, {"product": "chat"},
    {"session_ref": SECOND, "metrics": metrics(SECOND)},
])
def test_matching_product_subject_and_server_turn_are_all_required(backed_client, changed):
    client, store, db = backed_client
    insert(store)
    body = {**envelope(), **changed}
    assert client.post(REPORT, json=body).status_code == 409
    assert db.connect().execute(
        "SELECT count(*) FROM b14_model_call WHERE pc_work_metrics_json IS NOT NULL"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("changed", [
    {"metrics": metrics(outcome="running", outcome_reason="in_progress")},
    {"metrics": metrics(SECOND)}, {"subject_ref": "customer@example.invalid"},
    {"product": "api"}, {"metrics": {**metrics(), "file_path": "PRIVATE_PATH"}},
    {"prompt": "PRIVATE_PROMPT"},
])
def test_report_refuses_nonterminal_mismatched_or_content_carrying_payload(backed_client, changed):
    client, store, _ = backed_client
    insert(store)
    response = client.post(REPORT, json={**envelope(), **changed})
    assert response.status_code == 422
    assert "PRIVATE" not in response.text


@pytest.mark.no_b14_service_proof
def test_report_and_recent_summary_require_existing_hmac_even_in_mock(backed_client):
    client, store, db = backed_client
    insert(store)
    assert client.post(REPORT, json=envelope()).status_code == 401
    assert client.get(RECENT).status_code == 401
    assert db.connect().execute(
        "SELECT count(*) FROM b14_model_call WHERE pc_work_metrics_json IS NOT NULL"
    ).fetchone()[0] == 0


def test_body_tampering_does_not_reuse_a_service_proof(backed_client, b14_service_proof_secret):
    from app.pilot.service_proof import compute_service_proof
    client, store, _ = backed_client
    insert(store)
    timestamp = str(int(time.time()))
    proof = compute_service_proof(b14_service_proof_secret, timestamp, b"{}")
    assert client.post(REPORT, json=envelope(), headers={
        "x-padiem-b14-time": timestamp, "x-padiem-b14-proof": proof,
    }).status_code == 401


def test_recent_n_summary_distinguishes_unknown_bytes_tokens_and_estimates(backed_client):
    client, store, _ = backed_client
    insert(store)
    client.post(REPORT, json=envelope())
    insert(store, suffix="second", turn=SECOND)
    unknown = metrics(SECOND, model_input_tokens=None, model_input_tokens_observed=0,
                      model_input_tokens_missing_calls=1, truncated_bytes=None,
                      truncated_bytes_unknown_count=1, truncation_count=1,
                      timeout_count=1, outcome="failed", outcome_reason="tool_timeout")
    unknown["tool_calls"]["claw.pc.read_file"].update(
        truncation_count=1, truncated_bytes_unknown_count=1, timeout_count=1)
    assert client.post(REPORT, json=envelope(SECOND, measurement=unknown)).status_code == 200
    body = client.get(RECENT + "?limit=2&product=claw").json()
    summary = body["summary"]
    assert summary["turn_count"] == 2
    assert summary["outcomes"] == {"completed": 1, "failed": 1}
    assert summary["outcome_reasons"] == {"completed": 1, "tool_timeout": 1}
    assert summary["counters"]["pc_round_trips"]["average"] == 2
    assert summary["counters"]["timeout_count"]["max"] == 1
    assert summary["counters"]["truncated_bytes"]["missing_turns"] == 1
    assert summary["counters"]["model_input_tokens"] == {
        "average": 100, "max": 100, "observed_turns": 1, "missing_turns": 1,
    }
    assert summary["token_ratio_basis"] == "utf8_bytes_div4_estimate"
    assert summary["tools"][0]["tool_id"] == "claw.pc.read_file"
    assert summary["tools"][0]["pc_round_trips"] == 4
    assert len(client.get(RECENT + "?limit=1").json()["turns"]) == 1
    assert client.get(RECENT + "?subject_ref=another_subject").json()["turns"] == []


def test_truncation_and_timeout_rankings_keep_distinct_tools_and_recovered_failure(backed_client):
    client, store, _ = backed_client
    insert(store)
    snapshot = metrics(
        calls=3, pc_round_trips=3, truncation_count=1, truncated_bytes=None,
        truncated_bytes_unknown_count=1, timeout_count=2,
        outcome="completed", outcome_reason="tool_timeout",
    )
    snapshot["tool_calls"] = {
        "claw.pc.read_file": {"calls": 1, "pc_round_trips": 1,
                              "truncation_count": 1, "truncated_bytes_known": 0,
                              "truncated_bytes_unknown_count": 1, "timeout_count": 0},
        "claw.pc.write_file": {"calls": 2, "pc_round_trips": 2,
                               "truncation_count": 0, "truncated_bytes_known": 0,
                               "truncated_bytes_unknown_count": 0, "timeout_count": 2},
    }
    assert client.post(REPORT, json=envelope(measurement=snapshot)).status_code == 200
    summary = client.get(RECENT).json()["summary"]
    assert summary["truncation_ranking"][0]["tool_id"] == "claw.pc.read_file"
    assert summary["timeout_ranking"][0]["tool_id"] == "claw.pc.write_file"
    assert summary["outcomes"] == {"completed": 1}
    assert summary["outcome_reasons"] == {"tool_timeout": 1}


def test_deployment_stages_the_same_shared_validator_source():
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    deploy = (root / "apps/korean-ai-platform/deploy.sh").read_text()
    preflight = (root / ".github/workflows/b14-worker-json-bundle-preflight.yml").read_text()
    assert "document_parser_boundary.py pc_work_metrics.py; do" in deploy
    assert "document_parser_boundary.py pc_work_metrics.py; do" in preflight


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "unknown=private", "group_by=product"])
def test_recent_query_reuses_existing_limit_and_query_contract(backed_client, query):
    client, _, _ = backed_client
    assert client.get(RECENT + "?" + query).status_code == 422


def test_0003_upgrades_existing_b14_without_new_usage_store(tmp_path):
    import shutil
    from pathlib import Path
    old_migrations = tmp_path / "old_migrations"
    old_migrations.mkdir()
    source = Path(__file__).resolve().parents[1] / "migrations"
    for name in ("0001_b14_model_call_ledger.sql", "0002_credential_source.sql"):
        shutil.copyfile(source / name, old_migrations / name)
    path = tmp_path / "upgrade.sqlite3"
    old = SqliteLedger(path, migrations_dir=old_migrations)
    assert old.apply_migrations() == 2
    insert(CallLedgerStore(old))
    old.close()
    current = SqliteLedger(path)
    assert current.apply_migrations() == 1
    assert current.apply_migrations() == 0
    columns = {row[1] for row in current.connect().execute("PRAGMA table_info(b14_model_call)")}
    assert {"pc_work_metrics_json", "pc_work_metrics_recorded_at"} <= columns
    tables = {row[0] for row in current.connect().execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"b14_model_call", "b14_model_call_attempt", "b14_local_migration"}
    assert current.connect().execute("SELECT total_tokens FROM b14_model_call").fetchone()[0] == 120
    current.close()


def test_v2_lifecycle_counters_persist_and_v1_remains_missing_in_summary(backed_client):
    client, store, db = backed_client
    insert(store, suffix="legacy", turn=TURN)
    insert(store, suffix="lifecycle", turn=SECOND)
    legacy = metrics(TURN)
    measured = metrics(
        SECOND, schema_version=2, stored_output_count=3,
        compaction_count=2, background_job_count=1,
    )
    for turn, snapshot in ((TURN, legacy), (SECOND, measured)):
        assert client.post(REPORT, json=envelope(turn, measurement=snapshot)).status_code == 200
    # The same v2 report remains idempotent in the existing immutable ledger.
    assert client.post(REPORT, json=envelope(SECOND, measurement=measured)).status_code == 200
    response = client.get(RECENT)
    assert response.status_code == 200
    result = response.json()
    turns = {row["session_ref"]: row["metrics"] for row in result["turns"]}
    assert turns[TURN] == legacy
    assert turns[SECOND] == measured
    for key, count in (
        ("stored_output_count", 3), ("compaction_count", 2), ("background_job_count", 1)
    ):
        assert result["summary"]["counters"][key] == {
            "average": count, "max": count, "observed_turns": 1, "missing_turns": 1,
        }
    assert db.connect().execute("SELECT COUNT(*) FROM b14_model_call").fetchone()[0] == 2
