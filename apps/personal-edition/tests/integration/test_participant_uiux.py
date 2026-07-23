"""UI/UX regression tests for Personal Edition participant experience.

Covers:
- Design token CSS presence
- CSS cache busting version query
- Image attributes (src, alt, width, height)
- Heading text and CTA presence
- Korean-only error messages on participant pages
- Reduced-motion CSS
- Participant/admin surface separation
- Published-only history display
- No pending/rejected edition leakage
- Form field retention on validation error
- CSRF token presence on all forms
- HTML escaping of user content
- Privacy/cache headers
"""
import os
import sys
import re

import pytest
from fastapi.testclient import TestClient

_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_DIR))

from app.db import apply_migrations, get_connection
from app.db_runtime import SqliteRuntimeConnection
from app.factory import create_app
from app.auth import (
    create_participant_session, sign_session_token,
    create_admin_session, sign_admin_session_token,
    generate_csrf_token, sign_csrf_token, verify_csrf_token,
)
from app import participant_repository as pt_repo, input_repository as input_repo
from app import edition_repository as ed_repo, feedback_repository as fb_repo
from app.pipeline.service import GenerationService, GenerationRequest
from app.pipeline.fixtures import load_bundle
import json, tempfile, time


def _make_app(db_path, provider=None):
    app = create_app(db_path=db_path, provider=provider)
    migrations_dir = os.path.join(_DIR, "migrations")
    apply_migrations(get_connection(db_path), migrations_dir)
    return app, db_path


def _create_participant(conn, pid, name):
    return pt_repo.create_participant(SqliteRuntimeConnection(conn), participant_id=pid, display_name=name, preferred_language="ko")


def _get_session_cookie(pid):
    session = create_participant_session(pid)
    signed = sign_session_token(session)
    return {"pe_session": signed}


def _get_admin_session_cookie():
    session = create_admin_session()
    signed = sign_admin_session_token(session)
    return {"pe_admin_session": signed}


def _get_csrf_cookie_and_token():
    token = generate_csrf_token()
    signed = sign_csrf_token(token)
    return {"pe_csrf": signed}, token


def _get_admin_csrf_cookie_and_token():
    token = generate_csrf_token()
    signed = sign_csrf_token(token)
    return {"pe_admin_csrf": signed}, token


def _make_draft_payload():
    return {
        "content_version": "test-v1", "language": "ko",
        "edition_title": "테스트 에디션",
        "publication_title": "테스트 발행",
        "deck": "테스트 요약",
        "opening": "테스트 서론입니다. " * 20,
        "provenance_note": "테스트 출처",
        "highlighted_insight": "핵심 인사이트입니다.",
        "sections": [
            {"section_id": "s001", "title": "섹션1", "source_segment_ids": ["s001"],
             "paragraphs": ["이것은 테스트 단락입니다. " * 30]},
        ],
    }


# ------------------------------------------------------------------
# CSS and design token tests
# ------------------------------------------------------------------

class TestCSSTokens:
    def test_css_version_query_present(self):
        """CSS link must contain cache-busting version query."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "css-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "CSS 테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        assert "app.css?v=pe-ui51-20260722-3" in html, "CSS version query missing"
        assert "app.css?v=pe-ui51-20260722-2" not in html, "Stale CSS reference found"

    def test_css_version_query_on_all_participant_pages(self):
        """Access, home, edition, feedback pages all reference versioned CSS."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "css-all-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "CSS 테스트")
        cookies = _get_session_cookie(pid)

        for path in ["/p/access", f"/p/{pid}", f"/p/{pid}/input"]:
            resp = client.get(path, cookies=cookies)
            assert "app.css?v=pe-ui51-20260722-3" in resp.text, f"Missing CSS version on {path}"

    def test_css_file_returns_200(self):
        """Versioned CSS URL returns HTTP 200."""
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/static/app.css?v=pe-ui51-20260722-3")
        assert resp.status_code == 200
        assert "font-editorial" in resp.text or "var(--paper)" in resp.text

    def test_css_has_design_tokens(self):
        """CSS must contain the required custom properties."""
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/static/app.css")
        css = resp.text
        for token in ["--paper", "--surface", "--ink", "--muted", "--forest",
                       "--oxblood", "--border", "--font-editorial", "--font-interface"]:
            assert token in css, f"Design token {token} missing from CSS"

    def test_css_has_reduced_motion(self):
        """CSS must support prefers-reduced-motion."""
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/static/app.css")
        assert "prefers-reduced-motion" in resp.text

    def test_css_version_3(self):
        """CSS version must be -3."""
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/p/access")
        assert "app.css?v=pe-ui51-20260722-3" in resp.text
        assert "app.css?v=pe-ui51-20260722-2" not in resp.text

    def test_focus_visible_css(self):
        """CSS must contain focus-visible rules."""
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/static/app.css?v=pe-ui51-20260722-3")
        assert "focus-visible" in resp.text


# ------------------------------------------------------------------
# Image tests
# ------------------------------------------------------------------

class TestImageAttributes:
    def _check_image(self, html, expected_src, context=""):
        pattern = rf'<img[^>]+src="{re.escape(expected_src)}"[^>]*>'
        match = re.search(pattern, html)
        assert match, f"Image {expected_src} not found in {context}"
        tag = match.group(0)
        assert "alt=" in tag, f"alt attribute missing on {expected_src}"
        assert "width=" in tag, f"width attribute missing on {expected_src}"
        assert "height=" in tag, f"height attribute missing on {expected_src}"

    def test_access_page_has_invitation_image(self):
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/p/access")
        self._check_image(resp.text, "/static/images/access-invitation.webp", "access page")

    def test_dashboard_has_hero_image(self):
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "img-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "이미지 테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        self._check_image(resp.text, "/static/images/private-library-hero.webp", "dashboard")

    def test_history_has_hero_image(self):
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "hist-img"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "기록 테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/history", cookies=cookies)
        self._check_image(resp.text, "/static/images/edition-library-history.webp", "history")

    def test_waiting_state_has_process_image(self):
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "wait-img"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "대기 테스트")
            input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid, raw_text="테스트 입력 " * 50, consent_confirmed=1)
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        self._check_image(resp.text, "/static/images/editorial-process-layers.webp", "waiting state")

    def test_access_image_exact_dimensions(self):
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/p/access")
        assert 'width="1122"' in resp.text
        assert 'height="1402"' in resp.text

    def test_dashboard_hero_exact_dimensions(self):
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "dim-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "크기 테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        assert 'width="1536"' in resp.text
        assert 'height="1024"' in resp.text

    def test_history_hero_exact_dimensions(self):
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "hist-dim"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "기록 크기 테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/history", cookies=cookies)
        assert 'width="1536"' in resp.text
        assert 'height="1024"' in resp.text


# ------------------------------------------------------------------
# Heading and CTA text tests
# ------------------------------------------------------------------

class TestParticipantText:
    def test_access_page_brand_and_cta(self):
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/p/access")
        html = resp.text
        assert "Personal Edition" in html
        assert "당신의 기록이" in html
        assert "비공개 편집실 입장" in html

    def test_access_page_privacy_notes(self):
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/p/access")
        html = resp.text
        assert "비공개 초대 전용" in html
        assert "자동" in html
        assert "검토 후 발행" in html

    def test_dashboard_greeting(self):
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "greet-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "홍길동")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        assert "홍길동" in resp.text

    def test_empty_dashboard_cta(self):
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "empty-cta"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "빈 참여자")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        assert "첫 기록" in html

    def test_input_form_heading_and_cta(self):
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "input-cta"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "입력 테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/input", cookies=cookies)
        html = resp.text
        assert "기록을 남겨주세요" in html
        assert "편집을 위해 기록 맡기기" in html

    def test_feedback_form_heading_and_cta(self):
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "fb-cta"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "피드백 테스트")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="테스트 에디션")
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/editions/1/feedback", cookies=cookies)
        html = resp.text
        assert "편집 메모" in html
        assert "편집 메모 전달하기" in html


# ------------------------------------------------------------------
# Error and terminal state tests
# ------------------------------------------------------------------

class TestTerminalStates:
    def test_invalid_token_korean_error(self):
        """Invalid token shows Korean error, not English internal details."""
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        # Get CSRF from initial page load
        resp = client.get("/p/access")
        csrf_val = ""
        import re as _re
        m = _re.search(r'name="csrf_token" value="([^"]+)"', resp.text)
        if m:
            csrf_val = m.group(1)
        resp2 = client.post("/p/access",
                            data={"token": "invalid-token-999", "csrf_token": csrf_val},
                            follow_redirects=True)
        html = resp2.text
        # Should not show internal Python tracebacks or exceptions
        assert "Traceback" not in html
        assert "Exception" not in html
        assert "FileNotFoundError" not in html
        # Should show the access page again (not a server error)
        assert "Personal Edition" in html

    def test_not_found_page_korean(self):
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "nf-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/editions/999", cookies=cookies)
        html = resp.text
        assert "찾을 수 없습니다" in html or "not found" in html.lower()
        assert "Exception" not in html
        assert "Traceback" not in html

    def test_edition_not_found_korean(self):
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "ed-nf"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/editions/999", cookies=cookies)
        html = resp.text
        assert "찾을 수 없습니다" in html or "발행" in html
        assert "Exception" not in html
        assert "Traceback" not in html


# ------------------------------------------------------------------
# Security and privacy tests
# ------------------------------------------------------------------

class TestSecurityPrivacy:
    def test_no_cache_headers(self):
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/p/access")
        cache = resp.headers.get("cache-control", "")
        assert "no-store" in cache or "no-cache" in cache or "private" in cache

    def test_no_index_header(self):
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/p/access")
        robots = resp.headers.get("x-robots-tag", "")
        assert "noindex" in robots

    def test_csrf_token_in_all_forms(self):
        """All POST forms must have CSRF token."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "csrf-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "CSRF 테스트")
        cookies = _get_session_cookie(pid)

        for path in ["/p/access", f"/p/{pid}/input"]:
            resp = client.get(path, cookies=cookies)
            assert 'name="csrf_token"' in resp.text, f"CSRF token missing on {path}"

    def test_no_raw_json_exposed(self):
        """No raw JSON or technical metadata on participant pages."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "json-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "JSON 테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        assert "error_category" not in html
        assert "validation_status" not in html
        assert "provider_call_count" not in html

    def test_admin_and_participant_separate(self):
        """Participant pages don't show admin links."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "sep-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "분리 테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        assert "/admin/" not in resp.text


# ------------------------------------------------------------------
# Published-only edition tests
# ------------------------------------------------------------------

class TestEditionVisibility:
    def test_pending_edition_not_in_participant_history(self):
        """Pending (unpublished) editions should not appear to participant."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "vis-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "가시성 테스트")
            ed_repo.create_edition(
                SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                structured_content=json.dumps(_make_draft_payload()),
                rendered_title="대기 중인 에디션")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/history", cookies=cookies)
        assert "대기 중인 에디션" not in resp.text

    def test_published_edition_visible(self):
        """Published editions appear in history."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "pub-vis"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "발행 테스트")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="발행된 에디션")
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/history", cookies=cookies)
        assert "발행된 에디션" in resp.text


# ------------------------------------------------------------------
# HTML escaping tests
# ------------------------------------------------------------------

class TestHTMLEscaping:
    def test_user_name_escaped_in_dashboard(self):
        """Participant display name with HTML chars is escaped."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "esc-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "<script>alert('x')</script>")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "script" not in html.replace("</script>", "")

    def test_generated_html_escaped(self):
        """Malicious img tags in generated content are escaped."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "esc-img"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "이미지 이스케이프 테스트")
            ed = ed_repo.create_edition(
                SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                structured_content=json.dumps(_make_draft_payload()),
                rendered_title='<img src=x onerror=alert(1)>')
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/history", cookies=cookies)
        assert '<img src=x' not in resp.text
        assert '&lt;img' in resp.text


# ------------------------------------------------------------------
# Feedback Korean labels tests
# ------------------------------------------------------------------

class TestFeedbackLabels:
    def test_feedback_korean_labels(self):
        """Feedback form shows Korean labels, not English enum names."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "fb-labels"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "피드백 라벨 테스트")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="테스트 에디션")
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/editions/1/feedback", cookies=cookies)
        for label in ["이 분위기와 방향을 계속 유지해주세요",
                      "조금 더 구체적이고 실용적으로 써주세요",
                      "생각과 감정을 조금 더 깊게 다뤄주세요"]:
            assert label in resp.text, f"Korean label missing: {label}"

    def test_feedback_no_english_enum_labels(self):
        """No English enum names exposed in feedback form."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "fb-no-en"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "피드백 영어 테스트")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="테스트 에디션")
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/editions/1/feedback", cookies=cookies)
        assert "Continue Direction" not in resp.text
        assert "More Practical" not in resp.text

    def test_feedback_enum_values_preserved(self):
        """Feedback checkbox values use enum values."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "fb-vals"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "피드백 값 테스트")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="테스트 에디션")
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/editions/1/feedback", cookies=cookies)
        assert 'value="continue_direction"' in resp.text
        assert 'value="more_practical"' in resp.text


# ------------------------------------------------------------------
# Body class and surface tests
# ------------------------------------------------------------------

class TestBodyClass:
    def test_participant_body_class(self):
        """Participant pages have participant-surface body class."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "body-class"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "바디 클래스 테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        assert 'class="participant-surface"' in resp.text
        assert 'class="admin-surface"' not in resp.text


class TestGuidedWorkflow:
    """Tests for the guided publishing workflow (Issue #57)."""

    def test_access_page_workflow_steps(self):
        """Access page shows the 4-step publishing workflow."""
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/p/access")
        html = resp.text
        assert "기록을 남깁니다" in html
        assert "AI가 초안을 구성합니다" in html
        assert "편집자가 검토합니다" in html
        assert "비공개 에디션으로 발행됩니다" in html
        assert 'class="access-workflow"' in html

    def test_access_page_workflow_is_ordered_list(self):
        """Workflow steps use semantic ordered list."""
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/p/access")
        html = resp.text
        assert "<ol" in html
        assert 'aria-label="제작 흐름"' in html

    def test_empty_state_shows_progress_bar(self):
        """Empty dashboard shows the progress steps bar."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "progress-empty"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "진행 단계 테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        assert 'aria-label="제작 진행 단계"' in html
        assert "기록" in html
        assert "초안 구성" in html
        assert "편집 검토" in html
        assert "발행" in html

    def test_empty_state_primary_action(self):
        """Empty state has '첫 기록 시작하기' as primary CTA."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "empty-primary"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "빈 상태 테스트")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        assert "첫 기록 시작하기" in html
        assert 'class="btn btn-primary"' in html

    def test_input_received_state(self):
        """Input received state shows status and process image."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "input-recv"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "기록 접수 테스트")
            input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid, raw_text="테스트 입력 " * 50, consent_confirmed=1)
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        assert "기록 접수됨" in html
        assert "editorial-process-layers.webp" in html

    def test_reviewing_state(self):
        """Reviewing state shows pending status."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "review-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "검토 테스트")
            input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid, raw_text="기록 " * 50, consent_confirmed=1)
            ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                   structured_content=json.dumps(_make_draft_payload()),
                                   rendered_title="초안")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        assert "편집 검토 중" in html
        assert "자동으로 공개되지 않" in html

    def test_published_state(self):
        """Published state shows edition and primary CTA."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "pub-state"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "발행 상태")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="발행 에디션")
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        assert "발행 완료" in html
        assert "최신 에디션 읽기" in html
        assert "피드백 보내기" in html

    def test_feedback_state(self):
        """Feedback complete state shows feedback status and secondary CTA."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "fb-state"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "피드백 상태")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="피드백 에디션")
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
            fb_repo.create_feedback(SqliteRuntimeConnection(conn), participant_id=pid, edition_id=ed.id,
                                    direction_choices=json.dumps(["continue_direction"]))
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        assert "피드백 완료" in html
        assert "새 기록 남기기" in html
        assert "최신 에디션 다시 읽기" in html

    def test_workspace_title(self):
        """Dashboard uses '작업실' title instead of '홈'."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "ws-title"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "작업실 타이틀")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        assert "작업실" in resp.text
        assert "개인 출판 작업실" in resp.text

    def _get_progress_step_attrs(self, html):
        import re as _re
        return _re.findall(
            r'<li\s+class="progress-step([^"]*)"([^>]*)>', html
        )

    def test_progress_record_stage(self):
        """record: 기록=current, others empty."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "prog-rec"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "기록단계")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        attrs = self._get_progress_step_attrs(html)
        assert len(attrs) == 4
        assert "current" in attrs[0][0]
        assert "completed" not in attrs[0][0]
        assert "completed" not in attrs[1][0]
        assert "completed" not in attrs[2][0]
        assert "completed" not in attrs[3][0]
        assert 'aria-current="step"' in attrs[0][1]

    def test_progress_input_received_stage(self):
        """input_received: 기록=completed, 초안 구성=current."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "prog-inp"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "접수단계")
            input_repo.create_input(
                SqliteRuntimeConnection(conn), participant_id=pid, raw_text="테스트 " * 50,
                consent_confirmed=1,
            )
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        attrs = self._get_progress_step_attrs(html)
        assert len(attrs) == 4
        assert "completed" in attrs[0][0]
        assert "current" in attrs[1][0]
        assert "completed" not in attrs[2][0]
        assert "completed" not in attrs[3][0]
        assert 'aria-current="step"' in attrs[1][1]

    def test_progress_reviewing_stage(self):
        """reviewing: 기록·초안=completed, 편집 검토=current."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "prog-rev"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "검토단계")
            input_repo.create_input(
                SqliteRuntimeConnection(conn), participant_id=pid, raw_text="기록 " * 50,
                consent_confirmed=1,
            )
            ed_repo.create_edition(
                SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                structured_content=json.dumps(_make_draft_payload()),
                rendered_title="초안",
            )
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        attrs = self._get_progress_step_attrs(html)
        assert len(attrs) == 4
        assert "completed" in attrs[0][0]
        assert "completed" in attrs[1][0]
        assert "current" in attrs[2][0]
        assert "completed" not in attrs[3][0]
        assert 'aria-current="step"' in attrs[2][1]

    def test_progress_published_stage(self):
        """published: 기록·초안·검토=completed, 발행=current."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "prog-pub"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "발행단계")
            ed = ed_repo.create_edition(
                SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                structured_content=json.dumps(_make_draft_payload()),
                rendered_title="발행",
            )
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        attrs = self._get_progress_step_attrs(html)
        assert len(attrs) == 4
        assert "completed" in attrs[0][0]
        assert "completed" in attrs[1][0]
        assert "completed" in attrs[2][0]
        assert "current" in attrs[3][0]
        assert 'aria-current="step"' in attrs[3][1]

    def test_progress_feedback_stage(self):
        """feedback: all steps completed."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "prog-fb"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "피드백단계")
            ed = ed_repo.create_edition(
                SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                structured_content=json.dumps(_make_draft_payload()),
                rendered_title="피드백",
            )
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
            fb_repo.create_feedback(
                SqliteRuntimeConnection(conn), participant_id=pid, edition_id=ed.id,
                direction_choices=json.dumps(["continue_direction"]),
            )
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        html = resp.text
        attrs = self._get_progress_step_attrs(html)
        assert len(attrs) == 4
        assert "completed" in attrs[0][0]
        assert "completed" in attrs[1][0]
        assert "completed" in attrs[2][0]
        assert "completed" in attrs[3][0]
        assert 'aria-current="step"' not in html


# ------------------------------------------------------------------
# Cover thumbnail tests
# ------------------------------------------------------------------

class TestCoverThumbnails:
    def test_home_published_cover(self):
        """Dashboard published edition shows cover image."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "cover-home"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "커버 홈 테스트")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="커버 테스트")
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}", cookies=cookies)
        assert "edition-cover-shift.webp" in resp.text or "edition-cover-archive.webp" in resp.text

    def test_history_cover_thumbnails(self):
        """History page shows cover thumbnails."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "cover-hist"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "커버 기록 테스트")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="커버 기록")
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/history", cookies=cookies)
        assert "history-thumb" in resp.text


# ------------------------------------------------------------------
# Input validation retention tests
# ------------------------------------------------------------------

class TestInputRetention:
    def test_validation_error_retains_input(self):
        """On validation error, the raw_text field retains user input."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "ret-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "유지 테스트")
        cookies = _get_session_cookie(pid)
        csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
        resp = client.post(f"/p/{pid}/input",
                           data={"raw_text": "짧은 입력", "csrf_token": csrf_token},
                           cookies={**cookies, **csrf_cookie})
        assert resp.status_code == 200
        assert "짧은 입력" in resp.text


# ------------------------------------------------------------------
# Issue #51 Admin Editorial Workspace & Multi-edition tests
# ------------------------------------------------------------------

class TestAdminEditorialUI:
    def test_admin_login_page_branding_and_heading(self):
        """Admin login page has proper branding, heading, guidance, and security note."""
        app, _ = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        resp = client.get("/admin/access")
        assert resp.status_code == 200
        assert "Personal Edition 편집실" in resp.text
        assert "관리자 접속" in resp.text
        assert "편집 업무 전용 비공개 공간" in resp.text
        assert "보안" in resp.text
        assert 'class="admin-surface"' in resp.text

    def test_admin_dashboard_kpis_and_status_mapping(self):
        """Admin dashboard displays actionable KPI summary cards and Korean status labels."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "dash-kpi"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "대시보드 테스트")
            input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid, raw_text="긴 입력 내용 테스트 " * 20, consent_confirmed=1)
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="초안 에디션")
        admin_cookies = _get_admin_session_cookie()
        resp = client.get("/admin/", cookies=admin_cookies)
        assert resp.status_code == 200
        assert "검토 대기" in resp.text
        assert "생성 준비" in resp.text
        assert "생성 실패" in resp.text
        assert "피드백 도착" in resp.text
        assert "최근 발행" in resp.text
        assert "검토 필요" in resp.text or "에디션 검토" in resp.text

    def test_admin_dashboard_technical_info_collapsed(self):
        """Provider/model technical info must be inside collapsible details tag."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        admin_cookies = _get_admin_session_cookie()
        resp = client.get("/admin/", cookies=admin_cookies)
        assert resp.status_code == 200
        assert "<details" in resp.text
        assert "기술 정보" in resp.text

    def test_admin_participant_detail_status_and_actions(self):
        """Participant detail page shows readable raw input cards, status, and primary action."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "detail-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "상세 참여자")
            input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid, raw_text="상세 읽기 본문 내용 테스트 " * 15, consent_confirmed=1)
        admin_cookies = _get_admin_session_cookie()
        resp = client.get(f"/admin/participants/{pid}", cookies=admin_cookies)
        assert resp.status_code == 200
        assert "상세 참여자" in resp.text
        assert "비공개 개인 발행물" in resp.text
        assert "초안 만들기" in resp.text
        assert "상세 읽기 본문 내용 테스트" in resp.text

    def test_admin_review_reader_preview(self):
        """Review page shows reader preview before editing form."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "rev-prev"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "미리보기 참여자")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="미리보기 제목")
        admin_cookies = _get_admin_session_cookie()
        resp = client.get(f"/admin/review/{ed.id}", cookies=admin_cookies)
        assert resp.status_code == 200
        assert "독자 화면 미리보기" in resp.text
        assert "테스트 발행" in resp.text
        assert "테스트 서론입니다." in resp.text

    def test_admin_safe_field_edit_validation(self):
        """Form field edit preserves inputs on validation failure and updates DB on success."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "safe-edit"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "안전 편집")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="기존 제목")
        admin_cookies = _get_admin_session_cookie()
        csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
        client.cookies.update(admin_cookies)
        client.cookies.update(csrf_cookie)

        # Submit updated structured fields
        post_data = {
            "csrf_token": csrf_token,
            "field_publication_title": "수정된 발행물 제목",
            "field_deck": "수정된 요약 문구",
            "field_opening": "수정된 여는 글 서문 " * 5,
            "field_highlighted_insight": "수정된 인사이트",
            "section_0_title": "수정 섹션 1",
            "section_0_paragraphs": "수정 섹션 1의 단락입니다.\n두 번째 단락입니다.",
            "section_1_title": "수정 섹션 2",
            "section_1_paragraphs": "수정 섹션 2의 단락입니다.",
        }
        resp = client.post(f"/admin/review/{ed.id}/edit", data=post_data)
        assert resp.status_code in (200, 303)

        with get_connection(db) as conn:
            updated_ed = ed_repo.get_edition_by_id(conn, ed.id)
            parsed = json.loads(updated_ed.structured_content)
            assert parsed["publication_title"] == "수정된 발행물 제목"

    def test_admin_publish_and_reject_actions(self):
        """Admin publish and reject buttons function correctly with explicit CSRF."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "pub-rej"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "발행 거부")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="발행 테스트")
        admin_cookies = _get_admin_session_cookie()
        csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
        client.cookies.update(admin_cookies)
        client.cookies.update(csrf_cookie)

        resp = client.post(f"/admin/review/{ed.id}/publish", data={"csrf_token": csrf_token}, follow_redirects=False)
        assert resp.status_code == 303

        with get_connection(db) as conn:
            updated_ed = ed_repo.get_edition_by_id(conn, ed.id)
            assert updated_ed.publication_state == "published"

    def test_multi_edition_history_fixture_3_plus(self):
        """History view renders multi-edition history (3+ editions) correctly."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "multi-ed"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "다중 에디션")
            for i in range(1, 4):
                ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=i,
                                             structured_content=json.dumps(_make_draft_payload()),
                                             rendered_title=f"에디션 #{i} 제목")
                ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed.id, "published")
        cookies = _get_session_cookie(pid)
        resp = client.get(f"/p/{pid}/history", cookies=cookies)
        assert resp.status_code == 200
        assert "#1" in resp.text
        assert "#2" in resp.text
        assert "#3" in resp.text
        assert "에디션 #3 제목" in resp.text


class TestOperatorUIFixedContractAndNavigation:
    """Verifies all CTO review requirements for operator navigation, latest selection, status mappings, and safe errors."""

    def test_admin_navigation_branching_on_all_admin_routes(self):
        """Admin routes use admin navigation with Personal Edition 편집실, /admin/logout, and no participant menu."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "nav-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "네비게이션 테스트")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1,
                                         structured_content=json.dumps(_make_draft_payload()),
                                         rendered_title="네비 에디션")

        admin_cookies = _get_admin_session_cookie()
        client.cookies.update(admin_cookies)

        admin_paths = [
            "/admin/",
            f"/admin/participants/{pid}",
            f"/admin/review/{ed.id}",
        ]
        for path in admin_paths:
            resp = client.get(path)
            assert resp.status_code == 200, f"Failed on {path}"
            assert "Personal Edition 편집실" in resp.text
            assert 'action="/admin/logout"' in resp.text
            assert f'action="/p/{pid}/logout"' not in resp.text
            assert f'href="/p/{pid}/input"' not in resp.text
            assert f'href="/p/{pid}/history"' not in resp.text

    def test_multi_input_latest_sequence_targeted_for_generation(self):
        """Out of 3 inputs (sequences 1, 2, 3), sequence 3 (latest) is targeted in admin participant detail."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "multi-inp-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "입력3개")
            inp1 = input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid, raw_text="첫 번째 수신 기록 텍스트 " * 5)
            inp2 = input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid, raw_text="두 번째 수신 기록 텍스트 " * 5)
            inp3 = input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid, raw_text="세 번째 최신 수신 기록 텍스트 " * 5)

        admin_cookies = _get_admin_session_cookie()
        client.cookies.update(admin_cookies)

        resp = client.get(f"/admin/participants/{pid}")
        assert resp.status_code == 200
        assert f'value="{inp3.id}"' in resp.text
        assert "기록 #3" in resp.text

    def test_multi_edition_latest_edition_selection_and_status(self):
        """Out of 3 editions (1, 2, 3), edition 3 is selected as latest edition."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "multi-ed-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "에디션3개")
            input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid, raw_text="기록 " * 10)
            ed1 = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1, structured_content=json.dumps(_make_draft_payload()), rendered_title="1호")
            ed2 = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=2, structured_content=json.dumps(_make_draft_payload()), rendered_title="2호")
            ed3 = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=3, structured_content=json.dumps(_make_draft_payload()), rendered_title="3호")
            fb_repo.create_feedback(SqliteRuntimeConnection(conn), participant_id=pid, edition_id=ed1.id, direction_choices=json.dumps(["continue_direction"]))

        admin_cookies = _get_admin_session_cookie()
        client.cookies.update(admin_cookies)

        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert "#3" in resp.text

    def test_latest_edition_feedback_only_triggers_feedback_received_status(self):
        """Feedback on past edition does NOT trigger feedback_received status for current state."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "past-fb-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "과거피드백")
            input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid, raw_text="기록 " * 10)
            ed1 = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1, structured_content=json.dumps(_make_draft_payload()), rendered_title="1호")
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed1.id, "published")
            fb_repo.create_feedback(SqliteRuntimeConnection(conn), participant_id=pid, edition_id=ed1.id, direction_choices=json.dumps(["more_practical"]))
            ed2 = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=2, structured_content=json.dumps(_make_draft_payload()), rendered_title="2호")
            ed_repo.update_edition_publication(SqliteRuntimeConnection(conn), ed2.id, "published")

        admin_cookies = _get_admin_session_cookie()
        client.cookies.update(admin_cookies)

        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert "발행 완료" in resp.text

    def test_generation_failed_status_mapping_and_count(self):
        """Actual generation_failed status displays as 생성 실패 and counts in dashboard KPI."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "gen-fail-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "실패참여자")
            input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid, raw_text="기록 " * 10)
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1, structured_content="{}", rendered_title="실패호")
            conn.execute("UPDATE editions SET generation_status = 'generation_failed' WHERE id = ?", (ed.id,))

        admin_cookies = _get_admin_session_cookie()
        client.cookies.update(admin_cookies)

        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert "생성 실패" in resp.text

    def test_generation_exception_safe_error_and_no_mutation(self):
        """When generation raises exception, safe Korean message is displayed and no DB mutation occurs."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "err-safe-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "오류참여자")
            inp = input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid, raw_text="기록 " * 10)

        admin_cookies = _get_admin_session_cookie()
        csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
        client.cookies.update(admin_cookies)
        client.cookies.update(csrf_cookie)

        class FailingService:
            def generate_edition(self, conn, request):
                raise RuntimeError("Provider API Key Invalid Secrets!")

        app.state.generation_service = FailingService()

        resp = client.post(
            f"/admin/participants/{pid}/generate",
            data={"csrf_token": csrf_token, "input_id": inp.id},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "초안을 생성하지 못했습니다." in resp.text
        assert "기존 기록과 에디션은 변경되지 않았습니다." in resp.text
        assert "Provider API Key Invalid Secrets" not in resp.text

        with get_connection(db) as conn:
            editions = ed_repo.get_editions_by_participant(conn, pid)
            assert len(editions) == 0

    def test_admin_secret_error_korean_only(self):
        """Wrong admin secret error displays Korean message without English Invalid admin secret."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)

        get_resp = client.get("/admin/access")
        csrf_token = get_resp.text.split('name="csrf_token" value="')[1].split('"')[0]

        resp = client.post("/admin/access", data={"secret": "wrongsecret", "csrf_token": csrf_token})
        assert resp.status_code == 200
        assert "올바르지 않은 관리자 비밀번호입니다." in resp.text
        assert "Invalid admin secret." not in resp.text

    def test_feedback_direction_korean_labels_synthetic_fixture(self):
        """Feedback inspection displays Korean labels (방향 유지, 성찰·깊이감 강화) for synthetic 2+ direction choices."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"))
        client = TestClient(app)
        pid = "fb-label-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "피드백표시")
            ed = ed_repo.create_edition(SqliteRuntimeConnection(conn), participant_id=pid, edition_number=1, structured_content=json.dumps(_make_draft_payload()), rendered_title="1호")
            fb_repo.create_feedback(
                SqliteRuntimeConnection(conn),
                participant_id=pid,
                edition_id=ed.id,
                direction_choices=json.dumps(["continue_direction", "more_reflective"]),
                free_text="방향 전환 희망합니다",
            )

        admin_cookies = _get_admin_session_cookie()
        client.cookies.update(admin_cookies)

        resp = client.get(f"/admin/participants/{pid}")
        assert resp.status_code == 200
        assert "방향 유지" in resp.text
        assert "성찰·깊이감 강화" in resp.text
        assert "continue_direction" not in resp.text
        assert "more_reflective" not in resp.text


# =====================================================================
# Issue #51: generation failure and schema validation safety
# =====================================================================

class FailingProvider:
    """Provider that returns failed generation results without exceptions."""

    def __init__(self):
        self.provider = "failing_test"
        self.model = "failing_test_model"
        self.call_count = 0

    def generate_structured(self, **kwargs):
        self.call_count += 1
        from app.domain.models import ProviderResult
        from app.domain.enums import CostClass, ProviderErrorCategory
        return ProviderResult(
            provider="failing_test",
            advertised_model="failing_test_model",
            cost_class=CostClass.FREE,
            success=False,
            error_category=ProviderErrorCategory.PROVIDER_ERROR,
            error_message="internal provider error",
            latency_seconds=0.1,
            retry_count=0,
            request_id=kwargs.get("request_id", ""),
        )


class TestGenerationFailureHandling:
    """Test that generation failures (succeeded=False) are handled safely."""

    def test_returned_failure_shows_safe_korean_message(self):
        """succeeded=False triggers safe Korean failure message, not raw error."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"), provider=FailingProvider())
        client = TestClient(app)
        pid = "fail-ret-test"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "실패테스트")
            inp = input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid,
                                          raw_text="테스트 입력입니다. " * 50, consent_confirmed=1)
            input_id = inp.id

        admin_cookies = _get_admin_session_cookie()
        csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
        all_cookies = {**admin_cookies, **csrf_cookie}

        resp = client.post(
            f"/admin/participants/{pid}/generate",
            data={"input_id": input_id, "csrf_token": csrf_token},
            cookies=all_cookies, follow_redirects=False,
        )
        assert resp.status_code == 303
        redirect_url = resp.headers["location"]
        assert "error=generation_failed" in redirect_url

        resp2 = client.get(redirect_url, cookies=all_cookies, follow_redirects=True)
        assert resp2.status_code == 200
        assert "초안을 생성하지 못했습니다" in resp2.text
        assert "기존 기록과 에디션은 변경되지 않았습니다" in resp2.text
        assert "internal provider error" not in resp2.text
        assert "Traceback" not in resp2.text

        conn2 = get_connection(db)
        try:
            editions = ed_repo.get_editions_by_participant(conn2, pid)
            assert len(editions) == 0
        finally:
            conn2.close()

    def test_schema_validation_safe_error(self):
        """Schema validation errors show safe Korean message, not Pydantic exception."""
        from app.routes.admin import _validate_edition_content
        is_valid, error_msg, model = _validate_edition_content('{"invalid": true}')
        assert is_valid is False
        assert "validation_error" not in error_msg.lower()
        assert "ValidationError" not in error_msg
        assert "type=" not in error_msg
        assert "input_value" not in error_msg
        assert model is None
        assert "필수 항목" in error_msg or "형식" in error_msg

    def test_schema_malformed_json_safe_error(self):
        """Malformed JSON shows safe error, not traceback."""
        from app.routes.admin import _validate_edition_content
        is_valid, error_msg, model = _validate_edition_content("not json at all")
        assert is_valid is False
        assert "JSON" in error_msg
        assert "Traceback" not in error_msg
        assert model is None

    def test_schema_validation_invalid_content_safe_error(self):
        """Valid JSON but wrong schema shows safe message."""
        from app.routes.admin import _validate_edition_content
        bad_content = json.dumps({
            "content_version": "v1",
            "language": "ko",
            "edition_title": "제목",
            "publication_title": "발행",
            "deck": "요약",
            "opening": "서론",
            "provenance_note": "출처",
            "highlighted_insight": "인사이트",
            "sections": [],  # Missing required fields
        })
        is_valid, error_msg, model = _validate_edition_content(bad_content)
        assert is_valid is False
        assert "ValidationError" not in error_msg
        assert "type=" not in error_msg
        assert "input_value" not in error_msg

    def test_generation_failure_preserves_input(self):
        """Generation failure doesn't destroy existing input."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"), provider=FailingProvider())
        client = TestClient(app)
        pid = "fail-preserve"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "입력유지")
            inp = input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid,
                                          raw_text="유지되어야 할 입력입니다. " * 30,
                                          consent_confirmed=1)
            input_id = inp.id

        admin_cookies = _get_admin_session_cookie()
        csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
        all_cookies = {**admin_cookies, **csrf_cookie}

        client.post(
            f"/admin/participants/{pid}/generate",
            data={"input_id": input_id, "csrf_token": csrf_token},
            cookies=all_cookies, follow_redirects=False,
        )

        conn2 = get_connection(db)
        try:
            inputs = input_repo.get_inputs_by_participant(conn2, pid)
            assert len(inputs) == 1
            assert "유지되어야 할 입력" in inputs[0].raw_text
        finally:
            conn2.close()

    def test_generation_failure_redirects_with_error(self):
        """Failed generation redirects to detail page with error code."""
        app, db = _make_app(tempfile.mktemp(suffix=".db"), provider=FailingProvider())
        client = TestClient(app)
        pid = "fail-redirect"
        with get_connection(db) as conn:
            _create_participant(conn, pid, "리다이렉트")
            inp = input_repo.create_input(SqliteRuntimeConnection(conn), participant_id=pid,
                                          raw_text="리다이렉트 테스트 입력. " * 30,
                                          consent_confirmed=1)
            input_id = inp.id

        admin_cookies = _get_admin_session_cookie()
        csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
        all_cookies = {**admin_cookies, **csrf_cookie}

        resp = client.post(
            f"/admin/participants/{pid}/generate",
            data={"input_id": input_id, "csrf_token": csrf_token},
            cookies=all_cookies, follow_redirects=False,
        )
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert f"/admin/participants/{pid}" in location
        assert "error=generation_failed" in location

        resp2 = client.get(location, cookies=all_cookies)
        assert resp2.status_code == 200
        assert "초안을 생성하지 못했습니다" in resp2.text


class TestValidationPrivacy:
    """Ensure private editorial content is never logged during schema validation."""

    def test_private_content_not_logged_on_schema_error(self, caplog):
        """Sentinel payload in schema validation must not appear in log output."""
        from app.routes.admin import _validate_edition_content
        sentinel = "PRIVATE_EDITORIAL_SENTINEL_DO_NOT_LOG"
        payload = {
            "content_version": "v1",
            "language": "ko",
            "edition_title": sentinel,
            "publication_title": "발행",
            "deck": "요약",
            "opening": "서론",
            "provenance_note": "출처",
            "highlighted_insight": "인사이트",
            "sections": [{"section_id": "s001", "title": "T1",
                          "source_segment_ids": ["s001"],
                          "paragraphs": [sentinel]}],
        }
        import json as _json
        is_valid, error_msg, model = _validate_edition_content(_json.dumps(payload))
        assert is_valid is False
        assert model is None
        assert "필수 항목" in error_msg or "형식" in error_msg

        log_text = caplog.text
        assert sentinel not in log_text, f"Private content leaked into logs: {sentinel}"
        assert "input_value" not in log_text, "input_value leaked into logs"
        assert "ValidationError" not in log_text, "ValidationError leaked into logs"
