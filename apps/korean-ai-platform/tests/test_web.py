from tests.conftest import CREATE_FORM


def _create_task_http(client, form=None):
    form = form or CREATE_FORM
    resp = client.post("/tasks", data=form, follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]
    return location.split("/")[-1]


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_dashboard_renders_core_message(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    body = resp.text
    assert "작업·검증·승인까지 관리합니다" in body
    assert "새 AI 작업 시작" in body
    assert "이번 달 예상 AI 비용" in body


def test_new_task_form_lists_demo_models(client):
    resp = client.get("/tasks/new")
    assert resp.status_code == 200
    assert "작업 모델" in resp.text
    assert "검증 모델" in resp.text
    assert "Demo" in resp.text


def test_create_task_shows_ready_state(client):
    task_id = _create_task_http(client)
    resp = client.get(f"/tasks/{task_id}")
    assert resp.status_code == 200
    assert "실행 대기" in resp.text
    assert "실행 시작" in resp.text


def test_full_flow_run_review_approve(client):
    task_id = _create_task_http(client)

    run_resp = client.post(f"/tasks/{task_id}/run", follow_redirects=False)
    assert run_resp.status_code == 303
    assert "ran=1" in run_resp.headers["location"]

    review = client.get(f"/tasks/{task_id}")
    assert "승인 대기" in review.text
    assert "변경 파일" in review.text
    assert "검증자 판단" in review.text
    # Approval gate: no branch/commit before approval.
    assert f"feat/demo-{task_id}" not in review.text

    approve = client.post(
        f"/tasks/{task_id}/approve", data={"approver": "검토자 김"},
        follow_redirects=False,
    )
    assert approve.status_code == 303

    done = client.get(f"/tasks/{task_id}")
    assert "완료" in done.text
    assert f"feat/demo-{task_id}" in done.text
    assert "demo-" in done.text


def test_rework_flow_over_http(client):
    task_id = _create_task_http(client)
    client.post(f"/tasks/{task_id}/run")

    rework = client.post(
        f"/tasks/{task_id}/rework", data={"reason": "백오프를 적용해 주세요."},
        follow_redirects=False,
    )
    assert rework.status_code == 303
    page = client.get(f"/tasks/{task_id}")
    assert "재작업" in page.text
    assert "재실행" in page.text

    client.post(f"/tasks/{task_id}/run")
    page2 = client.get(f"/tasks/{task_id}")
    assert "승인 대기" in page2.text


def test_rework_without_reason_is_rejected(client):
    task_id = _create_task_http(client)
    client.post(f"/tasks/{task_id}/run")
    client.post(f"/tasks/{task_id}/rework", data={"reason": ""})
    page = client.get(f"/tasks/{task_id}")
    # Still awaiting approval because empty reason is refused.
    assert "승인 대기" in page.text


def test_reject_flow_over_http(client):
    task_id = _create_task_http(client)
    client.post(f"/tasks/{task_id}/run")
    client.post(f"/tasks/{task_id}/reject", data={"reason": "범위 초과"})
    page = client.get(f"/tasks/{task_id}")
    assert "거절" in page.text
    assert f"feat/demo-{task_id}" not in page.text


def test_path_violation_shown_in_review(client):
    form = dict(CREATE_FORM)
    form["denied_paths"] = "app/"
    task_id = _create_task_http(client, form)
    client.post(f"/tasks/{task_id}/run")
    page = client.get(f"/tasks/{task_id}")
    assert "허용 범위 위반" in page.text


def test_settings_save_does_not_echo_api_key(client):
    secret = "fake-api-key-do-not-store-12345"
    resp = client.post(
        "/settings",
        data={"apikey_byok-model": secret, "domestic_first": "on"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = client.get("/settings")
    assert secret not in page.text
    assert "등록됨" in page.text


def test_not_found_task(client):
    resp = client.get("/tasks/does-not-exist")
    assert resp.status_code == 404
    assert "찾을 수 없습니다" in resp.text


def test_create_task_validation_errors_rendered(client):
    form = dict(CREATE_FORM)
    form["title"] = ""
    resp = client.post("/tasks", data=form)
    assert resp.status_code == 200
    assert "작업 제목을 입력하세요" in resp.text
