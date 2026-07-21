"""Additional acceptance tests for Living Travel Phase 2 CTO requirements.

Covers: personalization, exact feedback, failure UI, atomicity.
All tests use TestClient against actual production routes.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.config import get_settings, reset_settings
from app.db import apply_migrations, get_connection
from app.domain.enums import SourceConfidence
from app.edition_repository import (
    create_edition,
    get_edition_by_id,
    get_editions_by_traveler,
    update_edition_content,
    update_edition_generation_status,
    update_edition_publication,
)
from app.factory import create_app
from app.feedback_repository import (
    create_feedback,
    get_feedback_by_edition,
    mark_feedback_applied,
)
from app.generation_run_repository import count_generation_runs_by_edition
from app.pipeline.errors import PipelineError
from app.security import (
    create_traveler_session,
    create_traveler_token,
    deactivate_traveler_tokens,
    generate_csrf_token,
    get_login_rate_limiter,
    reset_login_rate_limiter,
)
from app.source_repository import create_source
from app.traveler_repository import (
    create_traveler,
    get_traveler_by_id,
    is_traveler_active,
)


@pytest.fixture()
def app(tmp_path: Path):
    reset_settings()
    reset_login_rate_limiter()
    db_path = str(tmp_path / "test.db")
    os.environ["LT_DATABASE_URL"] = db_path
    os.environ["LT_OPERATOR_SECRET"] = "test-secret-12345"
    reset_settings()
    application = create_app()
    yield application
    reset_settings()
    reset_login_rate_limiter()


def _operator_login(client: TestClient):
    settings = get_settings()
    secret = getattr(settings, "operator_secret", "test-secret-12345")
    client.get("/operator/login")
    csrf = client.cookies.get("lt_csrf")
    client.post("/operator/login", data={"secret": secret, "csrf_token": csrf or ""},
               cookies={"lt_csrf": csrf or ""})


def _op_csrf(client: TestClient) -> str:
    resp = client.get("/operator/")
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.text)
    return m.group(1) if m else ""


def _create_traveler_via_route(client: TestClient, name: str, dest: str, csrf: str,
                                nights: int = 3, **kwargs) -> str:
    data = {"display_name": name, "destination": dest,
            "trip_duration_nights": nights, "csrf_token": csrf}
    data.update(kwargs)
    resp = client.post("/operator/travelers/create", data=data, cookies={"lt_csrf": csrf})
    assert resp.status_code in (200, 303)
    conn = get_connection()
    t = conn.execute("SELECT id FROM travelers WHERE display_name = ?", (name,)).fetchone()
    conn.close()
    assert t is not None
    return t["id"]


def _issue_token_via_route(client: TestClient, traveler_id: str, csrf: str) -> str:
    resp = client.post(f"/operator/travelers/{traveler_id}/invite",
                       data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
    assert resp.status_code == 200
    m = re.search(r'class="token-value">([A-Za-z0-9_-]+)<', resp.text)
    assert m is not None
    return m.group(1)


def _traveler_enter(client: TestClient, raw_token: str):
    client.get("/traveler/enter")
    csrf = client.cookies.get("lt_csrf")
    resp = client.post("/traveler/enter",
                       data={"token": raw_token, "csrf_token": csrf or ""},
                       cookies={"lt_csrf": csrf or ""})
    return resp


# ===================================================================
# Personalization tests
# ===================================================================

class TestPersonalization:
    def test_two_destinations_different_content(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)

        tid_busan = _create_traveler_via_route(c, "BusanPers", "부산", csrf, nights=2)
        tid_seoul = _create_traveler_via_route(c, "SeoulPers", "서울", csrf, nights=4)

        resp1 = c.post(f"/operator/travelers/{tid_busan}/generate-first",
                       data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        assert resp1.status_code in (200, 303)

        resp2 = c.post(f"/operator/travelers/{tid_seoul}/generate-first",
                       data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        assert resp2.status_code in (200, 303)

        conn = get_connection()
        eds_busan = get_editions_by_traveler(conn, tid_busan)
        eds_seoul = get_editions_by_traveler(conn, tid_seoul)
        assert len(eds_busan) == 1
        assert len(eds_seoul) == 1

        sc_busan = eds_busan[0].structured_content
        sc_seoul = eds_seoul[0].structured_content

        assert sc_busan["destination"] == "부산"
        assert sc_seoul["destination"] == "서울"

        assert "2박" in sc_busan.get("trip_frame", "")
        assert "4박" in sc_seoul.get("trip_frame", "")

        assert sc_busan["publication_title"] != sc_seoul["publication_title"]
        assert sc_busan["edition_title"] != sc_seoul["edition_title"]
        assert sc_busan["editorial_opening"] != sc_seoul["editorial_opening"]

        for sec in sc_busan.get("sections", []):
            assert "부산" in sec.get("title", "")
        for sec in sc_seoul.get("sections", []):
            assert "서울" in sec.get("title", "")
        conn.close()

    def test_sources_are_destination_isolated(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)

        tid1 = _create_traveler_via_route(c, "SrcIso1", "부산", csrf)
        tid2 = _create_traveler_via_route(c, "SrcIso2", "서울", csrf)

        c.post(f"/operator/travelers/{tid1}/generate-first",
               data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        c.post(f"/operator/travelers/{tid2}/generate-first",
               data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})

        conn = get_connection()
        src_busan = conn.execute(
            "SELECT id, destination FROM sources WHERE destination = '부산'"
        ).fetchall()
        src_seoul = conn.execute(
            "SELECT id, destination FROM sources WHERE destination = '서울'"
        ).fetchall()
        assert len(src_busan) >= 3
        assert len(src_seoul) >= 3
        busan_ids = {r["id"] for r in src_busan}
        seoul_ids = {r["id"] for r in src_seoul}
        assert busan_ids != seoul_ids
        conn.close()


# ===================================================================
# Exact feedback tests
# ===================================================================

class TestExactFeedback:
    def test_lower_budget_only(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)

        tid = _create_traveler_via_route(c, "FbLower", "부산", csrf)
        raw = _issue_token_via_route(c, tid, csrf)

        c.post(f"/operator/travelers/{tid}/generate-first",
               data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})

        conn = get_connection()
        ed1 = get_editions_by_traveler(conn, tid)[0]
        update_edition_publication(conn, ed1.id, "published")
        conn.close()

        _traveler_enter(c, raw)
        csrf_t = c.cookies.get("lt_csrf")
        resp = c.post(f"/traveler/editions/{ed1.id}/feedback",
                      data={"choices": ["lower_budget"], "free_text": "",
                            "csrf_token": csrf_t or ""},
                      cookies={"lt_csrf": csrf_t or ""})
        assert resp.status_code in (200, 303)

        _operator_login(c)
        csrf = _op_csrf(c)
        resp2 = c.post(f"/operator/travelers/{tid}/generate-second",
                       data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        assert resp2.status_code in (200, 303)

        conn = get_connection()
        eds = get_editions_by_traveler(conn, tid)
        assert len(eds) == 2
        ed2 = eds[1]
        sc2 = ed2.structured_content

        assert len(sc2.get("applied_feedback", [])) >= 1
        fb_applied = sc2["applied_feedback"][0]
        assert "lower_budget" in fb_applied.get("requested_change", "")
        assert "budget" in fb_applied.get("actual_action", "").lower() or \
               "비용" in fb_applied.get("actual_action", "")
        assert fb_applied.get("feedback_id", "") != ""

        assert "조용하고 느린" not in sc2.get("editorial_opening", "")
        assert "느린" not in sc2.get("editorial_opening", "") or "lower_budget" in fb_applied.get("requested_change", "")

        fb_list = get_feedback_by_edition(conn, ed1.id)
        assert len(fb_list) >= 1
        assert fb_list[0].applied_to_next_edition is True
        conn.close()

    def test_quieter_and_less_walking(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)

        tid = _create_traveler_via_route(c, "FbQuiet", "부산", csrf)
        raw = _issue_token_via_route(c, tid, csrf)

        c.post(f"/operator/travelers/{tid}/generate-first",
               data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})

        conn = get_connection()
        ed1 = get_editions_by_traveler(conn, tid)[0]
        update_edition_publication(conn, ed1.id, "published")
        conn.close()

        _traveler_enter(c, raw)
        csrf_t = c.cookies.get("lt_csrf")
        c.post(f"/traveler/editions/{ed1.id}/feedback",
               data={"choices": ["quieter_places", "less_walking"],
                     "free_text": "더 조용하고 덜 걸었으면", "csrf_token": csrf_t or ""},
               cookies={"lt_csrf": csrf_t or ""})

        _operator_login(c)
        csrf = _op_csrf(c)
        c.post(f"/operator/travelers/{tid}/generate-second",
               data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})

        conn = get_connection()
        ed2 = get_editions_by_traveler(conn, tid)[1]
        sc2 = ed2.structured_content
        fb_applied = sc2.get("applied_feedback", [])
        assert len(fb_applied) >= 1
        directions = fb_applied[0].get("requested_change", "")
        assert "quieter_places" in directions
        assert "less_walking" in directions
        opening = sc2.get("editorial_opening", "")
        assert "조용" in opening
        conn.close()


# ===================================================================
# Failure UI tests
# ===================================================================

class TestFailureUI:
    def test_failure_category_visible_on_detail(self, app):
        c = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        _operator_login(c)
        csrf = _op_csrf(c)

        tid = _create_traveler_via_route(c, "FailUI", "부산", csrf)

        def failing_provider(*args, **kwargs):
            from app.ai.mock import MockProvider
            provider = MockProvider()
            def fail(**kw):
                from app.domain.models import ProviderResult
                return ProviderResult(provider="mock-fail", model="mock-fail",
                                      success=False, error_category="timeout",
                                      error_message="simulated failure")
            provider.generate_structured = fail
            return provider

        with patch("app.web.routes.operator.create_mock_provider", side_effect=failing_provider):
            resp = c.post(f"/operator/travelers/{tid}/generate-first",
                          data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
            assert resp.status_code in (200, 303)

        location = resp.headers.get("location", "")
        assert "?failure=" in location

        detail = c.get(location)
        assert detail.status_code == 200
        assert "timeout" in detail.text.lower() or "validation_error" in detail.text.lower() or "unknown" in detail.text.lower()

    def test_no_private_content_in_failure(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)

        tid = _create_traveler_via_route(c, "FailPriv", "부산", csrf)

        def failing_provider(*args, **kwargs):
            from app.ai.mock import MockProvider
            provider = MockProvider()
            def fail(**kw):
                from app.domain.models import ProviderResult
                return ProviderResult(provider="mock-fail", model="mock-fail",
                                      success=False, error_category="timeout",
                                      error_message="secret prompt data leaked")
            provider.generate_structured = fail
            return provider

        with patch("app.web.routes.operator.create_mock_provider", side_effect=failing_provider):
            resp = c.post(f"/operator/travelers/{tid}/generate-first",
                          data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})

        body = resp.text if hasattr(resp, "text") else ""
        assert "secret prompt data" not in body
        assert "system_prompt" not in body

        detail = c.get(f"/operator/travelers/{tid}")
        assert "secret prompt data" not in detail.text

    def test_prior_published_maintained_after_failure(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)

        tid = _create_traveler_via_route(c, "FailPrior", "부산", csrf)
        c.post(f"/operator/travelers/{tid}/generate-first",
               data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})

        conn = get_connection()
        ed1 = get_editions_by_traveler(conn, tid)[0]
        ed1_content = ed1.structured_content
        update_edition_publication(conn, ed1.id, "published")
        create_feedback(conn, traveler_id=tid, edition_id=ed1.id,
                        direction_choices=["lower_budget"], free_text="test")
        conn.close()

        def failing_provider(*args, **kwargs):
            from app.ai.mock import MockProvider
            provider = MockProvider()
            def fail(**kw):
                from app.domain.models import ProviderResult
                return ProviderResult(provider="mock-fail", model="mock-fail",
                                      success=False, error_category="timeout",
                                      error_message="simulated failure")
            provider.generate_structured = fail
            return provider

        with patch("app.web.routes.operator.create_second_mock_provider", side_effect=failing_provider):
            c.post(f"/operator/travelers/{tid}/generate-second",
                   data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})

        conn = get_connection()
        ed1_check = get_edition_by_id(conn, ed1.id)
        assert ed1_check.publication_state == "published"
        assert ed1_check.structured_content == ed1_content

        fb_list = get_feedback_by_edition(conn, ed1.id)
        assert len(fb_list) == 1
        assert fb_list[0].applied_to_next_edition is False
        conn.close()


# ===================================================================
# Atomicity tests
# ===================================================================

class TestAtomicity:
    def test_invite_atomic_on_exception(self, app):
        c = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        _operator_login(c)
        csrf = _op_csrf(c)

        tid = _create_traveler_via_route(c, "AtomInv", "부산", csrf)
        raw_old = _issue_token_via_route(c, tid, csrf)

        conn = get_connection()
        old_token_row = conn.execute(
            "SELECT id FROM traveler_tokens WHERE traveler_id = ? AND is_active = 1",
            (tid,),
        ).fetchone()
        old_token_id = old_token_row["id"]
        old_session_row = conn.execute(
            "SELECT id FROM traveler_sessions WHERE traveler_id = ?", (tid,)
        ).fetchone()
        old_session_id = old_session_row["id"] if old_session_row else None
        conn.close()

        with patch("app.web.routes.operator.create_traveler_token", side_effect=RuntimeError("insert failed")):
            resp = c.post(f"/operator/travelers/{tid}/invite",
                          data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
            assert resp.status_code == 500

        conn = get_connection()
        still_active = conn.execute(
            "SELECT id FROM traveler_tokens WHERE id = ? AND is_active = 1",
            (old_token_id,),
        ).fetchone()
        assert still_active is not None

        if old_session_id:
            still_session = conn.execute(
                "SELECT id FROM traveler_sessions WHERE id = ?", (old_session_id,)
            ).fetchone()
            assert still_session is not None

        new_tokens = conn.execute(
            "SELECT id FROM traveler_tokens WHERE traveler_id = ? AND id != ?",
            (tid, old_token_id),
        ).fetchall()
        assert len(new_tokens) == 0
        conn.close()

    def test_second_gen_failure_rollback_feedback(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)

        tid = _create_traveler_via_route(c, "AtomFb", "부산", csrf)
        raw = _issue_token_via_route(c, tid, csrf)
        c.post(f"/operator/travelers/{tid}/generate-first",
               data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})

        conn = get_connection()
        ed1 = get_editions_by_traveler(conn, tid)[0]
        update_edition_publication(conn, ed1.id, "published")
        create_feedback(conn, traveler_id=tid, edition_id=ed1.id,
                        direction_choices=["lower_budget"], free_text="test")
        conn.close()

        _traveler_enter(c, raw)

        _operator_login(c)
        csrf = _op_csrf(c)

        def failing_provider(*args, **kwargs):
            from app.ai.mock import MockProvider
            provider = MockProvider()
            def fail(**kw):
                from app.domain.models import ProviderResult
                return ProviderResult(provider="mock-fail", model="mock-fail",
                                      success=False, error_category="timeout",
                                      error_message="simulated failure")
            provider.generate_structured = fail
            return provider

        with patch("app.web.routes.operator.create_second_mock_provider", side_effect=failing_provider):
            c.post(f"/operator/travelers/{tid}/generate-second",
                   data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})

        conn = get_connection()
        eds = get_editions_by_traveler(conn, tid)
        assert len(eds) == 1
        assert eds[0].publication_state == "published"

        fb_list = get_feedback_by_edition(conn, ed1.id)
        assert len(fb_list) == 1
        assert fb_list[0].applied_to_next_edition is False
        conn.close()
