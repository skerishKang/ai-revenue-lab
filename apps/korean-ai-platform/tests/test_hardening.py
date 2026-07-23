"""Hardening regression tests: path normalization, cost validation, approval
gate idempotency, output escaping, API-key non-storage, and honest demo labels.
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse, parse_qs

import pytest

from app import engine
from app.domain import (
    ChangedFile,
    TaskStatus,
    Verdict,
    evaluate_path_policy,
    normalize_path,
    path_matches,
)
from app.store import SecuritySettings, Store, create_task, parse_cost_limit
from tests.conftest import CREATE_FORM, make_task


# --- Path normalization -------------------------------------------------


def test_normalize_backslash_and_drive():
    assert normalize_path("app\\services\\x.py") == "app/services/x.py"
    assert normalize_path("C:\\app\\x.py") == "app/x.py"
    assert normalize_path("C:") == ""


def test_normalize_traversal_clamped_at_root():
    assert normalize_path("../app/x.py") == "app/x.py"
    assert normalize_path("../../app/x.py") == "app/x.py"
    assert normalize_path("..") == ""
    assert normalize_path("../") == ""


def test_normalize_dots_and_duplicate_slashes():
    assert normalize_path("./app//x.py") == "app/x.py"
    assert normalize_path("app/./sub/../x.py") == "app/x.py"
    assert normalize_path("/app/") == "app"
    assert normalize_path("app//") == "app"


def test_normalize_strips_trailing_wildcard():
    assert normalize_path("apps/example/**") == "apps/example"
    assert normalize_path("apps/example/*") == "apps/example"


def test_match_similar_prefix_not_bypassed():
    assert path_matches("apps/example/", "apps/example/x.py")
    assert not path_matches("apps/example/", "apps/example-evil/x.py")
    assert not path_matches("apps/example", "apps/example-evil/x.py")


def test_match_traversal_and_backslash_inputs():
    # A denied pattern using traversal/backslash still resolves to the real dir.
    assert path_matches("../../app/", "app/services/x.py")
    assert path_matches("app\\", "app/services/x.py")
    assert path_matches("../app/", "app/services/x.py")


def _files(*paths):
    return [
        ChangedFile(path=p, additions=1, deletions=0, language="python", diff="")
        for p in paths
    ]


def test_denied_wins_over_allowed():
    violations = evaluate_path_policy(
        _files("app/secret.py"), ["app/"], ["app/secret.py"]
    )
    assert any("수정 금지 경로" in v for v in violations)


def test_denied_nested_under_allowed_flagged():
    violations = evaluate_path_policy(
        _files("app/config.py"), ["app/"], ["app/config.py"]
    )
    assert any("수정 금지 경로" in v for v in violations)


def test_changed_file_outside_allowed_flagged():
    violations = evaluate_path_policy(_files("docs/x.md"), ["app/", "tests/"], [])
    assert any("docs/x.md" in v for v in violations)


# --- Cost limit validation ----------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", 0.0),
        ("   ", 0.0),
        ("0", 0.0),
        ("5000", 5000.0),
        ("4900.5", 4900.5),
        ("1e9", 1e9),
    ],
)
def test_parse_cost_limit_accepts(raw, expected):
    value, error = parse_cost_limit(raw)
    assert error is None
    assert value == expected


@pytest.mark.parametrize(
    "raw",
    ["-1", "-0.01", "abc", "12abc", "nan", "NaN", "inf", "Infinity", "-inf"],
)
def test_parse_cost_limit_rejects(raw):
    value, error = parse_cost_limit(raw)
    assert value is None
    assert error is not None


def test_create_task_rejects_negative_cost(store):
    form = dict(CREATE_FORM)
    form["cost_limit_krw"] = "-500"
    task, errors = create_task(store, form)
    assert task is None
    assert "cost_limit_krw" in errors


def test_create_task_rejects_nan_and_inf(store):
    for bad in ["nan", "inf"]:
        form = dict(CREATE_FORM)
        form["cost_limit_krw"] = bad
        task, errors = create_task(store, form)
        assert task is None, bad
        assert "cost_limit_krw" in errors


def test_over_budget_boundary(store, models):
    task = make_task(store)
    engine.run_task(task, models)
    total = task.run.cost_total_krw

    at_limit = make_task(store, cost_limit_krw=total)
    engine.run_task(at_limit, models)
    assert at_limit.run.over_budget is False  # equal to limit is within budget

    under = make_task(store, cost_limit_krw=round(total - 0.01, 2))
    engine.run_task(under, models)
    assert under.run.over_budget is True


# --- Approval gate idempotency ------------------------------------------


def test_duplicate_approve_has_no_side_effect(store, models):
    task = make_task(store)
    engine.run_task(task, models)
    engine.approve_task(task, "검토자 김")
    first_sha = task.commit_sha
    first_completed_at = task.completed_at
    with pytest.raises(engine.IllegalTransition):
        engine.approve_task(task, "다른 사람")
    assert task.status == TaskStatus.COMPLETED
    assert task.commit_sha == first_sha
    assert task.completed_at == first_completed_at
    assert task.approver == "검토자 김"


def test_approve_completed_and_rejected_rejected(store, models):
    completed = make_task(store)
    engine.run_task(completed, models)
    engine.approve_task(completed, "x")
    with pytest.raises(engine.IllegalTransition):
        engine.approve_task(completed, "y")

    rejected = make_task(store)
    engine.run_task(rejected, models)
    engine.reject_task(rejected, "no")
    with pytest.raises(engine.IllegalTransition):
        engine.approve_task(rejected, "y")
    assert rejected.commit_sha is None


def test_run_number_increments_per_rework(store, models):
    task = make_task(store)
    engine.run_task(task, models)
    assert task.run.run_number == 1
    engine.request_rework(task, "1차 수정", models)
    engine.run_task(task, models)
    assert task.run.run_number == 2
    engine.request_rework(task, "2차 수정", models)
    engine.run_task(task, models)
    assert task.run.run_number == 3
    assert task.rework_count == 2


def test_duplicate_approve_over_http(client):
    form = dict(CREATE_FORM)
    resp = client.post("/tasks", data=form, follow_redirects=False)
    task_id = resp.headers["location"].split("/")[-1]
    client.post(f"/tasks/{task_id}/run")
    client.post(f"/tasks/{task_id}/approve", data={"approver": "검토자 김"})

    second = client.post(
        f"/tasks/{task_id}/approve", data={"approver": "공격자"},
        follow_redirects=False,
    )
    assert second.status_code == 303
    page = client.get(f"/tasks/{task_id}")
    assert "검토자 김" in page.text
    assert "공격자" not in page.text


def test_error_redirect_location_is_ascii(client):
    resp = client.post("/tasks", data=CREATE_FORM, follow_redirects=False)
    task_id = resp.headers["location"].split("/")[-1]
    # Approve a task that is still 'ready' -> IllegalTransition -> error redirect.
    err = client.post(
        f"/tasks/{task_id}/approve", data={"approver": "x"}, follow_redirects=False
    )
    location = err.headers["location"]
    assert location.isascii()
    query = parse_qs(urlparse(location).query)
    assert "상태에서는 승인할 수 없습니다" in unquote(query["error"][0])


def test_unknown_task_post_redirects_home_and_isolates(client):
    resp = client.post("/tasks/does-not-exist/approve", data={"approver": "x"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


# --- Output escaping -----------------------------------------------------


def test_instruction_html_is_escaped(client):
    form = dict(CREATE_FORM)
    form["instruction"] = "<script>alert(1)</script> 주문 로직"
    resp = client.post("/tasks", data=form, follow_redirects=False)
    task_id = resp.headers["location"].split("/")[-1]
    page = client.get(f"/tasks/{task_id}")
    assert "<script>alert(1)</script>" not in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text


def test_rework_reason_html_is_escaped(client):
    resp = client.post("/tasks", data=CREATE_FORM, follow_redirects=False)
    task_id = resp.headers["location"].split("/")[-1]
    client.post(f"/tasks/{task_id}/run")
    client.post(
        f"/tasks/{task_id}/rework",
        data={"reason": "<img src=x onerror=alert(1)>"},
    )
    page = client.get(f"/tasks/{task_id}")
    assert "<img src=x onerror=alert(1)>" not in page.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in page.text


def test_jinja_env_autoescape_enabled(app):
    assert app.state.jinja_env.autoescape is True


# --- API key non-storage -------------------------------------------------


def test_api_key_not_stored_anywhere(client, app):
    secret = "kap-fake-key-do-not-store-777"
    client.post(
        "/settings",
        data={"apikey_byok-model": secret, "domestic_first": "on"},
        follow_redirects=False,
    )
    page = client.get("/settings")
    assert secret not in page.text
    assert "등록됨" in page.text

    store = app.state.store
    state = store.settings.byok["byok-model"]
    assert state.registered is True
    assert set(SecuritySettings.model_fields.keys()).isdisjoint(
        {"api_key", "apikey", "byok_key"}
    )
    assert set(type(state).model_fields.keys()) == {"registered"}


# --- Honest demo labeling ------------------------------------------------


def test_awaiting_task_shows_no_branch_or_commit(client):
    resp = client.post("/tasks", data=CREATE_FORM, follow_redirects=False)
    task_id = resp.headers["location"].split("/")[-1]
    client.post(f"/tasks/{task_id}/run")
    page = client.get(f"/tasks/{task_id}")
    assert f"feat/demo-{task_id}" not in page.text
    assert "브랜치에 반영되지 않습니다" in page.text


def test_completed_task_labels_demo_values(client):
    resp = client.post("/tasks", data=CREATE_FORM, follow_redirects=False)
    task_id = resp.headers["location"].split("/")[-1]
    client.post(f"/tasks/{task_id}/run")
    client.post(f"/tasks/{task_id}/approve", data={"approver": "검토자 김"})
    page = client.get(f"/tasks/{task_id}")
    assert f"feat/demo-{task_id}" in page.text
    assert "demo-" in page.text
    assert "Demo" in page.text
