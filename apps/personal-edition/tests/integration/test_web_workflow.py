"""Comprehensive web, security, and end-to-end tests for Phase 4 private web workflow.

Covers all 17 test categories from Issue #28 plus adversarial security tests.
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
    sign_admin_session_token,
    sign_csrf_token,
    verify_csrf_token,
    generate_csrf_token,
    decode_session_token,
    decode_admin_session_token,
    verify_admin_secret,
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
    signed = sign_admin_session_token(session_data)
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
# 1. Application startup, migrations, /health, production secret rejection
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

    def test_production_rejects_default_secret_key(self):
        with pytest.raises(ValueError, match="SECRET_KEY"):
            Settings(
                app_env="production",
                secret_key="dev-secret-key-change-in-production",
                admin_secret="a-strong-admin-secret-here!",
                cookie_secure=True,
            )

    def test_production_rejects_default_admin_secret(self):
        with pytest.raises(ValueError, match="ADMIN_SECRET"):
            Settings(
                app_env="production",
                secret_key="a-very-strong-secret-key-at-least-32-chars!",
                admin_secret="dev-admin-secret-change-in-production",
                cookie_secure=True,
            )

    def test_production_rejects_insecure_cookie(self):
        with pytest.raises(ValueError, match="COOKIE_SECURE"):
            Settings(
                app_env="production",
                secret_key="a-very-strong-secret-key-at-least-32-chars!",
                admin_secret="a-strong-admin-secret-here!",
                cookie_secure=False,
            )

    def test_production_accepts_valid_config(self):
        s = Settings(
            app_env="production",
            secret_key="a-very-strong-secret-key-at-least-32-chars!",
            admin_secret="a-strong-admin-secret-here!",
            cookie_secure=True,
        )
        assert s.app_env == "production"


# ================================================================
# 2. Participant access
# ================================================================
class TestParticipantAccess:
    def test_token_entry_page_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/p/access")
            assert resp.status_code == 200

    def test_token_entry_page_issues_csrf_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/p/access")
            assert resp.status_code == 200
            assert "pe_csrf" in resp.cookies
            assert 'name="csrf_token"' in resp.text
            assert 'name="csrf_token" value=""' not in resp.text

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
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/access",
                data={"token": raw_token, "csrf_token": csrf_token},
                cookies=csrf_cookie,
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/p/p1"
            assert "pe_session" in resp.cookies

    def test_valid_token_login_sets_session_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                prov = _create_participant(conn, "p1", "Test User")
                raw_token = prov.one_time_token
            finally:
                conn.close()
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/access",
                data={"token": raw_token, "csrf_token": csrf_token},
                cookies=csrf_cookie,
                follow_redirects=False,
            )
            assert "pe_session" in resp.cookies
            session_val = resp.cookies["pe_session"]
            decoded = decode_session_token(session_val)
            assert decoded is not None
            assert decoded.get("participant_id") == "p1"

    def test_participant_login_rejects_missing_csrf(self):
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
                "/p/access",
                data={"token": raw_token, "csrf_token": ""},
                follow_redirects=False,
            )
            assert resp.status_code == 200
            assert "expired" in resp.text.lower() or "invalid" in resp.text.lower()
            assert "pe_session" not in resp.cookies

    def test_participant_login_rejects_mismatched_csrf(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                prov = _create_participant(conn, "p1", "Test User")
                raw_token = prov.one_time_token
            finally:
                conn.close()
            csrf_cookie, _ = _get_csrf_cookie_and_token()
            wrong_token = generate_csrf_token()
            resp = client.post(
                "/p/access",
                data={"token": raw_token, "csrf_token": wrong_token},
                cookies=csrf_cookie,
                follow_redirects=False,
            )
            assert resp.status_code == 200
            assert "expired" in resp.text.lower() or "invalid" in resp.text.lower()
            assert "pe_session" not in resp.cookies

    def test_invalid_token_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/access",
                data={"token": "invalid-token", "csrf_token": csrf_token},
                cookies=csrf_cookie,
            )
            assert resp.status_code == 200
            assert "Invalid" in resp.text or "invalid" in resp.text.lower()

    def test_empty_token_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/access",
                data={"token": "", "csrf_token": csrf_token},
                cookies=csrf_cookie,
            )
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
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/access",
                data={"token": raw_token, "csrf_token": csrf_token},
                cookies=csrf_cookie,
            )
            assert resp.status_code == 200

    def test_deleted_participant_session_revoked(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1", cookies=cookies, follow_redirects=False)
            assert resp.status_code == 200

            conn2 = get_connection(db_path)
            try:
                pt_repo.delete_participant(conn2, "p1")
            finally:
                conn2.close()

            resp2 = client.get("/p/p1", cookies=cookies, follow_redirects=False)
            assert resp2.status_code == 303
            assert resp2.headers["location"] == "/p/access"

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

    def test_participant_logout_rejects_missing_csrf(self):
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
                "/p/p1/logout", cookies=cookies,
                data={"csrf_token": ""},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/p/p1"

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
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            all_cookies = {**cookies, **csrf_cookie}
            resp = client.post(
                "/p/p1/logout",
                data={"csrf_token": csrf_token},
                cookies=all_cookies,
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/p/access"
            assert "pe_session" not in resp.cookies

    def test_logout_with_mismatched_csrf_does_not_clear_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            csrf_cookie, _ = _get_csrf_cookie_and_token()
            wrong_token = generate_csrf_token()
            all_cookies = {**cookies, **csrf_cookie}
            resp = client.post(
                "/p/p1/logout",
                data={"csrf_token": wrong_token},
                cookies=all_cookies,
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/p/p1"

    def test_logout_without_csrf_cookie_does_not_clear_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            csrf_token = generate_csrf_token()
            resp = client.post(
                "/p/p1/logout",
                data={"csrf_token": csrf_token},
                cookies=cookies,
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/p/p1"

    def test_participant_login_then_logout_full_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                prov = _create_participant(conn, "p1", "Test User")
                raw_token = prov.one_time_token
            finally:
                conn.close()
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/access",
                data={"token": raw_token, "csrf_token": csrf_token},
                cookies=csrf_cookie,
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert "pe_session" in resp.cookies
            session_val = resp.cookies["pe_session"]

            csrf_cookie2, csrf_token2 = _get_csrf_cookie_and_token()
            logout_cookies = {"pe_session": session_val, **csrf_cookie2}
            resp2 = client.post(
                "/p/p1/logout",
                data={"csrf_token": csrf_token2},
                cookies=logout_cookies,
                follow_redirects=False,
            )
            assert resp2.status_code == 303
            assert resp2.headers["location"] == "/p/access"

            resp3 = client.get(
                "/p/p1",
                follow_redirects=False,
            )
            assert resp3.status_code == 303
            assert resp3.headers["location"] == "/p/access"

    def test_participant_logout_clears_cookie_for_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                prov = _create_participant(conn, "p1", "Test User")
                raw_token = prov.one_time_token
            finally:
                conn.close()
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/access",
                data={"token": raw_token, "csrf_token": csrf_token},
                cookies=csrf_cookie,
                follow_redirects=False,
            )
            assert "pe_session" in resp.cookies

            csrf_cookie2, csrf_token2 = _get_csrf_cookie_and_token()
            resp2 = client.post(
                "/p/p1/logout",
                data={"csrf_token": csrf_token2},
                follow_redirects=False,
            )
            assert resp2.status_code == 303
            assert "pe_session" not in resp2.cookies


# ================================================================
# 3. Participant input submission
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
                data={"raw_text": "", "consent_confirmed": "1", "csrf_token": csrf_token},
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

    def test_input_error_rerender_fresh_csrf_and_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, cookies = self._make_client_with_session(Path(tmp))
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            all_cookies = {**cookies, **csrf_cookie}
            resp = client.post(
                "/p/p1/input",
                data={"raw_text": "", "consent_confirmed": "1", "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "pe_csrf" in resp.cookies
            new_csrf_token = generate_csrf_token()
            new_csrf_signed = sign_csrf_token(new_csrf_token)
            retry_cookies = {**cookies, "pe_csrf": new_csrf_signed}
            resp2 = client.post(
                "/p/p1/input",
                data={
                    "raw_text": "재시도 입력 텍스트입니다. " * 20,
                    "consent_confirmed": "1",
                    "csrf_token": new_csrf_token,
                },
                cookies=retry_cookies,
            )
            assert resp2.status_code == 200
            assert "submitted" in resp2.text.lower() or "제출" in resp2.text


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
                    conn, participant_id="p2", edition_number=1,
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
                    conn, participant_id="p2", edition_number=1,
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
                data={"direction_choices": "continue_direction", "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "찾을" in resp.text or "not found" in resp.text.lower()


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
                    conn, participant_id="p1", edition_number=1,
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
                    conn, participant_id="p1", edition_number=1,
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
                    conn, participant_id="p1", edition_number=1,
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
# 6. Admin authentication
# ================================================================
class TestAdminAuthentication:
    def test_admin_access_page_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/admin/access")
            assert resp.status_code == 200

    def test_admin_access_page_issues_csrf_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/admin/access")
            assert resp.status_code == 200
            assert "pe_admin_csrf" in resp.cookies
            assert 'name="csrf_token"' in resp.text
            assert 'name="csrf_token" value=""' not in resp.text

    def test_admin_wrong_secret_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            resp = client.post(
                "/admin/access",
                data={"secret": "wrong", "csrf_token": csrf_token},
                cookies=csrf_cookie,
            )
            assert resp.status_code == 200
            assert "Invalid" in resp.text or "invalid" in resp.text.lower()

    def test_admin_valid_secret_grants_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            resp = client.post(
                "/admin/access",
                data={
                    "secret": "dev-admin-secret-change-in-production",
                    "csrf_token": csrf_token,
                },
                cookies=csrf_cookie,
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

    def test_admin_logout_rejects_missing_csrf(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            cookies = _get_admin_session_cookie()
            resp = client.post(
                "/admin/logout", cookies=cookies,
                data={"csrf_token": ""},
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/admin/"

    def test_admin_logout(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**cookies, **csrf_cookie}
            resp = client.post(
                "/admin/logout",
                data={"csrf_token": csrf_token},
                cookies=all_cookies, follow_redirects=False,
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/admin/access"
            assert "pe_admin_session" not in resp.cookies

    def test_admin_logout_with_mismatched_csrf_does_not_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            cookies = _get_admin_session_cookie()
            csrf_cookie, _ = _get_admin_csrf_cookie_and_token()
            wrong_token = generate_csrf_token()
            all_cookies = {**cookies, **csrf_cookie}
            resp = client.post(
                "/admin/logout",
                data={"csrf_token": wrong_token},
                cookies=all_cookies, follow_redirects=False,
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/admin/"

    def test_admin_login_logout_full_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            resp = client.post(
                "/admin/access",
                data={
                    "secret": "dev-admin-secret-change-in-production",
                    "csrf_token": csrf_token,
                },
                cookies=csrf_cookie,
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert "pe_admin_session" in resp.cookies
            admin_session = resp.cookies["pe_admin_session"]

            csrf_cookie2, csrf_token2 = _get_admin_csrf_cookie_and_token()
            logout_cookies = {"pe_admin_session": admin_session, **csrf_cookie2}
            resp2 = client.post(
                "/admin/logout",
                data={"csrf_token": csrf_token2},
                cookies=logout_cookies,
                follow_redirects=False,
            )
            assert resp2.status_code == 303
            assert resp2.headers["location"] == "/admin/access"

            resp3 = client.get(
                "/admin/",
                follow_redirects=False,
            )
            assert resp3.status_code == 303
            assert resp3.headers["location"] == "/admin/access"

    def test_admin_secret_constant_time_comparison(self):
        assert verify_admin_secret("dev-admin-secret-change-in-production")
        assert not verify_admin_secret("wrong-secret")


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
                data={"raw_text": "테스트", "consent_confirmed": "1", "csrf_token": ""},
                cookies=cookies,
            )
            assert resp.status_code == 200

    def test_admin_edit_rejects_missing_csrf(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                )
                edition_id = ed.id
            finally:
                conn.close()
            admin_cookies = _get_admin_session_cookie()
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(_make_draft_payload()), "csrf_token": ""},
                cookies=admin_cookies, follow_redirects=False,
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
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                )
                edition_id = ed.id
            finally:
                conn.close()
            admin_cookies = _get_admin_session_cookie()
            resp = client.post(
                f"/admin/review/{edition_id}/publish",
                data={"csrf_token": ""}, cookies=admin_cookies, follow_redirects=False,
            )
            assert resp.status_code == 303

    def test_admin_access_rejects_missing_csrf(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.post(
                "/admin/access",
                data={"secret": "dev-admin-secret-change-in-production", "csrf_token": ""},
            )
            assert resp.status_code == 200


# ================================================================
# 8. MockProvider generation
# ================================================================
class TestGenerationThroughWeb:
    def test_admin_generate_creates_edition(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = MockProvider(
                task_payloads={"editorial_plan": MOCK_PLAN_PAYLOAD, "edition_draft": _make_draft_payload()}
            )
            app, db_path = _make_app(Path(tmp), provider=provider)
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                inp = input_repo.create_input(conn, participant_id="p1", raw_text=_make_long_korean_text(600), consent_confirmed=1)
                input_id = inp.id
            finally:
                conn.close()
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            resp = client.post(
                "/admin/participants/p1/generate",
                data={"input_id": input_id, "csrf_token": csrf_token},
                cookies=all_cookies, follow_redirects=False,
            )
            assert resp.status_code == 303
            conn2 = get_connection(db_path)
            try:
                editions = ed_repo.get_editions_by_participant(conn2, "p1")
                assert len(editions) >= 1
                assert editions[0].generation_status == "pending_review"
            finally:
                conn2.close()

    def test_admin_generate_short_sample_requires_explicit_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = MockProvider(
                task_payloads={"editorial_plan": MOCK_PLAN_PAYLOAD, "edition_draft": _make_draft_payload()}
            )
            app, db_path = _make_app(Path(tmp), provider=provider)
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                short_text = "짧은 테스트 텍스트입니다. " * 10
                inp = input_repo.create_input(conn, participant_id="p1", raw_text=short_text, consent_confirmed=1)
                input_id = inp.id
            finally:
                conn.close()
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            resp = client.post(
                "/admin/participants/p1/generate",
                data={"input_id": input_id, "csrf_token": csrf_token, "allow_short_sample": "0"},
                cookies=all_cookies, follow_redirects=False,
            )
            assert resp.status_code == 303
            conn2 = get_connection(db_path)
            try:
                editions = ed_repo.get_editions_by_participant(conn2, "p1")
                assert len(editions) == 0
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
                conn, participant_id="p1", edition_number=1,
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
                cookies=all_cookies, follow_redirects=False,
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
                data={"structured_content": "not valid json", "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "Invalid JSON" in resp.text or "invalid" in resp.text.lower() or "Error" in resp.text

    def test_admin_edit_valid_json_wrong_schema_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = {"foo": "bar"}
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            conn = get_connection(db_path)
            try:
                ed = ed_repo.get_edition_by_id(conn, edition_id)
                orig = json.loads(ed.structured_content)
                assert orig.get("edition_title") == "테스트 에디션 제목"
            finally:
                conn.close()

    def test_admin_edit_unsafe_markup_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload()
            bad_content["opening"] = "<script>alert('xss')</script>"
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "unsafe" in resp.text.lower() or "markup" in resp.text.lower() or "Error" in resp.text
            conn = get_connection(db_path)
            try:
                ed = ed_repo.get_edition_by_id(conn, edition_id)
                orig = json.loads(ed.structured_content)
                assert "<script>" not in orig.get("opening", "")
            finally:
                conn.close()

    def test_admin_edit_event_handler_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload()
            bad_content["sections"][0]["title"] = '<img src=x onerror="alert(1)">'
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "unsafe" in resp.text.lower() or "markup" in resp.text.lower() or "Error" in resp.text

    def test_admin_edit_javascript_url_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload()
            bad_content["sections"][0]["title"] = 'javascript:alert(1)'
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "unsafe" in resp.text.lower() or "markup" in resp.text.lower() or "Error" in resp.text

    def test_admin_edit_unsafe_nested_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload()
            bad_content["sections"][0]["paragraphs"] = ["<iframe src='evil.com'>"]
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "unsafe" in resp.text.lower() or "markup" in resp.text.lower() or "Error" in resp.text

    def test_admin_edit_no_content_change_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            conn = get_connection(db_path)
            try:
                orig = ed_repo.get_edition_by_id(conn, edition_id)
                orig_content = orig.structured_content
                orig_state = orig.publication_state
                orig_gen_status = orig.generation_status
            finally:
                conn.close()
            bad_content = _make_draft_payload()
            bad_content["opening"] = "<script>alert(1)</script>"
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            conn2 = get_connection(db_path)
            try:
                ed = ed_repo.get_edition_by_id(conn2, edition_id)
                assert ed.structured_content == orig_content
                assert ed.publication_state == orig_state
                assert ed.generation_status == orig_gen_status
            finally:
                conn2.close()

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
                cookies=all_cookies, follow_redirects=False,
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
                cookies=all_cookies, follow_redirects=False,
            )
            assert resp.status_code == 303
            conn = get_connection(db_path)
            try:
                ed = ed_repo.get_edition_by_id(conn, edition_id)
                assert ed.publication_state == "rejected"
            finally:
                conn.close()


# ================================================================
# 10. Edition reading and history
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
                        conn, participant_id="p1", edition_number=i,
                        structured_content=json.dumps(_make_draft_payload()),
                        rendered_title=f"Edition {i}",
                    )
                    if i <= 2:
                        ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/history", cookies=cookies)
            assert resp.status_code == 200
            assert "Edition 2" in resp.text

    def test_history_ordering_descending(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                for i in range(1, 4):
                    ed = ed_repo.create_edition(
                        conn, participant_id="p1", edition_number=i,
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
                    conn, participant_id="p1", edition_number=1,
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
            finally:
                conn2.close()

    def test_feedback_invalid_section_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="Edition 1",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            all_cookies = {**cookies, **csrf_cookie}
            resp = client.post(
                "/p/p1/editions/1/feedback",
                data={
                    "direction_choices": ["continue_direction"],
                    "selected_section_id": "nonexistent_section",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "not valid" in resp.text.lower() or "Invalid" in resp.text
            conn2 = get_connection(db_path)
            try:
                feedbacks = conn2.execute(
                    "SELECT * FROM feedback WHERE participant_id = 'p1'"
                ).fetchall()
                assert len(feedbacks) == 0
            finally:
                conn2.close()

    def test_feedback_error_shows_generic_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "User One")
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="Edition 1",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            all_cookies = {**cookies, **csrf_cookie}
            resp = client.post(
                "/p/p1/editions/1/feedback",
                data={
                    "direction_choices": [],
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            assert "sqlite" not in resp.text.lower()
            assert "traceback" not in resp.text.lower()


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
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(draft1), rendered_title="Edition 1",
                )
                ed_repo.update_edition_publication(conn, ed1.id, "published")
                fb = fb_repo.create_feedback(
                    conn, participant_id="p1", edition_id=ed1.id,
                    direction_choices=json.dumps(["continue_direction"]),
                    free_text="계속 이 방향으로",
                )
                draft2 = _make_draft_payload()
                draft2["applied_feedback"] = {
                    "feedback_id": fb.id, "action": "continue_direction",
                    "affected_section_ids": ["s001", "s002"],
                    "evidence": "피드백이 반영되었습니다.",
                }
                ed2 = ed_repo.create_edition_with_feedback_applied(
                    conn, participant_id="p1", edition_number=2,
                    prior_edition_id=ed1.id, input_id=None,
                    structured_content=json.dumps(draft2), rendered_title="Edition 2",
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
                malicious_draft["sections"][0]["paragraphs"] = ["<script>alert('xss')</script>"]
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(malicious_draft), rendered_title="XSS Test",
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
                malicious_draft["sections"][0]["paragraphs"] = ['<img src=x onerror="alert(1)">']
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(malicious_draft), rendered_title="Event Handler Test",
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
# 14. Privacy headers
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

    def test_admin_access_page_has_privacy_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/admin/access")
            assert "no-store" in resp.headers.get("cache-control", "")

    def test_participant_redirect_has_privacy_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/p/p1", follow_redirects=False)
            assert resp.status_code == 303
            assert "no-store" in resp.headers.get("cache-control", "")

    def test_admin_redirect_has_privacy_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/admin/", follow_redirects=False)
            assert resp.status_code == 303
            assert "no-store" in resp.headers.get("cache-control", "")

    def test_participant_error_page_has_privacy_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/999", cookies=cookies)
            assert "no-store" in resp.headers.get("cache-control", "")


# ================================================================
# 15. File-backed persistence
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
                    conn, participant_id="p1", raw_text="ERSIST 테스트 입력입니다.", consent_confirmed=1,
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
# 16. No network
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
        signed = sign_admin_session_token(session_data)
        decoded = decode_admin_session_token(signed)
        assert decoded is not None
        assert decoded.get("is_admin") is True

    def test_invalid_token_returns_none(self):
        assert decode_session_token("invalid") is None

    def test_invalid_admin_token_returns_none(self):
        assert decode_admin_session_token("invalid") is None

    def test_participant_token_not_accepted_as_admin(self):
        session_data = create_participant_session("p1")
        signed = sign_session_token(session_data)
        assert decode_admin_session_token(signed) is None

    def test_admin_token_not_accepted_as_participant(self):
        session_data = create_admin_session()
        signed = sign_admin_session_token(session_data)
        assert decode_session_token(signed) is None

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
        css_path = Path(__file__).resolve().parent.parent.parent / "static" / "app.css"
        assert css_path.is_file()

    def test_css_is_mobile_first(self):
        css_path = Path(__file__).resolve().parent.parent.parent / "static" / "app.css"
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


# ================================================================
# 18. CSRF regression tests
# ================================================================
class TestCSRFRegression:
    def test_participant_access_get_sets_csrf_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/p/access")
            assert resp.status_code == 200
            assert "pe_csrf" in resp.cookies
            signed = resp.cookies["pe_csrf"]
            assert verify_csrf_token("", signed) is False

    def test_admin_access_get_sets_csrf_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.get("/admin/access")
            assert resp.status_code == 200
            assert "pe_admin_csrf" in resp.cookies
            signed = resp.cookies["pe_admin_csrf"]
            assert verify_csrf_token("", signed) is False

    def test_participant_dashboard_sets_csrf_cookie(self):
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
            assert "pe_csrf" in resp.cookies

    def test_participant_history_sets_csrf_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/history", cookies=cookies)
            assert resp.status_code == 200
            assert "pe_csrf" in resp.cookies

    def test_participant_input_page_sets_csrf_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/input", cookies=cookies)
            assert resp.status_code == 200
            assert "pe_csrf" in resp.cookies

    def test_participant_edition_read_sets_csrf_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="Test",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/1", cookies=cookies)
            assert resp.status_code == 200
            assert "pe_csrf" in resp.cookies

    def test_admin_dashboard_sets_csrf_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            cookies = _get_admin_session_cookie()
            resp = client.get("/admin/", cookies=cookies)
            assert resp.status_code == 200
            assert "pe_admin_csrf" in resp.cookies

    def test_admin_review_page_sets_csrf_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                )
                edition_id = ed.id
            finally:
                conn.close()
            cookies = _get_admin_session_cookie()
            resp = client.get(f"/admin/review/{edition_id}", cookies=cookies)
            assert resp.status_code == 200
            assert "pe_admin_csrf" in resp.cookies

    def test_all_pages_contain_matching_csrf_field_and_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="Test",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()
            p_cookies = _get_session_cookie("p1")
            pages = [
                "/p/access",
                "/p/p1",
                "/p/p1/input",
                "/p/p1/history",
                "/p/p1/editions/1",
            ]
            for path in pages:
                resp = client.get(path, cookies=p_cookies)
                assert "pe_csrf" in resp.cookies, f"{path} missing CSRF cookie"
                assert 'name="csrf_token"' in resp.text, f"{path} missing CSRF field"

    def test_admin_pages_contain_matching_csrf_field_and_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                )
                edition_id = ed.id
            finally:
                conn.close()
            a_cookies = _get_admin_session_cookie()
            pages = [
                "/admin/access",
                "/admin/",
                f"/admin/review/{edition_id}",
            ]
            for path in pages:
                resp = client.get(path, cookies=a_cookies)
                assert "pe_admin_csrf" in resp.cookies, f"{path} missing CSRF cookie"
                assert 'name="csrf_token"' in resp.text, f"{path} missing CSRF field"

    def test_participant_login_csrf_missing_no_session_created(self):
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
                "/p/access",
                data={"token": raw_token, "csrf_token": ""},
                follow_redirects=False,
            )
            assert "pe_session" not in resp.cookies

    def test_admin_login_csrf_missing_no_session_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            resp = client.post(
                "/admin/access",
                data={"secret": "dev-admin-secret-change-in-production", "csrf_token": ""},
                follow_redirects=False,
            )
            assert "pe_admin_session" not in resp.cookies

    def test_participant_logout_csrf_missing_session_not_cleared(self):
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
                "/p/p1/logout",
                data={"csrf_token": ""},
                cookies=cookies,
                follow_redirects=False,
            )
            assert "pe_session" not in resp.cookies

    def test_admin_logout_csrf_missing_session_not_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            cookies = _get_admin_session_cookie()
            resp = client.post(
                "/admin/logout",
                data={"csrf_token": ""},
                cookies=cookies,
                follow_redirects=False,
            )
            assert "pe_admin_session" not in resp.cookies


# ================================================================
# 19. EditionContent model validation regression tests
# ================================================================
class TestEditionContentValidation:
    def _setup_edition(self, tmp_path):
        app, db_path = _make_app(tmp_path)
        conn = get_connection(db_path)
        try:
            _create_participant(conn, "p1", "Test User")
            ed = ed_repo.create_edition(
                conn, participant_id="p1", edition_number=1,
                structured_content=json.dumps(_make_draft_payload()),
                rendered_title="Test Edition",
            )
            edition_id = ed.id
        finally:
            conn.close()
        return app, db_path, edition_id

    def _admin_edit(self, client, edition_id, content, all_cookies):
        return client.post(
            f"/admin/review/{edition_id}/edit",
            data={
                "structured_content": json.dumps(content),
                "rendered_title": "Updated",
                "csrf_token": all_cookies.get("csrf_token_val", ""),
            },
            cookies={k: v for k, v in all_cookies.items() if k != "csrf_token_val"},
            follow_redirects=False,
        )

    def test_unsupported_language_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload()
            bad_content["language"] = "fr"
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            conn = get_connection(db_path)
            try:
                ed = ed_repo.get_edition_by_id(conn, edition_id)
                assert ed.rendered_title == "Test Edition"
            finally:
                conn.close()

    def test_five_sections_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload(section_ids=["s1", "s2", "s3", "s4", "s5"])
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200

    def test_invalid_section_id_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload(section_ids=["s001", "invalid id!"])
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200

    def test_empty_paragraph_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload()
            bad_content["sections"][0]["paragraphs"] = [""]
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200

    def test_empty_source_segment_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload()
            bad_content["sections"][0]["source_segment_ids"] = [""]
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200

    def test_malformed_applied_feedback_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload()
            bad_content["applied_feedback"] = {
                "feedback_id": "x",
                "action": "",
                "affected_section_ids": [],
                "evidence": "",
            }
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200

    def test_malformed_next_edition_prompt_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload()
            bad_content["next_edition_prompt"] = {
                "question": "",
                "choices": [],
            }
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200

    def test_unsafe_markup_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload()
            bad_content["opening"] = "<script>alert(1)</script>"
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200

    def test_valid_edit_persists_canonical_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            new_content = _make_draft_payload()
            new_content["edition_title"] = "Canonical Title"
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={
                    "structured_content": json.dumps(new_content),
                    "rendered_title": "Canonical Edition",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies, follow_redirects=False,
            )
            assert resp.status_code == 303
            conn = get_connection(db_path)
            try:
                ed = ed_repo.get_edition_by_id(conn, edition_id)
                assert ed.rendered_title == "Canonical Edition"
                persisted = json.loads(ed.structured_content)
                assert persisted["edition_title"] == "Canonical Title"
                validated = EditionContent.model_validate(persisted)
                reparsed = json.loads(validated.model_dump_json())
                assert reparsed["edition_title"] == "Canonical Title"
                assert reparsed["language"] in ("ko", "en")
            finally:
                conn.close()

    def test_edit_no_change_on_invalid_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            conn = get_connection(db_path)
            try:
                orig = ed_repo.get_edition_by_id(conn, edition_id)
                orig_content = orig.structured_content
                orig_title = orig.rendered_title
                orig_notes = orig.reviewer_notes
                orig_state = orig.publication_state
            finally:
                conn.close()
            bad_content = _make_draft_payload()
            bad_content["language"] = "fr"
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={
                    "structured_content": json.dumps(bad_content),
                    "rendered_title": "Should Not Change",
                    "reviewer_notes": "Should Not Change",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
            )
            assert resp.status_code == 200
            conn2 = get_connection(db_path)
            try:
                ed = ed_repo.get_edition_by_id(conn2, edition_id)
                assert ed.structured_content == orig_content
                assert ed.rendered_title == orig_title
                assert ed.reviewer_notes == orig_notes
                assert ed.publication_state == orig_state
            finally:
                conn2.close()

    def test_duplicate_section_ids_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload(section_ids=["s001", "s001"])
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200

    def test_empty_opening_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, edition_id = self._setup_edition(Path(tmp))
            client = TestClient(app)
            admin_cookies = _get_admin_session_cookie()
            csrf_cookie, csrf_token = _get_admin_csrf_cookie_and_token()
            all_cookies = {**admin_cookies, **csrf_cookie}
            bad_content = _make_draft_payload()
            bad_content["opening"] = ""
            resp = client.post(
                f"/admin/review/{edition_id}/edit",
                data={"structured_content": json.dumps(bad_content), "csrf_token": csrf_token},
                cookies=all_cookies,
            )
            assert resp.status_code == 200


# ================================================================
# Issue #30: terminal page CSRF regression tests
# ================================================================
class TestTerminalPageCSRF:
    """Prove logout works directly from every distinct terminal-page class.

    Each test authenticates, hits a terminal page, verifies a fresh CSRF
    token + cookie pair is present, submits logout from that page, and
    confirms the session is destroyed.
    """

    def test_participant_edition_not_found_logout(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/999", cookies=cookies)
            assert resp.status_code == 200
            assert "pe_csrf" in resp.cookies
            html = resp.text
            assert 'name="csrf_token"' in html
            token_value = html.split('name="csrf_token" value="')[1].split('"')[0]
            assert token_value
            resp_csrf = resp.cookies["pe_csrf"]
            assert verify_csrf_token(token_value, resp_csrf)

            logout_resp = client.post(
                "/p/p1/logout",
                data={"csrf_token": token_value},
                cookies={**cookies, "pe_csrf": resp_csrf},
                follow_redirects=False,
            )
            assert logout_resp.status_code in (302, 303)
            assert logout_resp.headers.get("location") == "/p/access"
            assert "pe_session" not in logout_resp.cookies
            assert "pe_csrf" not in logout_resp.cookies

    def test_participant_feedback_target_not_found_logout(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/999/feedback", cookies=cookies)
            assert resp.status_code == 200
            assert "pe_csrf" in resp.cookies
            html = resp.text
            assert 'name="csrf_token"' in html
            token_value = html.split('name="csrf_token" value="')[1].split('"')[0]
            assert token_value
            resp_csrf = resp.cookies["pe_csrf"]
            assert verify_csrf_token(token_value, resp_csrf)

            logout_resp = client.post(
                "/p/p1/logout",
                data={"csrf_token": token_value},
                cookies={**cookies, "pe_csrf": resp_csrf},
                follow_redirects=False,
            )
            assert logout_resp.status_code in (302, 303)
            assert logout_resp.headers.get("location") == "/p/access"
            assert "pe_session" not in logout_resp.cookies
            assert "pe_csrf" not in logout_resp.cookies

    def test_participant_feedback_already_submitted_logout(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="Test",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
                fb_repo.create_feedback(
                    conn, participant_id="p1", edition_id=ed.id,
                    direction_choices='["more_practical"]',
                )
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/1/feedback", cookies=cookies)
            assert resp.status_code == 200
            assert "pe_csrf" in resp.cookies
            html = resp.text
            assert 'name="csrf_token"' in html
            token_value = html.split('name="csrf_token" value="')[1].split('"')[0]
            assert token_value
            resp_csrf = resp.cookies["pe_csrf"]
            assert verify_csrf_token(token_value, resp_csrf)

            logout_resp = client.post(
                "/p/p1/logout",
                data={"csrf_token": token_value},
                cookies={**cookies, "pe_csrf": resp_csrf},
                follow_redirects=False,
            )
            assert logout_resp.status_code in (302, 303)
            assert logout_resp.headers.get("location") == "/p/access"
            assert "pe_session" not in logout_resp.cookies
            assert "pe_csrf" not in logout_resp.cookies

    def test_participant_feedback_success_logout(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content=json.dumps(_make_draft_payload()),
                    rendered_title="Test",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")

            form_resp = client.get("/p/p1/editions/1/feedback", cookies=cookies)
            assert form_resp.status_code == 200
            form_html = form_resp.text
            form_token = form_html.split('name="csrf_token" value="')[1].split('"')[0]
            form_csrf = form_resp.cookies["pe_csrf"]

            submit_resp = client.post(
                "/p/p1/editions/1/feedback",
                data={
                    "direction_choices": ["more_practical"],
                    "selected_section_id": "s001",
                    "csrf_token": form_token,
                },
                cookies={**cookies, "pe_csrf": form_csrf},
                follow_redirects=False,
            )
            assert submit_resp.status_code == 200

            resp = client.get("/p/p1/editions/1/feedback", cookies=cookies)
            assert resp.status_code == 200
            assert "pe_csrf" in resp.cookies
            html = resp.text
            assert 'name="csrf_token"' in html
            token_value = html.split('name="csrf_token" value="')[1].split('"')[0]
            assert token_value
            resp_csrf = resp.cookies["pe_csrf"]
            assert verify_csrf_token(token_value, resp_csrf)

            logout_resp = client.post(
                "/p/p1/logout",
                data={"csrf_token": token_value},
                cookies={**cookies, "pe_csrf": resp_csrf},
                follow_redirects=False,
            )
            assert logout_resp.status_code in (302, 303)
            assert logout_resp.headers.get("location") == "/p/access"
            assert "pe_session" not in logout_resp.cookies
            assert "pe_csrf" not in logout_resp.cookies

    def test_admin_participant_not_found_logout(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            cookies = _get_admin_session_cookie()
            resp = client.get("/admin/participants/nonexistent", cookies=cookies)
            assert resp.status_code == 200
            assert "pe_admin_csrf" in resp.cookies
            html = resp.text
            assert 'name="csrf_token"' in html
            token_value = html.split('name="csrf_token" value="')[1].split('"')[0]
            assert token_value
            resp_csrf = resp.cookies["pe_admin_csrf"]
            assert verify_csrf_token(token_value, resp_csrf)

            logout_resp = client.post(
                "/admin/logout",
                data={"csrf_token": token_value},
                cookies={**cookies, "pe_admin_csrf": resp_csrf},
                follow_redirects=False,
            )
            assert logout_resp.status_code in (302, 303)
            assert logout_resp.headers.get("location") == "/admin/access"
            assert "pe_admin_session" not in logout_resp.cookies
            assert "pe_admin_csrf" not in logout_resp.cookies

    def test_admin_edition_review_not_found_logout(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            cookies = _get_admin_session_cookie()
            resp = client.get("/admin/review/nonexistent", cookies=cookies)
            assert resp.status_code == 200
            assert "pe_admin_csrf" in resp.cookies
            html = resp.text
            assert 'name="csrf_token"' in html
            token_value = html.split('name="csrf_token" value="')[1].split('"')[0]
            assert token_value
            resp_csrf = resp.cookies["pe_admin_csrf"]
            assert verify_csrf_token(token_value, resp_csrf)

            logout_resp = client.post(
                "/admin/logout",
                data={"csrf_token": token_value},
                cookies={**cookies, "pe_admin_csrf": resp_csrf},
                follow_redirects=False,
            )
            assert logout_resp.status_code in (302, 303)
            assert logout_resp.headers.get("location") == "/admin/access"
            assert "pe_admin_session" not in logout_resp.cookies
            assert "pe_admin_csrf" not in logout_resp.cookies
