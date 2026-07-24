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
    generate_title_from_instruction,
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
        assert user_status_label("ready") == "Demo 실행을 시작할 수 있습니다"
        assert user_status_label("running") == "Demo 실행 중입니다"
        assert user_status_label("awaiting_approval") == "Demo 결과 확인이 필요합니다"
        assert user_status_label("rework") == "Demo 재작업 중입니다"
        assert user_status_label("completed") == "Demo 작업이 완료됐습니다"
        assert user_status_label("rejected") == "Demo 작업이 중단됐습니다"

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
        assert "Demo 실행을 시작할 수 있습니다" in resp.text

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
        assert "Demo 결과가 준비됐습니다" in resp.text

    def test_task_detail_completed_summary(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/approve", data={"approver": "검토자"})
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert "Demo 검토와 승인 절차가 완료됐습니다" in resp.text

    def test_task_detail_rejected_summary(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/reject", data={"reason": "부적절"})
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert "Demo 작업이 중단됐습니다" in resp.text

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
        assert "Demo 결과가 준비됐습니다" in resp.text
        client.post(f"/tasks/{task_id}/approve", data={"approver": "검토자"})
        resp = client.get(f"/tasks/{task_id}")
        assert "Demo 검토와 승인 절차가 완료됐습니다" in resp.text

    def test_rework_flow_still_works(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/rework", data={"reason": "수정 필요"})
        resp = client.get(f"/tasks/{task_id}")
        assert "Demo 재작업 중입니다" in resp.text

    def test_reject_flow_still_works(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/reject", data={"reason": "거절"})
        resp = client.get(f"/tasks/{task_id}")
        assert "Demo 작업이 중단됐습니다" in resp.text

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


class TestPrimaryCTAInputPreservation:
    def test_instruction_prefill(self, client):
        resp = client.get("/tasks/new?instruction=주문 오류를 수정해 주세요")
        assert resp.status_code == 200
        assert "주문 오류를 수정해 주세요" in resp.text

    def test_title_auto_generated_from_instruction(self, client):
        resp = client.get("/tasks/new?instruction=주문 페이지에 재고 부족 경고 메시지를 추가해 주세요")
        assert resp.status_code == 200
        assert "주문 페이지에 재고 부족 경고 메시지를 추가해 주세요" in resp.text

    def test_valid_project_query_selected(self, client):
        resp = client.get("/tasks/new?project_id=commerce-backend")
        assert resp.status_code == 200
        assert 'value="commerce-backend"' in resp.text
        assert "selected" in resp.text

    def test_invalid_project_query_ignored(self, client):
        resp = client.get("/tasks/new?project_id=nonexistent-project")
        assert resp.status_code == 200
        assert 'value="nonexistent-project"' not in resp.text

    def test_template_plus_explicit_instruction_priority(self, client):
        resp = client.get("/tasks/new?template=code&instruction=사용자 지정 지시")
        assert resp.status_code == 200
        assert "사용자 지정 지시" in resp.text
        tpl = TEMPLATES_BY_ID["code"]
        assert tpl.suggested_instruction not in resp.text

    def test_template_plus_valid_project_priority(self, client):
        resp = client.get("/tasks/new?template=website&project_id=commerce-backend")
        assert resp.status_code == 200
        assert 'value="commerce-backend"' in resp.text

    def test_blank_query_does_not_clear_template(self, client):
        resp = client.get("/tasks/new?template=code&instruction=")
        assert resp.status_code == 200
        tpl = TEMPLATES_BY_ID["code"]
        assert tpl.suggested_instruction in resp.text

    def test_script_tag_escaped(self, client):
        resp = client.get("/tasks/new?instruction=<script>alert(1)</script>")
        assert resp.status_code == 200
        assert "<script>alert(1)</script>" not in resp.text
        assert "&lt;script&gt;" in resp.text


class TestDemoTruthfulness:
    def test_no_ai_working_message_on_home(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "AI가 작업하고 있습니다" not in resp.text

    def test_no_ai_analyzing_message_on_detail(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert "AI가 요청을 분석하고" not in resp.text

    def test_demo_running_label_present(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert "Demo 결과 확인이 필요합니다" in resp.text

    def test_no_file_test_counts_in_recent_summary(self, client, store):
        task = make_task(store, status=TaskStatus.READY)
        from app import engine
        engine.run_task(task, store.models)
        task.status = TaskStatus.COMPLETED
        resp = client.get("/")
        assert resp.status_code == 200
        assert "파일 3개 변경" not in resp.text
        assert "테스트 8개 통과" not in resp.text


class TestDisclosureStructure:
    def test_completed_commit_sha_inside_details(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/approve", data={"approver": "검토자"})
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        body = resp.text
        details_start = body.index('<details class="ws-disclosure">')
        details_end = body.rindex("</details>")
        details_content = body[details_start:details_end]
        assert "데모 커밋 SHA" in details_content

    def test_completed_branch_inside_details(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        client.post(f"/tasks/{task_id}/approve", data={"approver": "검토자"})
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        body = resp.text
        details_start = body.index('<details class="ws-disclosure">')
        details_end = body.rindex("</details>")
        details_content = body[details_start:details_end]
        assert "데모 브랜치" in details_content

    def test_verdict_strip_inside_details(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        body = resp.text
        details_start = body.index('<details class="ws-disclosure">')
        details_end = body.rindex("</details>")
        details_content = body[details_start:details_end]
        assert "검증자 판단" in details_content

    def test_risk_warnings_outside_details(self, client, store):
        task = make_task(store, status=TaskStatus.READY)
        from app import engine
        engine.run_task(task, store.models)
        task.run.path_violations = ["허용 범위 밖 파일 변경"]
        resp = client.get(f"/tasks/{task.id}")
        assert resp.status_code == 200
        body = resp.text
        risk_pos = body.index("허용되지 않은 파일이 변경됐습니다")
        if '<details class="ws-disclosure">' in body:
            details_start = body.index('<details class="ws-disclosure">')
            assert risk_pos < details_start

    def test_approve_action_outside_details(self, client):
        task_id = _create_task(client)
        client.post(f"/tasks/{task_id}/run")
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        body = resp.text
        action_pos = body.index("결과 확인")
        details_start = body.index('<details class="ws-disclosure">')
        assert action_pos < details_start

    def test_header_badge_uses_user_label(self, client):
        task_id = _create_task(client)
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert "Demo 실행을 시작할 수 있습니다" in resp.text


class TestUserShell:
    def test_home_no_persistence_label(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "로컬 SQLite 저장" not in resp.text
        assert "단일 프로세스" not in resp.text

    def test_home_no_settings_nav(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "모델·보안 설정" not in resp.text

    def test_home_has_workspace_brand(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "AI 작업 Workspace" in resp.text

    def test_admin_has_persistence_label(self, client):
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "로컬 SQLite 저장" in resp.text or "인메모리" in resp.text

    def test_admin_has_settings_nav(self, client):
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "모델·보안 설정" in resp.text

    def test_settings_has_settings_nav(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert "모델·보안 설정" in resp.text

    def test_task_new_crumb_user_workspace(self, client):
        resp = client.get("/tasks/new")
        assert resp.status_code == 200
        assert "사용자 Workspace" in resp.text

    def test_user_admin_toggle_links_present(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "사용자 화면" in resp.text
        assert "운영자 화면" in resp.text


class TestTitleGeneration:
    def test_empty_instruction_returns_empty(self):
        assert generate_title_from_instruction("") == ""
        assert generate_title_from_instruction("   ") == ""

    def test_short_instruction_unchanged(self):
        assert generate_title_from_instruction("주문 오류 수정") == "주문 오류 수정"

    def test_whitespace_normalized(self):
        assert generate_title_from_instruction("주문   오류를    수정해   주세요") == "주문 오류를 수정해 주세요"

    def test_long_instruction_truncated(self):
        long_text = "매우 긴 사용자 요청입니다. 이 텍스트는 40자를 초과하므로 잘려야 합니다."
        result = generate_title_from_instruction(long_text)
        assert len(result) == 41
        assert result.endswith("…")

    def test_exactly_40_chars_not_truncated(self):
        text = "가" * 40
        assert generate_title_from_instruction(text) == text

    def test_41_chars_truncated(self):
        text = "가" * 41
        result = generate_title_from_instruction(text)
        assert len(result) == 41
        assert result.endswith("…")
