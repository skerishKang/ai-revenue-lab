import pytest

from app import engine
from app.domain import TaskStatus, Verdict
from tests.conftest import make_task


def test_run_task_moves_to_awaiting_approval(store, models):
    task = make_task(store)
    engine.run_task(task, models)
    assert task.status == TaskStatus.AWAITING_APPROVAL
    assert task.run is not None
    assert task.run.run_number == 1
    assert len(task.run.steps) == 6
    assert task.run.changed_files
    assert task.run.tests is not None
    assert task.run.cost_total_krw > 0


def test_no_commit_before_approval(store, models):
    task = make_task(store)
    engine.run_task(task, models)
    assert task.commit_sha is None
    assert task.branch_name is None
    assert task.status != TaskStatus.COMPLETED


def test_approve_creates_demo_branch_and_commit(store, models):
    task = make_task(store)
    engine.run_task(task, models)
    engine.approve_task(task, approver="검토자 김")
    assert task.status == TaskStatus.COMPLETED
    assert task.commit_sha is not None
    assert task.commit_sha.startswith("demo-")
    assert task.branch_name == f"feat/demo-{task.id}"
    assert task.approver == "검토자 김"
    assert task.completed_at is not None


def test_approve_requires_awaiting_approval(store, models):
    task = make_task(store)
    with pytest.raises(engine.IllegalTransition):
        engine.approve_task(task, "검토자")


def test_rework_flow_returns_to_awaiting_with_new_run(store, models):
    task = make_task(store)
    engine.run_task(task, models)
    engine.request_rework(task, "백오프 정책을 적용해 주세요.", models)
    assert task.status == TaskStatus.REWORK
    assert task.rework_count == 1
    assert task.rework_reasons == ["백오프 정책을 적용해 주세요."]

    engine.run_task(task, models)
    assert task.status == TaskStatus.AWAITING_APPROVAL
    assert task.run.run_number == 2
    assert "백오프" in task.run.plan_text


def test_rework_requires_reason(store, models):
    task = make_task(store)
    engine.run_task(task, models)
    with pytest.raises(ValueError):
        engine.request_rework(task, "   ", models)


def test_reject_is_terminal(store, models):
    task = make_task(store)
    engine.run_task(task, models)
    engine.reject_task(task, "범위 초과")
    assert task.status == TaskStatus.REJECTED
    assert task.rejected_reason == "범위 초과"
    assert task.commit_sha is None


def test_denied_path_violation_sets_reject_verdict(store, models):
    task = make_task(store, denied_paths=["app/"])
    engine.run_task(task, models)
    assert task.run.verdict == Verdict.REJECT
    assert task.run.path_violations
    assert any("수정 금지 경로" in v for v in task.run.path_violations)


def test_outside_allowed_sets_caution_verdict(store, models):
    task = make_task(store, allowed_paths=["app/"], denied_paths=[])
    engine.run_task(task, models)
    assert task.run.verdict == Verdict.CAUTION
    assert any("허용 경로" in v for v in task.run.path_violations)


def test_clean_policy_sets_approve_verdict(store, models):
    task = make_task(store, allowed_paths=["app/", "tests/"], denied_paths=[])
    engine.run_task(task, models)
    assert task.run.verdict == Verdict.APPROVE
    assert task.run.path_violations == []


def test_over_budget_flag(store, models):
    task = make_task(store, cost_limit_krw=1.0)
    engine.run_task(task, models)
    assert task.run.over_budget is True


def test_within_budget_not_flagged(store, models):
    task = make_task(store, cost_limit_krw=50000.0)
    engine.run_task(task, models)
    assert task.run.over_budget is False


def test_restrict_external_with_overseas_model_adds_security_note(store, models):
    task = make_task(store, external_policy="restrict", worker_model_id="openai-gpt")
    engine.run_task(task, models)
    assert task.run.security_notes
    assert task.run.verdict == Verdict.CAUTION


def test_domestic_only_data_regions(store, models):
    task = make_task(
        store, worker_model_id="domestic-open", validator_model_id="domestic-open"
    )
    regions = engine.data_regions(task, models)
    assert regions["domestic_only"] is True
    assert regions["overseas"] is False


def test_run_from_completed_is_illegal(store, models):
    task = make_task(store)
    engine.run_task(task, models)
    engine.approve_task(task, "검토자")
    with pytest.raises(engine.IllegalTransition):
        engine.run_task(task, models)
