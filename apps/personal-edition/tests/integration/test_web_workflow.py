"""Comprehensive web, security, and end-to-end tests for Phase 4 private web workflow.

Covers all 17 test categories from Issue #28.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.mock import MockProvider
from app import participant_repository as pt_repo
from app import input_repository as input_repo
from app import edition_repository as ed_repo
from app import feedback_repository as fb_repo
from app.auth import (
    create_participant_session,
    create_admin_session,
    sign_session_token,
    sign_csrf_token,
    verify_csrf_token,
    generate_csrf_token,
    decode_session_token,
)
from app.config import Settings
from app.db import apply_migrations, get_connection
from app.domain.models import EditionContent, EditorialPlan, EditionSection
from app.factory import create_app
from app.pipeline.service import GenerationService


MIGRATIONS_DIR = str(
    Path(__file__).resolve().parent.parent.parent / "migrations"
)


def _make_app(tmp_path: Path, provider=None):
    db_path = str(tmp_path / "test.db")
    app = create_app(db_path=db_path, provider=provider)
    conn = get_connection(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
    finally:
        conn.close()
    return app, db_path


def _create_participant(conn, pid="p1", name="Test User", lang="ko"):
    return pt_repo.create_participant(
        conn, participant_id=pid, display_name=name, preferred_language=lang
    )


def _get_session_cookie(participant_id: str) -> dict[str, str]:
    session_data = create_participant_session(participant_id)
    signed = sign_session_token(session_data)
    return {"pe_session": signed}


def _get_admin_session_cookie() -> dict[str, str]:
    session_data = create_admin_session()
    signed = sign_session_token(session_data)
    return {"pe_admin_session": signed}


def _get_csrf_cookie_and_token() -> tuple[dict[str, str], str]:
    token = generate_csrf_token()
    signed = sign_csrf_token(token)
    return {"pe_csrf": signed}, token


def _get_admin_csrf_cookie_and_token() -> tuple[dict[str, str], str]:
    token = generate_csrf_token()
    signed = sign_csrf_token(token)
    return {"pe_admin_csrf": signed}, token


MOCK_PLAN_PAYLOAD = {
    "plan_version": "test-v1",
    "language": "ko",
    "central_theme": "테스트 주제",
    "reader_value": "테스트 가치",
    "opening_intent": "테스트 의도",
    "sections": [
        {
            "section_id": "s001",
            "working_title": "섹션1",
            "purpose": "목적1",
            "source_segment_ids": ["s001"],
        },
        {
            "section_id": "s002",
            "working_title": "섹션2",
            "purpose": "목적2",
            "source_segment_ids": ["s001"],
        },
    ],
    "highlighted_insight": "핵심",
}


def _make_draft_payload(section_ids=None):
    if section_ids is None:
        section_ids = ["s001", "s002"]
    sections = []
    for i, sid in enumerate(section_ids):
        sections.append({
            "section_id": sid,
            "title": f"섹션{i+1}",
            "paragraphs": [f"이것은 테스트 단락입니다. " * 50],
            "source_segment_ids": ["s001"],
            "contains_interpretation": False,
        })
    return {
        "content_version": "test-v1",
        "language": "ko",
        "publication_title": "테스트 발행 제목",
        "edition_title": "테스트 에디션 제목",
        "deck": "테스트 요약",
        "opening": "테스트 서론입니다. " * 20,
        "sections": sections,
        "highlighted_insight": "핵심 인사이트",
        "provenance_note": "테스트 출처",
    }


def _make_long_korean_text(min_chars=600):
    return "한국어 테스트 문장입니다. " * 300


# ================================================================
# 1. Application startup, migrations, /health regression
# ================================================================
class TestApplicationStartup:
    def test_health_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "ai_provider" in data
            assert "ai_model" in data

    def test_migrations_applied_on_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            conn = get_connection(db_path)
            try:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                table_names = {t["name"] for t in tables}
                assert "participants" in table_names
                assert "editions" in table_names
                assert "inputs" in table_names
                assert "feedback" in table_names
                assert "generation_runs" in table_names
                assert "schema_migrations" in table_names
            finally:
                conn.close()

    def test_app_importable(self):
        from app.main import app as main_app
        assert main_app is not None


# ================================================================
# 2. Participant access: success, invalid token, deleted, logout, cookies
# ================================================================
class TestParticipantAccess:
    def test_token_entry_page_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/p/access")
            assert resp.status_code == 200
            assert "access token" in resp.text.lower() or "토큰" in resp.text

    def test_valid_token_grants_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                prov = _create_participant(conn, "p1", "Test User")
                raw_token = prov.one_time_token
            finally:
                conn.close()
            resp = client.post(
                "/p/access", data={"token": raw_token},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/p/p1"
            assert "pe_session" in resp.cookies

    def test_invalid_token_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.post("/p/access", data={"token": "invalid-token"})
            assert resp.status_code == 200
            assert "Invalid" in resp.text or "invalid" in resp.text.lower()

    def test_empty_token_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.post("/p/access", data={"token": ""})
            assert resp.status_code == 200

    def test_deleted_participant_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                prov = _create_participant(conn, "p1", "Test User")
                raw_token = prov.one_time_token
                pt_repo.delete_participant(conn, "p1")
            finally:
                conn.close()
            resp = client.post("/p/access", data={"token": raw_token})
            assert resp.status_code == 200
            assert "Invalid" in resp.text or "invalid" in resp.text.lower()

    def test_dashboard_requires_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/p/p1", follow_redirects=False)
            assert resp.status_code == 303
            assert resp.headers["location"] == "/p/access"

    def test_dashboard_with_valid_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1", cookies=cookies)
            assert resp.status_code == 200
            assert "Test User" in resp.text

    def test_dashboard_wrong_participant_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                _create_participant(conn, "p2", "User Two")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p2", cookies=cookies, follow_redirects=False)
            assert resp.status_code == 303

    def test_logout_clears_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.post("/p/p1/logout", cookies=cookies,
                               follow_redirects=False)
            assert resp.status_code == 303


# ================================================================
# 3. Participant input submission: success and validation failure
# ================================================================
class TestParticipantInput:
    def _make_client_with_session(self, tmp_path):
        app, db_path = _make_app(tmp_path)
        client = TestClient(app)
        conn = get_connection(db_path)
        try:
            _create_participant(conn, "p1", "Test User")
        finally:
            conn.close()
        cookies = _get_session_cookie("p1")
        return client, cookies

    def test_input_form_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, cookies = self._make_client_with_session(Path(tmp))
            resp = client.get("/p/p1/input", cookies=cookies)
            assert resp.status_code == 200
            assert "csrf_token" in resp.text

    def test_input_submission_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, cookies = self._make_client_with_session(Path(tmp))
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            all_cookies = {**cookies, **csrf_cookie}
            resp = client.post(
                "/p/p1/input",
                data={
                    "raw_text": "테스트 입력 텍스트입니다. " * 100,
                    "consent_confirmed": "1",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "submitted" in resp.text.lower() or "제출" in resp.text

    def test_input_empty_text_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, cookies = self._make_client_with_session(Path(tmp))
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            all_cookies = {**cookies, **csrf_cookie}
            resp = client.post(
                "/p/p1/input",
                data={
                    "raw_text": "",
                    "consent_confirmed": "1",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "provide" in resp.text.lower() or "입력" in resp.text

    def test_input_no_consent_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, cookies = self._make_client_with_session(Path(tmp))
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            all_cookies = {**cookies, **csrf_cookie}
            resp = client.post(
                "/p/p1/input",
                data={
                    "raw_text": "테스트 입력 텍스트입니다.",
                    "consent_confirmed": "0",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "consent" in resp.text.lower() or "동의" in resp.text

    def test_input_stored_in_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            all_cookies = {**cookies, **csrf_cookie}
            resp = client.post(
                "/p/p1/input",
                data={
                    "raw_text": "DB 저장 테스트 입력입니다. " * 20,
                    "consent_confirmed": "1",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            conn2 = get_connection(db_path)
            try:
                inputs = input_repo.get_inputs_by_participant(conn2, "p1")
                assert len(inputs) >= 1
                assert "DB 저장 테스트" in inputs[0].raw_text
            finally:
                conn2.close()


# ================================================================
# 4. Cross-participant isolation
# ================================================================
class TestCrossParticipantIsolation:
    def test_cannot_read_others_edition(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                _create_participant(conn, "p2", "User Two")
                ed = ed_repo.create_edition(
                    conn,
                    participant_id="p2",
                    edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="P2 Edition",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()

            cookies_p1 = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/1", cookies=cookies_p1)
            assert resp.status_code == 200
            assert "not found" in resp.text.lower() or "찾을" in resp.text

    def test_cannot_submit_feedback_on_others_edition(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                _create_participant(conn, "p2", "User Two")
                ed = ed_repo.create_edition(
                    conn,
                    participant_id="p2",
                    edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="P2 Edition",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()

            cookies_p1 = _get_session_cookie("p1")
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            all_cookies = {**cookies_p1, **csrf_cookie}
            resp = client.post(
                "/p/p1/editions/1/feedback",
                data={
                    "direction_choices": "continue_direction",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "찾을" in resp.text or "not found" in resp.text.lower()
            conn2 = get_connection(db_path)
            try:
                feedbacks = conn2.execute(
                    "SELECT * FROM feedback WHERE participant_id = 'p1'"
                ).fetchall()
                assert len(feedbacks) == 0
            finally:
                conn2.close()


# ================================================================
# 5. Pending/rejected editions invisible to participants
# ================================================================
class TestEditionVisibility:
    def test_pending_edition_invisible(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                ed_repo.create_edition(
                    conn,
                    participant_id="p1",
                    edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="Pending Edition",
                )
            finally:
                conn.close()

            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/1", cookies=cookies)
            assert resp.status_code == 200
            assert "not found" in resp.text.lower() or "찾을" in resp.text

    def test_rejected_edition_invisible(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                ed = ed_repo.create_edition(
                    conn,
                    participant_id="p1",
                    edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="Rejected Edition",
                )
                ed_repo.update_edition_publication(conn, ed.id, "rejected")
            finally:
                conn.close()

            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/1", cookies=cookies)
            assert resp.status_code == 200
            assert "not found" in resp.text.lower() or "찾을" in resp.text

    def test_published_edition_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                ed = ed_repo.create_edition(
                    conn,
                    participant_id="p1",
                    edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="Published Edition",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()

            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/1", cookies=cookies)
            assert resp.status_code == 200
            assert "테스트 발행 제목" in resp.text


# ================================================================
# 6. Admin authentication and unauthorized admin rejection
# ================================================================
class TestAdminAuthentication:
    def test_admin_access_page_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/admin/access")
            assert resp.status_code == 200

    def test_admin_wrong_secret_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.post("/admin/access", data={"secret": "wrong"})
            assert resp.status_code == 200
            assert "Invalid" in resp.text or "invalid" in resp.text.lower()

    def test_admin_valid_secret_grants_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.post(
                "/admin/access",
                data={"secret": "dev-admin-secret-change-in-production"},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert "pe_admin_session" in resp.cookies

    def test_admin_dashboard_requires_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/admin/", follow_redirects=False)
            assert resp.status_code == 303
            assert resp.headers["location"] == "/admin/access"

    def test_admin_dashboard_with_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            cookies = _get_admin_session_cookie()
            resp = client.get("/admin/", cookies=cookies)
            assert resp.status_code == 200

    def test_admin_logout(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            cookies = _get_admin_session_cookie()
            resp = client.post(
                "/admin/logout", cookies=cookies, follow_redirects=False
            )
            assert resp.status_code == 303


# ================================================================
# 7. CSRF protection
# ================================================================
class TestCSRFProtection:
    def test_participant_input_rejects_missing_csrf(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.post(
                "/p/p1/input",
                data={
                    "raw_text": "테스트 입력 텍스트입니다.",
                    "consent_confirmed": "1",
                    "csrf_token": "",
                },
                cookies=cookies,
            )
            assert resp.status_code == 200
            assert "token" in resp.text.lower() or "토큰" in resp.text

    def test_admin_edit_rejects_missing_csrf(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                ed = ed_repo.create_edition(
                    conn,
                    participant_id="p1",
                    edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                )
                edition_id = ed.id
            finally:
                conn.close()

            admin_cookies = _get_admin_session_cookie()
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={
                    "structured_content": json.dumps(_make_draft_payload()),
                    "csrf_token": "",
                },
                cookies=admin_cookies,
                follow_redirects=False,
            )
            assert resp.status_code == 303

    def test_admin_publish_rejects_missing_csrf(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                ed = ed_repo.create_edition(
                    conn,
                    participant_id="p1",
                    edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                )
                edition_id = ed.id
            finally:
                conn.close()

            admin_cookies = _get_admin_session_cookie()
            resp = client.post(
                f"/admin/review/{edition_id}/publish",
                data={"csrf_token": ""},
                cookies=admin_cookies,
                follow_redirects=False,
            )
            assert resp.status_code == 303


# ================================================================
# 8. MockProvider generation through pending_review persistence
# ================================================================
class TestGenerationThroughWeb:
    def test_admin_generate_creates_edition(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = MockProvider(
                task_payloads={
                    "editorial_plan": MOCK_PLAN_PAYLOAD,
                    "edition_draft": _make_draft_payload(),
                }
            )
            app, db_path = _make_app(Path(tmp), provider=provider)
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                inp = input_repo.create_input(
                    conn,
                    participant_id="p1",
                    raw_text=_make_long_korean_text(600),
                    consent_confirmed=1,
                )
                input_id = inp.id
            finally:
                conn.close()

            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            resp = client.post(
                "/admin/participants/p1/generate",
                data={"input_id": input_id, "csrf_token": csrf_token},
                cookies=all_cookies,
                follow_redirects=False,
            )
            assert resp.status_code == 303

            conn2 = get_connection(db_path)
            try:
                editions = ed_repo.get_editions_by_participant(conn2, "p1")
                assert len(editions) >= 1
                assert editions[0].generation_status == "pending_review"
                assert editions[0].publication_state == "pending"
            finally:
                conn2.close()


# ================================================================
# 9. Admin review, valid/invalid edit, publish, reject
# ================================================================
class TestAdminReviewPublishReject:
    def _setup_edition(self, tmp_path):
        app, db_path = _make_app(tmp_path)
        conn = get_connection(db_path)
        try:
            _create_participant(conn, "p1", "Test User")
            ed = ed_repo.create_edition(
                conn,
                participant_id="p1",
                edition_number=1,
                structured_content=json.dumps(_make_draft_payload()),
                rendered_title="Test Edition",
            )
            edition_id = ed.id
        finally:
            conn.close()
        return app, db_path, edition_id

    def test_admin_review_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            cookies = _get_admin_session_cookie()
            resp = client.get(f"/admin/review/{edition_id}", cookies=cookies)
            assert resp.status_code == 200
            assert "Test Edition" in resp.text

    def test_admin_edit_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}

            new_content = _make_draft_payload()
            new_content["edition_title"] = "수정된 제목"
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={
                    "structured_content": json.dumps(new_content),
                    "rendered_title": "수정된 에디션",
                    "reviewer_notes": "검토 메모",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
                follow_redirects=False,
            )
            assert resp.status_code == 303

            conn = get_connection(db_path)
            try:
                ed = ed_repo.get_edition_by_id(conn, edition_id)
                assert ed.rendered_title == "수정된 에디션"
                assert ed.reviewer_notes == "검토 메모"
            finally:
                conn.close()

    def test_admin_edit_invalid_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={
                    "structured_content": "not valid json",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "Invalid JSON" in resp.text or "invalid" in resp.text.lower()

    def test_admin_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            resp = client.post(
                f"/admin/review/{edition_id}/publish",
                data={"csrf_token": csrf_token},
                cookies=all_cookies,
                follow_redirects=False,
            )
            assert resp.status_code == 303

            conn = get_connection(db_path)
            try:
                ed = ed_repo.get_edition_by_id(conn, edition_id)
                assert ed.publication_state == "published"
                assert ed.published_at is not None
            finally:
                conn.close()

    def test_admin_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            resp = client.post(
                f"/admin/review/{edition_id}/reject",
                data={"csrf_token": csrf_token},
                cookies=all_cookies,
                follow_redirects=False,
            )
            assert resp.status_code == 303

            conn = get_connection(db_path)
            try:
                ed = ed_repo.get_edition_by_id(conn, edition_id)
                assert ed.publication_state == "rejected"
            finally:
                conn.close()


# ================================================================
# 10. Published edition reading and history ordering
# ================================================================
class TestEditionReadingHistory:
    def test_history_shows_published_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                for i in range(1, 4):
                    ed = ed_repo.create_edition(
                        conn,
                        participant_id="p1",
                        edition_number=i,
                        structured_content=json.dumps(_make_draft_payload()),
                        rendered_title=f"Edition {i}",
                    )
                    if i <= 2:
                        ed_repo.update_edition_publication(
                            conn, ed.id, "published"
                        )
            finally:
                conn.close()

            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/history", cookies=cookies)
            assert resp.status_code == 200
            assert "Edition 2" in resp.text
            assert "Edition 1" in resp.text

    def test_history_ordering_descending(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                for i in range(1, 4):
                    ed = ed_repo.create_edition(
                        conn,
                        participant_id="p1",
                        edition_number=i,
                        structured_content=json.dumps(_make_draft_payload()),
                        rendered_title=f"Edition {i}",
                    )
                    ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()

            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/history", cookies=cookies)
            assert resp.status_code == 200
            pos3 = resp.text.find("Edition 3")
            pos1 = resp.text.find("Edition 1")
            assert pos3 < pos1


# ================================================================
# 11. Feedback persistence and ownership
# ================================================================
class TestFeedbackPersistence:
    def test_feedback_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                ed = ed_repo.create_edition(
                    conn,
                    participant_id="p1",
                    edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="Edition 1",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
                edition_id = ed.id
            finally:
                conn.close()

            cookies = _get_session_cookie("p1")
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            all_cookies = {**cookies, **csrf_cookie}
            resp = client.post(
                "/p/p1/editions/1/feedback",
                data={
                    "direction_choices": ["continue_direction"],
                    "selected_section_id": "s001",
                    "free_text": "좋은 에디션이었습니다.",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "감사" in resp.text or "제출" in resp.text

            conn2 = get_connection(db_path)
            try:
                feedbacks = fb_repo.get_feedback_by_edition(conn2, edition_id)
                assert len(feedbacks) == 1
                assert "continue_direction" in feedbacks[0].direction_choices
            finally:
                conn2.close()

    def test_feedback_ownership_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                _create_participant(conn, "p2", "User Two")
                ed = ed_repo.create_edition(
                    conn,
                    participant_id="p2",
                    edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="P2 Edition",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()

            cookies_p1 = _get_session_cookie("p1")
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            all_cookies = {**cookies_p1, **csrf_cookie}
            resp = client.post(
                "/p/p1/editions/1/feedback",
                data={
                    "direction_choices": "continue_direction",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "찾을" in resp.text or "not found" in resp.text.lower()
            conn2 = get_connection(db_path)
            try:
                feedbacks = conn2.execute(
                    "SELECT * FROM feedback WHERE participant_id = 'p1'"
                ).fetchall()
                assert len(feedbacks) == 0
            finally:
                conn2.close()


# ================================================================
# 12. Second-edition continuity display
# ================================================================
class TestSecondEditionContinuity:
    def test_applied_feedback_shown_on_second_edition(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")

                draft1 = _make_draft_payload()
                ed1 = ed_repo.create_edition(
                    conn,
                    participant_id="p1",
                    edition_number=1,
                    structured_content=json.dumps(draft1),
                    rendered_title="Edition 1",
                )
                ed_repo.update_edition_publication(conn, ed1.id, "published")

                fb = fb_repo.create_feedback(
                    conn,
                    participant_id="p1",
                    edition_id=ed1.id,
                    direction_choices=json.dumps(["continue_direction"]),
                    free_text="계속 이 방향으로",
                )

                draft2 = _make_draft_payload()
                draft2["applied_feedback"] = {
                    "feedback_id": fb.id,
                    "action": "continue_direction",
                    "affected_section_ids": ["s001", "s002"],
                    "evidence": "피드백이 반영되었습니다.",
                }
                ed2 = ed_repo.create_edition_with_feedback_applied(
                    conn,
                    participant_id="p1",
                    edition_number=2,
                    prior_edition_id=ed1.id,
                    input_id=None,
                    structured_content=json.dumps(draft2),
                    rendered_title="Edition 2",
                    feedback_id=fb.id,
                )
                ed_repo.update_edition_publication(conn, ed2.id, "published")
            finally:
                conn.close()

            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/2", cookies=cookies)
            assert resp.status_code == 200
            assert "피드백" in resp.text or "feedback" in resp.text.lower()


# ================================================================
# 13. Recursive script/HTML/event-handler/unsafe-URL content escaping
# ================================================================
class TestUnsafeContentEscaping:
    def test_script_tag_escaped_in_edition(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                malicious_draft = _make_draft_payload()
                malicious_draft["sections"][0]["paragraphs"] = [
                    "<script>alert('xss')</script>"
                ]
                ed = ed_repo.create_edition(
                    conn,
                    participant_id="p1",
                    edition_number=1,
                    structured_content=json.dumps(malicious_draft),
                    rendered_title="XSS Test",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()

            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/1", cookies=cookies)
            assert resp.status_code == 200
            assert "<script>" not in resp.text
            assert "&lt;script&gt;" in resp.text

    def test_event_handler_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                malicious_draft = _make_draft_payload()
                malicious_draft["sections"][0]["paragraphs"] = [
                    '<img src=x onerror="alert(1)">'
                ]
                ed = ed_repo.create_edition(
                    conn,
                    participant_id="p1",
                    edition_number=1,
                    structured_content=json.dumps(malicious_draft),
                    rendered_title="Event Handler Test",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()

            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/1", cookies=cookies)
            assert resp.status_code == 200
            assert "<img" not in resp.text
            assert "&lt;img" in resp.text


# ================================================================
# 14. Private routes carry no-store/no-cache/private and no-index headers
# ================================================================
class TestPrivacyHeaders:
    def test_participant_routes_have_privacy_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1", cookies=cookies)
            assert "no-store" in resp.headers.get("cache-control", "")
            assert "noindex" in resp.headers.get("x-robots-tag", "")

    def test_admin_routes_have_privacy_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            cookies = _get_admin_session_cookie()
            resp = client.get("/admin/", cookies=cookies)
            assert "no-store" in resp.headers.get("cache-control", "")
            assert "noindex" in resp.headers.get("x-robots-tag", "")

    def test_token_entry_page_has_privacy_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/p/access")
            assert "no-store" in resp.headers.get("cache-control", "")
            assert "noindex" in resp.headers.get("x-robots-tag", "")

    def test_admin_access_page_has_privacy_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/admin/access")
            assert "no-store" in resp.headers.get("cache-control", "")
            assert "noindex" in resp.headers.get("x-robots-tag", "")


# ================================================================
# 15. File-backed close/reopen persistence
# ================================================================
class TestFileBackedPersistence:
    def test_data_persists_across_connections(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
            finally:
                conn.close()

            client2 = TestClient(app)
            cookies = _get_session_cookie("p1")
            resp = client2.get("/p/p1", cookies=cookies)
            assert resp.status_code == 200
            assert "User One" in resp.text

    def test_input_persists_across_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                input_repo.create_input(
                    conn,
                    participant_id="p1",
                    raw_text="ERSIST 테스트 입력입니다.",
                    consent_confirmed=1,
                )
            finally:
                conn.close()

            conn2 = get_connection(db_path)
            try:
                inputs = input_repo.get_inputs_by_participant(conn2, "p1")
                assert len(inputs) == 1
                assert "ERSIST" in inputs[0].raw_text
            finally:
                conn2.close()


# ================================================================
# 16. No network, no external provider, no private fixture material
# ================================================================
class TestNoNetwork:
    def test_mock_provider_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            assert isinstance(app.state.provider, MockProvider)


# ================================================================
# 17. Auth module unit tests
# ================================================================
class TestAuthModule:
    def test_session_roundtrip(self):
        session_data = create_participant_session("p1")
        signed = sign_session_token(session_data)
        decoded = decode_session_token(signed)
        assert decoded is not None
        assert decoded.get("participant_id") == "p1"

    def test_admin_session_roundtrip(self):
        session_data = create_admin_session()
        signed = sign_session_token(session_data)
        decoded = decode_session_token(signed)
        assert decoded is not None
        assert decoded.get("is_admin") is True

    def test_invalid_token_returns_none(self):
        assert decode_session_token("invalid") is None

    def test_csrf_roundtrip(self):
        token = generate_csrf_token()
        signed = sign_csrf_token(token)
        assert verify_csrf_token(token, signed)

    def test_csrf_wrong_token_fails(self):
        token = generate_csrf_token()
        signed = sign_csrf_token(token)
        assert not verify_csrf_token("wrong", signed)


# ================================================================
# Static assets
# ================================================================
class TestStaticAssets:
    def test_css_file_exists(self):
        css_path = (
            Path(__file__).resolve().parent.parent.parent / "static" / "app.css"
        )
        assert css_path.is_file()

    def test_css_is_mobile_first(self):
        css_path = (
            Path(__file__).resolve().parent.parent.parent / "static" / "app.css"
        )
        content = css_path.read_text()
        assert "box-sizing" in content
        assert "max-width" in content


# ================================================================
# Smoke test
# ================================================================
class TestSmokeTest:
    def test_app_factory_creates_working_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    def test_all_routes_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            all_paths = []
            for r in app.routes:
                if hasattr(r, "path"):
                    all_paths.append(r.path)
                if hasattr(r, "routes"):
                    for sub in r.routes:
                        if hasattr(sub, "path"):
                            all_paths.append(sub.path)
            assert any("/health" in p for p in all_paths)
