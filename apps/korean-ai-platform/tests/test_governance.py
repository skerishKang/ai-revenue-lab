"""Governance regression tests: branch mode enforcement, REJECT approval block,
enum input validation, global settings alignment, BYOK data flow, and atomic
settings validation."""

from __future__ import annotations

from app import engine
from app.domain import BranchMode, TaskStatus, Verdict
from app.store import ByokState, SecuritySettings, Store, create_task
from tests.conftest import CREATE_FORM, make_task


# --- Defect 1: BranchMode enforcement -----------------------------------


def test_auto_approval_creates_branch_and_commit(store, models):
    task = make_task(store, branch_mode=BranchMode.AUTO)
    engine.run_task(task, models)
    engine.approve_task(task, "검토자 김")
    assert task.status == TaskStatus.COMPLETED
    assert task.branch_name == f"feat/demo-{task.id}"
    assert task.commit_sha is not None and task.commit_sha.startswith("demo-")


def test_manual_approval_records_but_no_branch_or_commit(store, models):
    task = make_task(store, branch_mode=BranchMode.MANUAL)
    engine.run_task(task, models)
    engine.approve_task(task, "검토자 김")
    assert task.status == TaskStatus.COMPLETED
    assert task.approver == "검토자 김"
    assert task.completed_at is not None
    assert task.branch_name is None
    assert task.commit_sha is None


def test_manual_approval_http_shows_manual_pending(client):
    form = dict(CREATE_FORM)
    form["branch_mode"] = "manual"
    resp = client.post("/tasks", data=form, follow_redirects=False)
    task_id = resp.headers["location"].split("/")[-1]
    client.post(f"/tasks/{task_id}/run")
    client.post(f"/tasks/{task_id}/approve", data={"approver": "검토자 김"})
    page = client.get(f"/tasks/{task_id}")
    assert "완료" in page.text
    assert "수동 반영 대기" in page.text
    assert f"feat/demo-{task_id}" not in page.text
    assert 'data-copy=' not in page.text  # no copy button for absent SHA/branch


# --- Defect 2: REJECT / denied-path violation blocks approval -----------


def test_reject_verdict_blocks_approval_without_side_effects(store, models):
    task = make_task(store, denied_paths=["app/"])  # forces denied violation → REJECT
    engine.run_task(task, models)
    assert task.run.verdict == Verdict.REJECT
    try:
        engine.approve_task(task, "검토자")
        assert False, "approve should have raised"
    except engine.IllegalTransition:
        pass
    assert task.status == TaskStatus.AWAITING_APPROVAL
    assert task.approver is None
    assert task.completed_at is None
    assert task.branch_name is None
    assert task.commit_sha is None


def test_caution_verdict_can_be_approved(store, models):
    task = make_task(store, allowed_paths=["app/"], denied_paths=[])  # outside → CAUTION
    engine.run_task(task, models)
    assert task.run.verdict == Verdict.CAUTION
    engine.approve_task(task, "검토자")
    assert task.status == TaskStatus.COMPLETED


def test_reject_approval_http_blocked_and_button_hidden(client):
    form = dict(CREATE_FORM)
    form["denied_paths"] = "app/"
    resp = client.post("/tasks", data=form, follow_redirects=False)
    task_id = resp.headers["location"].split("/")[-1]
    client.post(f"/tasks/{task_id}/run")

    review = client.get(f"/tasks/{task_id}")
    assert "승인 차단됨" in review.text
    assert f'action="/tasks/{task_id}/approve"' not in review.text

    approve = client.post(
        f"/tasks/{task_id}/approve", data={"approver": "공격자"}, follow_redirects=False
    )
    assert approve.status_code == 303
    assert "error=" in approve.headers["location"]
    page = client.get(f"/tasks/{task_id}")
    assert "Demo 결과 확인이 필요합니다" in page.text
    assert "공격자" not in page.text
    assert f"feat/demo-{task_id}" not in page.text


# --- Defect 3: manipulated enum inputs validated without 500 ------------


def test_invalid_external_policy_rejected(store):
    form = dict(CREATE_FORM)
    form["external_policy"] = "bogus"
    task, errors = create_task(store, form)
    assert task is None
    assert "external_policy" in errors


def test_invalid_branch_mode_rejected(store):
    form = dict(CREATE_FORM)
    form["branch_mode"] = "bogus"
    task, errors = create_task(store, form)
    assert task is None
    assert "branch_mode" in errors


def test_invalid_enum_http_rerenders_200_no_task_no_500(client, store):
    before = len(store.tasks)
    form = dict(CREATE_FORM)
    form["external_policy"] = "<script>"
    form["branch_mode"] = "evil"
    resp = client.post("/tasks", data=form)
    assert resp.status_code == 200  # form re-render, not 500/redirect
    assert "외부 전송 정책 값이 올바르지 않습니다" in resp.text
    assert "브랜치 생성 방식 값이 올바르지 않습니다" in resp.text
    assert len(store.tasks) == before  # no task created


# --- Defect 4: global governance settings alignment ---------------------


def test_blank_cost_uses_global_default(store):
    store.settings.project_cost_limit_krw = 7777.0
    form = dict(CREATE_FORM)
    form["cost_limit_krw"] = ""
    task, errors = create_task(store, form)
    assert errors == {}
    assert task.cost_limit_krw == 7777.0


def test_explicit_zero_cost_means_no_limit(store):
    store.settings.project_cost_limit_krw = 7777.0
    form = dict(CREATE_FORM)
    form["cost_limit_krw"] = "0"
    task, errors = create_task(store, form)
    assert errors == {}
    assert task.cost_limit_krw == 0.0  # explicit 0 ≠ blank default


def test_external_model_blocked_when_global_disabled(store):
    store.settings.allow_external = False
    form = dict(CREATE_FORM)
    form["worker_model_id"] = "openai-gpt"  # overseas
    form["validator_model_id"] = "anthropic-claude"  # overseas
    task, errors = create_task(store, form)
    assert task is None
    assert "worker_model_id" in errors
    assert "validator_model_id" in errors
    assert "해외 처리 모델" in errors["worker_model_id"]


def test_domestic_combo_allowed_when_global_disabled(store):
    store.settings.allow_external = False
    form = dict(CREATE_FORM)
    form["worker_model_id"] = "domestic-open"
    form["validator_model_id"] = "domestic-open"
    task, errors = create_task(store, form)
    assert errors == {}
    assert task is not None


def test_external_model_blocked_http(client, store):
    store.settings.allow_external = False
    form = dict(CREATE_FORM)
    form["worker_model_id"] = "openai-gpt"
    resp = client.post("/tasks", data=form)
    assert resp.status_code == 200
    assert "해외 처리 모델" in resp.text


def test_block_push_without_approval_cannot_be_disabled(client, store):
    # POST without the flag (or with off) must not weaken the mandatory gate.
    client.post("/settings", data={"domestic_first": "on"})
    assert store.settings.block_push_without_approval is True


# --- Defect 5: BYOK data flow and state handling ------------------------


def test_byok_register_then_blank_save_preserves(client, store):
    client.post("/settings", data={"apikey_byok-model": "some-key-value"})
    assert store.settings.byok["byok-model"].registered is True
    # Blank key input on a later save preserves the existing registered state.
    client.post("/settings", data={"domestic_first": "on"})
    assert store.settings.byok["byok-model"].registered is True


def test_byok_explicit_unregister(client, store):
    client.post("/settings", data={"apikey_byok-model": "some-key-value"})
    assert store.settings.byok["byok-model"].registered is True
    client.post("/settings", data={"apikey_unregister_byok-model": "on"})
    assert store.settings.byok["byok-model"].registered is False


def test_raw_api_key_not_persisted_or_echoed(client, store):
    secret = "kap-governance-secret-XYZ"
    resp = client.post("/settings", data={"apikey_byok-model": secret})
    # Not persisted anywhere in the store (ByokState only has `registered`).
    assert set(ByokState.model_fields.keys()) == {"registered"}
    assert secret not in store.settings.model_dump_json()
    # Not echoed on the settings page.
    page = client.get("/settings")
    assert secret not in page.text
    assert "등록됨" in page.text


# --- Defect 6: atomic settings validation -------------------------------


def test_invalid_settings_cost_is_atomic_and_rerendered(client, store):
    original_external = store.settings.allow_external  # default True
    original_limit = store.settings.project_cost_limit_krw
    # Submit a change to allow_external (off) together with an invalid cost.
    resp = client.post(
        "/settings",
        data={"project_cost_limit_krw": "not-a-number"},  # allow_external omitted
    )
    assert resp.status_code == 200  # re-render, not redirect
    assert "saved=1" not in str(resp.url)
    assert "저장되지 않았습니다" in resp.text
    # No partial change: both settings remain at their original values.
    assert store.settings.allow_external == original_external
    assert store.settings.project_cost_limit_krw == original_limit


def test_negative_and_nonfinite_settings_cost_rejected(client, store):
    original = store.settings.project_cost_limit_krw
    for bad in ["-100", "nan", "inf"]:
        resp = client.post("/settings", data={"project_cost_limit_krw": bad})
        assert resp.status_code == 200
        assert "저장되지 않았습니다" in resp.text
        assert store.settings.project_cost_limit_krw == original


def test_valid_settings_save_succeeds(client, store):
    resp = client.post(
        "/settings",
        data={"domestic_first": "on", "project_cost_limit_krw": "12345"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "saved=1" in resp.headers["location"]
    assert store.settings.project_cost_limit_krw == 12345.0


# --- Cost limit guidance text matches actual behavior -------------------


def test_new_task_page_renders_cost_guidance(client):
    resp = client.get("/tasks/new")
    assert resp.status_code == 200
    # Blank input applies the project default cost limit.
    assert "프로젝트 기본 비용 한도" in resp.text
    # Explicit 0 means no limit.
    assert "제한 없음" in resp.text
    # The old inaccurate phrasing ("0 또는 비워두면 제한 없음") must be gone.
    assert "0 또는 비워두면 제한 없음" not in resp.text
