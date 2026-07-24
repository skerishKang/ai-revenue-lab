"""Persistence tests: task round-trips, atomic transitions, settings/BYOK,
and web restart workflows against real SQLite files (tmp_path)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import PersistenceError, get_connection
from app.domain import BranchMode, TaskStatus, Verdict
from app.factory import create_app
from app.repositories import TaskRepository, _save_run
from app.services import SqliteTaskService

FORM = {
    "title": "주문 생성 시 재고 검증 추가",
    "instruction": "재고가 부족하면 주문이 실패하도록 검증 로직을 추가해 주세요.",
    "project_id": "commerce-backend",
    "worker_model_id": "openai-gpt",
    "validator_model_id": "anthropic-claude",
    "allowed_paths": "app/, tests/",
    "denied_paths": "migrations/",
    "cost_limit_krw": "5000",
    "external_policy": "allow",
    "branch_mode": "auto",
}


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "kap.db")


@pytest.fixture()
def service(db_path):
    svc = SqliteTaskService(db_path)
    svc.initialize(seed=False)
    return svc


def _create(service, **overrides):
    form = dict(FORM)
    form.update(overrides)
    task, errors = service.create_task(form)
    assert errors == {}
    return task


# --- 18.2 task persistence ----------------------------------------------


def test_task_survives_reopen(db_path, service):
    task = _create(service)
    reopened = SqliteTaskService(db_path)
    assert reopened.get_task(task.id) is not None


def test_scalar_fields_roundtrip(db_path, service):
    task = _create(service, cost_limit_krw="1234.5")
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.title == FORM["title"]
    assert got.instruction == FORM["instruction"]
    assert got.project_id == "commerce-backend"
    assert got.worker_model_id == "openai-gpt"
    assert got.validator_model_id == "anthropic-claude"
    assert got.cost_limit_krw == 1234.5
    assert got.external_policy.value == "allow"
    assert got.branch_mode.value == "auto"
    assert got.status == TaskStatus.READY


def test_paths_order_preserved(db_path, service):
    task = _create(service, allowed_paths="app/, tests/, scripts/", denied_paths="migrations/, secrets/")
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.allowed_paths == ["app/", "tests/", "scripts/"]
    assert got.denied_paths == ["migrations/", "secrets/"]


def test_latest_run_roundtrip(db_path, service):
    task = _create(service)
    service.run_task(task.id)
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.run is not None
    assert got.run.run_number == 1
    assert got.status == TaskStatus.AWAITING_APPROVAL


def test_history_preserved_after_rework(db_path, service):
    task = _create(service)
    service.run_task(task.id)
    service.request_rework(task.id, "1차 수정")
    service.run_task(task.id)
    reopened = SqliteTaskService(db_path)
    history = reopened.run_history(task.id)
    assert [r.run_number for r in history] == [1, 2]
    assert reopened.get_task(task.id).run.run_number == 2


def test_changed_files_diff_preserved(db_path, service):
    task = _create(service)
    service.run_task(task.id)
    got = SqliteTaskService(db_path).get_task(task.id)
    files = got.run.changed_files
    assert len(files) > 0
    assert all(f.diff for f in files)
    assert all(f.path for f in files)


def test_test_summary_results_preserved(db_path, service):
    task = _create(service)
    service.run_task(task.id)
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.run.tests is not None
    assert got.run.tests.total > 0
    assert len(got.run.tests.results) > 0


def test_findings_violations_notes_preserved(db_path, service):
    task = _create(service, denied_paths="app/")  # forces REJECT + violations
    service.run_task(task.id)
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.run.verdict == Verdict.REJECT
    assert len(got.run.path_violations) > 0
    assert len(got.run.findings) > 0


def test_cost_lines_total_preserved(db_path, service):
    task = _create(service)
    service.run_task(task.id)
    got = SqliteTaskService(db_path).get_task(task.id)
    assert len(got.run.cost_lines) == 2
    assert got.run.cost_total_krw > 0


def test_timeline_order_preserved(db_path, service):
    task = _create(service)
    service.run_task(task.id)
    got = SqliteTaskService(db_path).get_task(task.id)
    labels = [e.label for e in got.run.timeline]
    assert labels == ["실행 시작", "작업자 완료", "검증자 완료"]


def test_auto_complete_branch_commit(db_path, service):
    task = _create(service, branch_mode="auto")
    service.run_task(task.id)
    service.approve_task(task.id, "검토자 김")
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.status == TaskStatus.COMPLETED
    assert got.branch_name == f"feat/demo-{task.id}"
    assert got.commit_sha is not None


def test_manual_complete_no_branch_commit(db_path, service):
    task = _create(service, branch_mode="manual")
    service.run_task(task.id)
    service.approve_task(task.id, "검토자 김")
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.status == TaskStatus.COMPLETED
    assert got.approver == "검토자 김"
    assert got.branch_name is None
    assert got.commit_sha is None


def test_reject_verdict_blocks_approval_persists(db_path, service):
    task = _create(service, denied_paths="app/")
    service.run_task(task.id)
    with pytest.raises(Exception):
        service.approve_task(task.id, "검토자")
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.status == TaskStatus.AWAITING_APPROVAL
    assert got.approver is None
    assert got.commit_sha is None


def test_rejected_task_recovers(db_path, service):
    task = _create(service)
    service.run_task(task.id)
    service.reject_task(task.id, "범위 초과")
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.status == TaskStatus.REJECTED
    assert got.rejected_reason == "범위 초과"


def test_rework_reasons_order(db_path, service):
    task = _create(service)
    service.run_task(task.id)
    service.request_rework(task.id, "첫 번째 사유")
    service.run_task(task.id)
    service.request_rework(task.id, "두 번째 사유")
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.rework_reasons == ["첫 번째 사유", "두 번째 사유"]
    assert got.rework_count == 2


# --- 18.3 atomic transitions --------------------------------------------


def _boom(self, conn, task):
    raise sqlite3.Error("simulated write failure")


def test_create_midfailure_rolls_back(db_path, service, monkeypatch):
    conn = get_connection(db_path)
    before = conn.execute("SELECT next_value FROM task_id_sequence WHERE id=1").fetchone()["next_value"]
    conn.close()
    monkeypatch.setattr(TaskRepository, "save_task", _boom)
    with pytest.raises(PersistenceError):
        _create(service)
    assert service.list_tasks() == []
    conn = get_connection(db_path)
    after = conn.execute("SELECT next_value FROM task_id_sequence WHERE id=1").fetchone()["next_value"]
    conn.close()
    assert after == before  # sequence increment rolled back


def test_run_child_insert_failure_rolls_back(db_path, service, monkeypatch):
    task = _create(service)

    def boom_run(conn, task_id, run):
        raise sqlite3.Error("simulated child failure")

    monkeypatch.setattr("app.repositories._save_run", boom_run)
    with pytest.raises(PersistenceError):
        service.run_task(task.id)
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.status == TaskStatus.READY  # unchanged
    assert got.run is None


def test_approve_save_failure_no_completed(db_path, service, monkeypatch):
    task = _create(service)
    service.run_task(task.id)
    monkeypatch.setattr(TaskRepository, "save_task", _boom)
    with pytest.raises(PersistenceError):
        service.approve_task(task.id, "검토자")
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.status == TaskStatus.AWAITING_APPROVAL
    assert got.approver is None


def test_reject_save_failure_no_rejected(db_path, service, monkeypatch):
    task = _create(service)
    service.run_task(task.id)
    monkeypatch.setattr(TaskRepository, "save_task", _boom)
    with pytest.raises(PersistenceError):
        service.reject_task(task.id, "사유")
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.status == TaskStatus.AWAITING_APPROVAL


def test_rework_save_failure_no_count(db_path, service, monkeypatch):
    task = _create(service)
    service.run_task(task.id)
    monkeypatch.setattr(TaskRepository, "save_task", _boom)
    with pytest.raises(PersistenceError):
        service.request_rework(task.id, "사유")
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.rework_count == 0
    assert got.rework_reasons == []


def test_invalid_transition_no_db_change(db_path, service):
    task = _create(service)  # READY
    with pytest.raises(Exception):
        service.approve_task(task.id, "검토자")  # cannot approve READY
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.status == TaskStatus.READY


def test_reject_approval_no_db_change(db_path, service):
    task = _create(service, denied_paths="app/")
    service.run_task(task.id)  # REJECT verdict
    with pytest.raises(Exception):
        service.approve_task(task.id, "검토자")
    got = SqliteTaskService(db_path).get_task(task.id)
    assert got.status == TaskStatus.AWAITING_APPROVAL
    assert got.approver is None
    assert got.branch_name is None


# --- 18.4 settings & BYOK -----------------------------------------------


def test_settings_survive_reopen(db_path, service):
    ok, errors = service.save_settings(
        {"domestic_first": "on", "allow_external": "", "project_cost_limit_krw": "7777"}
    )
    assert ok and errors == {}
    got = SqliteTaskService(db_path).get_settings()
    assert got.domestic_first is True
    assert got.allow_external is False
    assert got.project_cost_limit_krw == 7777.0


def test_byok_registered_recovers(db_path, service):
    service.save_settings({"apikey_byok-model": "some-key"})
    got = SqliteTaskService(db_path).get_settings()
    assert got.byok["byok-model"].registered is True


def test_blank_key_preserves_registration(db_path, service):
    service.save_settings({"apikey_byok-model": "some-key"})
    service.save_settings({"domestic_first": "on"})  # blank key
    got = SqliteTaskService(db_path).get_settings()
    assert got.byok["byok-model"].registered is True


def test_explicit_unregister(db_path, service):
    service.save_settings({"apikey_byok-model": "some-key"})
    service.save_settings({"apikey_unregister_byok-model": "on"})
    got = SqliteTaskService(db_path).get_settings()
    assert got.byok["byok-model"].registered is False


def test_invalid_settings_rolls_back_all(db_path, service):
    service.save_settings({"project_cost_limit_krw": "1000", "allow_external": "on"})
    before = SqliteTaskService(db_path).get_settings()
    ok, errors = service.save_settings(
        {"project_cost_limit_krw": "not-a-number", "allow_external": ""}
    )
    assert ok is False
    assert "project_cost_limit_krw" in errors
    after = SqliteTaskService(db_path).get_settings()
    assert after.project_cost_limit_krw == before.project_cost_limit_krw
    assert after.allow_external == before.allow_external  # unchanged


def test_mandatory_push_gate_cannot_be_false(db_path, service):
    service.save_settings({})  # block_push checkbox absent -> would be "off"
    got = SqliteTaskService(db_path).get_settings()
    assert got.block_push_without_approval is True


def test_raw_key_not_in_db_bytes(db_path, service):
    secret = "kap-raw-secret-XYZ-999"
    service.save_settings({"apikey_byok-model": secret})
    data = Path(db_path).read_bytes()
    assert secret.encode() not in data


def test_raw_key_not_in_text_dump(db_path, service):
    secret = "kap-raw-secret-ABC-111"
    service.save_settings({"apikey_byok-model": secret})
    conn = get_connection(db_path)
    try:
        tables = [
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        for table in tables:
            for row in conn.execute(f"SELECT * FROM {table}"):
                for value in tuple(row):
                    assert secret not in str(value)
    finally:
        conn.close()


def test_raw_key_not_in_response_html(db_path):
    secret = "kap-raw-secret-HTML-222"
    app = create_app(db_path=db_path)
    with TestClient(app) as client:
        client.post("/settings", data={"apikey_byok-model": secret})
        page = client.get("/settings")
        assert secret not in page.text
        assert "등록됨" in page.text


# --- 18.7 web restart workflow ------------------------------------------


def _client(db_path):
    return TestClient(create_app(db_path=db_path))


def test_web_task_detail_after_recreate(db_path):
    with _client(db_path) as client:
        resp = client.post("/tasks", data=FORM, follow_redirects=False)
        task_id = resp.headers["location"].split("/")[-1]
    with _client(db_path) as client:
        page = client.get(f"/tasks/{task_id}")
        assert page.status_code == 200
        assert FORM["title"] in page.text


def test_web_run_evidence_after_recreate(db_path):
    with _client(db_path) as client:
        resp = client.post("/tasks", data=FORM, follow_redirects=False)
        task_id = resp.headers["location"].split("/")[-1]
        client.post(f"/tasks/{task_id}/run")
    with _client(db_path) as client:
        page = client.get(f"/tasks/{task_id}")
        assert "변경 파일" in page.text
        assert "검증자 판단" in page.text


def test_web_manual_approval_after_recreate(db_path):
    form = dict(FORM, branch_mode="manual")
    with _client(db_path) as client:
        resp = client.post("/tasks", data=form, follow_redirects=False)
        task_id = resp.headers["location"].split("/")[-1]
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/approve", data={"approver": "검토자 김"})
    with _client(db_path) as client:
        page = client.get(f"/tasks/{task_id}")
        assert "수동 반영 대기" in page.text
        assert f"feat/demo-{task_id}" not in page.text


def test_web_auto_approval_after_recreate(db_path):
    with _client(db_path) as client:
        resp = client.post("/tasks", data=FORM, follow_redirects=False)
        task_id = resp.headers["location"].split("/")[-1]
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/approve", data={"approver": "검토자 김"})
    with _client(db_path) as client:
        page = client.get(f"/tasks/{task_id}")
        assert f"feat/demo-{task_id}" in page.text
        assert "검토자 김" in page.text


def test_web_reject_after_recreate(db_path):
    with _client(db_path) as client:
        resp = client.post("/tasks", data=FORM, follow_redirects=False)
        task_id = resp.headers["location"].split("/")[-1]
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/reject", data={"reason": "범위 초과"})
    with _client(db_path) as client:
        page = client.get(f"/tasks/{task_id}")
        assert "거절" in page.text


def test_web_settings_after_recreate(db_path):
    with _client(db_path) as client:
        client.post("/settings", data={"project_cost_limit_krw": "8888", "domestic_first": "on"})
    with _client(db_path) as client:
        page = client.get("/settings")
        assert "8888" in page.text


def test_web_backend_label(db_path):
    with _client(db_path) as client:
        page = client.get("/admin")
        assert "로컬 SQLite 저장" in page.text


def test_web_db_error_no_success_redirect(db_path, monkeypatch):
    with _client(db_path) as client:
        resp = client.post("/tasks", data=FORM, follow_redirects=False)
        task_id = resp.headers["location"].split("/")[-1]
        client.post(f"/tasks/{task_id}/run")

        def boom(self, conn, task):
            raise sqlite3.Error("simulated")

        monkeypatch.setattr(TaskRepository, "save_task", boom)
        approve = client.post(
            f"/tasks/{task_id}/approve", data={"approver": "x"}, follow_redirects=False
        )
        # Must be an error redirect, not a success redirect to the task page.
        assert approve.status_code == 303
        assert "error=" in approve.headers["location"]
