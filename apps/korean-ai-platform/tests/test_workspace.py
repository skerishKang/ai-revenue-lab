"""Tests for the user workspace demo (Issue #105)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import mock_data
from app.demo_templates import TEMPLATES, TEMPLATES_BY_ID
from app.domain import BranchMode, ExternalPolicy, Task, TaskStatus
from app.factory import create_app
from app.store import Store
from app.user_helpers import (
    USER_ACTION_LABELS,
    USER_STATUS_LABELS,
    user_action_label,
    user_status_label,
)
from tests.conftest import CREATE_FORM, make_task


@pytest.fixture()
def store():
    return Store(seed=False)


@pytest.fixture()
def app(store):
    return create_app(store=store)


@pytest.fixture()
def client(app):
    return TestClient(app)


def _create_task(client, form=None):
    form = form or CREATE_FORM
    resp = client.post("/tasks", data=form, follow_redirects=False)
    assert resp.status_code == 303
    return resp.headers["location"].split("/")[-1]


class TestWorkspaceHome:
    def test_workspace_renders(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "무엇을 AI에게 맡기고 싶으세요?" in resp.text

    def test_workspace_has_natural_language_input(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "ws-textarea" in resp.text
        assert "시작하기" in resp.text

    def test_workspace_has_six_templates(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        for tpl in TEMPLATES:
            assert tpl.title in resp.text
            assert f"/tasks/new?template={tpl.id}" in resp.text

    def test_workspace_no_admin_heading_as_main(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "AI Operations Overview" not in resp.text

    def test_workspace_has_user_admin_nav(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "사용자 화면" in resp.text
        assert "운영자 화면" in resp.text

    def test_workspace_recent_tasks_no_model_id(self, client, store):
        make_task(store, status=TaskStatus.READY)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "openai-gpt" not in resp.text
        assert "anthropic-claude" not in resp.text

    def test_workspace_recent_tasks_no_commit_sha(self, client, store):
        task = make_task(store, status=TaskStatus.COMPLETED)
        task.commit_sha = "demo-abc123def456"
        task.branch_name = "feat/demo-test"
        resp = client.get("/")
        assert resp.status_code == 200
        assert "demo-abc123def456" not in resp.text


class TestAdminDashboard:
    def test_admin_renders_dashboard(self, client):
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "운영자 Console" in resp.text
        assert "작업·검증·승인까지 관리합니다" in resp.text

    def test_admin_has_demo_notice(self, client):
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "실제 권한 분리가 없는 Demo" in resp.text

    def test_admin_has_metrics(self, client):
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "이번 달 예상 AI 비용" in resp.text
        assert "승인 대기" in resp.text


class TestTemplatePrefill:
    def test_template_prefill_website(self, client):
        resp = client.get("/tasks/new?template=website")
        assert resp.status_code == 200
        tpl = TEMPLATES_BY_ID["website"]
        assert tpl.suggested_task_title in resp.text
        assert tpl.suggested_instruction in resp.text

    def test_all_six_templates_prefill(self, client):
        for tpl in TEMPLATES:
            resp = client.get(f"/tasks/new?template={tpl.id}")
            assert resp.status_code == 200
            assert tpl.suggested_task_title in resp.text

    def test_invalid_template_ignored(self, client):
        resp = client.get("/tasks/new?template=nonexistent")
        assert resp.status_code == 200
        assert "템플릿:" not in resp.text

    def test_template_shows_banner(self, client):
        resp = client.get("/tasks/new?template=code")
        assert resp.status_code == 200
        assert "템플릿: 코드 수정하기" in resp.text

    def test_template_prefill_project(self, client):
        resp = client.get("/tasks/new?template=data")
        assert resp.status_code == 200
        assert "data-pipeline" in resp.text


class TestUserStatusMapping:
    def test_all_statuses_have_labels(self):
        for status in TaskStatus:
            assert status.value in USER_STATUS_LABELS
            assert status.value in USER_ACTION_LABELS

    def test_status_labels_are_plain_language(self):
        assert user_status_label("ready") == "시작할 준비가 됐습니다"
        assert user_status_label("running") == "AI가 작업하고 있습니다"
        assert user_status_label("awaiting_approval") == "확인이 필요합니다"
        assert user_status_label("rework") == "요청한 내용을 다시 작업 중입니다"
        assert user_status_label("completed") == "작업이 완료됐습니다"
        assert user_status_label("rejected") == "작업이 중단됐습니다"

    def test_action_labels(self):
        assert user_action_label("ready") == "작업 시작"
        assert user_action_label("completed") == "결과 열기"
        assert user_action_label("rejected") == "중단 사유 보기"

    def test_unknown_status_fallback(self):
        assert user_status_label("unknown") == "unknown"
        assert user_action_label("unknown") == "자세히 보기"


class TestTaskDetailUserSummary:
    def test_task_detail_has_user_summary(self, client):
        task_id = _create_task(client)
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert "ws-summary" in resp.text
        assert "시작할 준비가 됐습니다" in resp.text

    def test_task_detail_technical_in_disclosure(self, client):
        task_id = _create_task(client)
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert "ws-disclosure" in resp.text
        assert "기술 세부정보 보기" in resp.text

    def test_task_detail_awaiting_approval_summary(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert "결과가 준비됐습니다" in resp.text

    def test_task_detail_completed_summary(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/approve", data={"approver": "검토자"})
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert "검토가 완료됐습니다" in resp.text

    def test_task_detail_rejected_summary(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/reject", data={"reason": "부적절"})
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert "작업이 중단됐습니다" in resp.text

    def test_risk_warnings_visible_outside_disclosure(self, client, store):
        task = make_task(store, status=TaskStatus.READY)
        from app import engine
        engine.run_task(task, store.models)
        task.run.path_violations = ["허용 범위 밖 파일 변경"]
        resp = client.get(f"/tasks/{task.id}")
        assert resp.status_code == 200
        assert "허용되지 않은 파일이 변경됐습니다" in resp.text

    def test_no_internal_enum_exposed(self, client):
        task_id = _create_task(client)
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert "AWAITING_APPROVAL" not in resp.text
        assert "TaskStatus" not in resp.text


class TestSvgAssets:
    def test_all_six_svg_assets_return_200(self, client):
        for tpl in TEMPLATES:
            resp = client.get(tpl.image_path)
            assert resp.status_code == 200, f"SVG {tpl.image_path} returned {resp.status_code}"
            assert "svg" in resp.headers.get("content-type", "")

    def test_template_images_are_local_paths(self):
        for tpl in TEMPLATES:
            assert tpl.image_path.startswith("/static/images/templates/")
            assert not tpl.image_path.startswith("http")

    def test_no_remote_image_urls_in_templates(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert 'src="http://' not in resp.text
        assert 'src="https://' not in resp.text


class TestExistingFlowsPreserved:
    def test_create_task_still_works(self, client):
        task_id = _create_task(client)
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200

    def test_run_approve_flow_still_works(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        resp = client.get(f"/tasks/{task_id}")
        assert "결과가 준비됐습니다" in resp.text
        client.post(f"/tasks/{task_id}/approve", data={"approver": "검토자"})
        resp = client.get(f"/tasks/{task_id}")
        assert "검토가 완료됐습니다" in resp.text

    def test_rework_flow_still_works(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/rework", data={"reason": "수정 필요"})
        resp = client.get(f"/tasks/{task_id}")
        assert "다시 작업하고 있습니다" in resp.text

    def test_reject_flow_still_works(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/reject", data={"reason": "거절"})
        resp = client.get(f"/tasks/{task_id}")
        assert "작업이 중단됐습니다" in resp.text

    def test_settings_page_still_works(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert "모델·보안 설정" in resp.text or "설정" in resp.text


class TestMobileNavigation:
    def test_nav_links_present(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert 'href="/"' in resp.text
        assert 'href="/admin"' in resp.text
        assert 'href="/tasks/new"' in resp.text
        assert 'href="/settings"' in resp.text
