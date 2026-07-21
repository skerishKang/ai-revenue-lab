"""Route-level acceptance tests for Living Travel Phase 2.

All tests use TestClient against actual production routes.
Service-level tests are in test_regression_full.py.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

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
from app.feedback_repository import create_feedback, get_feedback_by_edition
from app.security import (
    create_traveler_session,
    create_traveler_token,
    deactivate_traveler_tokens,
    generate_csrf_token,
    get_login_rate_limiter,
    reset_login_rate_limiter,
    rotate_traveler_token,
    validate_traveler_token,
    validate_traveler_session,
)
from app.source_repository import create_source
from app.traveler_repository import (
    activate_traveler,
    create_traveler,
    delete_traveler,
    get_traveler_by_id,
    is_traveler_active,
)


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load_fixture(name):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


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


def _create_traveler_via_route(client: TestClient, name: str, dest: str, csrf: str) -> str:
    resp = client.post("/operator/travelers/create",
                       data={"display_name": name, "destination": dest,
                             "trip_duration_nights": 3, "csrf_token": csrf},
                       cookies={"lt_csrf": csrf})
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
    assert m is not None, f"Token not found in: {resp.text[:500]}"
    return m.group(1)


def _traveler_enter(client: TestClient, raw_token: str):
    client.get("/traveler/enter")
    csrf = client.cookies.get("lt_csrf")
    resp = client.post("/traveler/enter",
                       data={"token": raw_token, "csrf_token": csrf or ""},
                       cookies={"lt_csrf": csrf or ""})
    return resp


def _generate_first_via_route(client: TestClient, traveler_id: str, csrf: str):
    resp = client.post(f"/operator/travelers/{traveler_id}/generate-first",
                       data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
    return resp


def _publish_via_route(client: TestClient, edition_id: str, csrf: str):
    resp = client.post(f"/operator/editions/{edition_id}/publish",
                       data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
    return resp


def _reject_via_route(client: TestClient, edition_id: str, csrf: str):
    resp = client.post(f"/operator/editions/{edition_id}/reject",
                       data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
    return resp


# ===================================================================
# Section B: First-edition production route test
# ===================================================================

class TestFirstEditionRoute:
    def test_generate_first_via_route(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)

        tid = _create_traveler_via_route(c, "RouteGen1", "부산", csrf)
        _issue_token_via_route(c, tid, csrf)

        resp = _generate_first_via_route(c, tid, csrf)
        assert resp.status_code in (200, 303)

        conn = get_connection()
        editions = get_editions_by_traveler(conn, tid)
        assert len(editions) == 1
        ed = editions[0]
        assert ed.generation_status == "pending_review"
        assert ed.publication_state == "pending"
        assert ed.structured_content != {}
        assert ed.structured_content.get("publication_title") is not None
        conn.close()

        detail = c.get(f"/operator/travelers/{tid}")
        assert detail.status_code == 200
        assert "pending_review" in detail.text
        assert f"/operator/editions/{ed.id}/publish" in detail.text
        assert f"/operator/editions/{ed.id}/reject" in detail.text

        tid2 = _create_traveler_via_route(c, "RouteGen1b", "부산", csrf)
        c.get("/traveler/enter")
        csrf2 = c.cookies.get("lt_csrf")
        _, raw2, _ = _get_traveler_session(c, "RouteGen1b")
        _traveler_enter(c, raw2)
        resp_traveler = c.get(f"/traveler/editions/{ed.id}")
        assert resp_traveler.status_code in (403, 307, 404)


def _get_traveler_session(client: TestClient, display_name: str):
    conn = get_connection()
    t = conn.execute("SELECT id FROM travelers WHERE display_name = ?", (display_name,)).fetchone()
    if not t:
        conn.close()
        return None, "", ""
    tid = t["id"]
    _, raw_token, csrf = create_traveler_session(conn, tid)
    conn.close()
    return tid, raw_token, csrf


# ===================================================================
# Section C: Full browser workflow
# ===================================================================

class TestFullBrowserWorkflow:
    def test_complete_operator_traveler_lifecycle(self, app):
        c = TestClient(app, follow_redirects=False)

        _operator_login(c)
        csrf = _op_csrf(c)

        tid = _create_traveler_via_route(c, "WfAlice", "부산", csrf)

        raw_token = _issue_token_via_route(c, tid, csrf)

        _traveler_enter(c, raw_token)
        resp_dash = c.get("/traveler/")
        assert resp_dash.status_code == 200
        assert "WfAlice" in resp_dash.text

        _operator_login(c)
        csrf = _op_csrf(c)

        resp_gen = _generate_first_via_route(c, tid, csrf)
        assert resp_gen.status_code in (200, 303)

        conn = get_connection()
        editions = get_editions_by_traveler(conn, tid)
        assert len(editions) == 1
        ed1 = editions[0]
        assert ed1.generation_status == "pending_review"
        assert ed1.publication_state == "pending"
        assert ed1.structured_content != {}
        conn.close()

        _traveler_enter(c, raw_token)
        resp_pending = c.get(f"/traveler/editions/{ed1.id}")
        assert resp_pending.status_code in (403, 307, 404)

        _operator_login(c)
        csrf = _op_csrf(c)
        resp_pub = _publish_via_route(c, ed1.id, csrf)
        assert resp_pub.status_code in (200, 303)

        conn = get_connection()
        ed1_check = get_edition_by_id(conn, ed1.id)
        assert ed1_check.generation_status == "pending_review"
        assert ed1_check.publication_state == "published"
        conn.close()

        _traveler_enter(c, raw_token)
        resp_view = c.get(f"/traveler/editions/{ed1.id}")
        assert resp_view.status_code == 200
        assert ed1_check.structured_content.get("publication_title", "") in resp_view.text

        _traveler_enter(c, raw_token)
        csrf_t = c.cookies.get("lt_csrf")
        resp_fb = c.post(f"/traveler/editions/{ed1.id}/feedback",
                         data={"choices": ["quieter_places", "slower_pace"],
                               "free_text": "좀 더 조용한 곳이 좋겠어요",
                               "csrf_token": csrf_t or ""},
                         cookies={"lt_csrf": csrf_t or ""})
        assert resp_fb.status_code in (200, 303)

        _operator_login(c)
        csrf = _op_csrf(c)
        detail = c.get(f"/operator/travelers/{tid}")
        assert detail.status_code == 200
        assert "WfAlice" in detail.text

        resp_gen2 = c.post(f"/operator/travelers/{tid}/generate-second",
                           data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        assert resp_gen2.status_code in (200, 303)

        conn = get_connection()
        editions2 = get_editions_by_traveler(conn, tid)
        assert len(editions2) == 2
        ed2 = editions2[1]
        assert ed2.generation_status == "pending_review"
        assert ed2.publication_state == "pending"
        assert ed2.prior_edition_id == ed1.id
        assert ed2.structured_content.get("publication_title") != ed1.structured_content.get("publication_title")
        conn.close()

        conn = get_connection()
        fb_list = get_feedback_by_edition(conn, ed1.id)
        assert len(fb_list) == 1
        assert fb_list[0].applied_to_next_edition is True
        conn.close()

        _operator_login(c)
        csrf = _op_csrf(c)
        resp_pub2 = _publish_via_route(c, ed2.id, csrf)
        assert resp_pub2.status_code in (200, 303)

        _traveler_enter(c, raw_token)
        resp_history = c.get("/traveler/editions")
        assert resp_history.status_code == 200

        _traveler_enter(c, raw_token)
        resp_v2 = c.get(f"/traveler/editions/{ed2.id}")
        assert resp_v2.status_code == 200
        assert ed2.structured_content.get("publication_title", "") in resp_v2.text


# ===================================================================
# Section D: Failure flow route-level tests
# ===================================================================

class TestFailureFlow:
    def test_pipeline_error_shows_failure(self, app):
        from unittest.mock import patch
        from app.domain.models import ProviderResult

        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "FailRoute1", "부산", csrf)

        def failing_provider(*args, **kwargs):
            from app.ai.mock import MockProvider
            provider = MockProvider()
            orig = provider.generate_structured
            def fail(**kw):
                return ProviderResult(provider="mock-fail", model="mock-fail",
                                      success=False, error_category="timeout",
                                      error_message="simulated failure")
            provider.generate_structured = fail
            return provider

        with patch("app.web.routes.operator.create_mock_provider", side_effect=failing_provider):
            resp = _generate_first_via_route(c, tid, csrf)
            assert resp.status_code in (200, 303)

        conn = get_connection()
        editions = get_editions_by_traveler(conn, tid)
        assert len(editions) == 0
        conn.close()

    def test_prior_published_edition_unaffected_by_failure(self, app):
        from unittest.mock import patch
        from app.domain.models import ProviderResult

        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "FailRoute2", "부산", csrf)

        resp1 = _generate_first_via_route(c, tid, csrf)
        assert resp1.status_code in (200, 303)

        conn = get_connection()
        ed1 = get_editions_by_traveler(conn, tid)[0]
        ed1_content = ed1.structured_content
        update_edition_publication(conn, ed1.id, "published")
        create_feedback(conn, traveler_id=tid, edition_id=ed1.id,
                        direction_choices=["quieter_places"], free_text="test")
        conn.close()

        def failing_provider(*args, **kwargs):
            from app.ai.mock import MockProvider
            provider = MockProvider()
            def fail(**kw):
                return ProviderResult(provider="mock-fail", model="mock-fail",
                                      success=False, error_category="timeout",
                                      error_message="simulated failure")
            provider.generate_structured = fail
            return provider

        with patch("app.web.routes.operator.create_second_mock_provider", side_effect=failing_provider):
            resp = c.post(f"/operator/travelers/{tid}/generate-second",
                          data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
            assert resp.status_code in (200, 303)

        conn = get_connection()
        ed1_check = get_edition_by_id(conn, ed1.id)
        assert ed1_check.publication_state == "published"
        assert ed1_check.structured_content == ed1_content

        editions = get_editions_by_traveler(conn, tid)
        assert len(editions) == 1
        conn.close()

    def test_no_private_content_leaked_on_failure(self, app):
        from unittest.mock import patch
        from app.domain.models import ProviderResult

        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "FailRoute3", "부산", csrf)

        def failing_provider(*args, **kwargs):
            from app.ai.mock import MockProvider
            provider = MockProvider()
            def fail(**kw):
                return ProviderResult(provider="mock-fail", model="mock-fail",
                                      success=False, error_category="timeout",
                                      error_message="simulated failure")
            provider.generate_structured = fail
            return provider

        with patch("app.web.routes.operator.create_mock_provider", side_effect=failing_provider):
            resp = _generate_first_via_route(c, tid, csrf)
            body = resp.text if hasattr(resp, "text") else ""
            assert "system_prompt" not in body
            assert "user_payload" not in body
            assert "simulated failure" not in body

    def test_unexpected_exception_not_swallowed(self, app):
        from unittest.mock import patch

        c = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "FailRoute4", "부산", csrf)

        def exploding_provider(*args, **kwargs):
            from app.ai.mock import MockProvider
            provider = MockProvider()
            def boom(**kw):
                raise RuntimeError("unexpected internal error")
            provider.generate_structured = boom
            return provider

        with patch("app.web.routes.operator.create_mock_provider", side_effect=exploding_provider):
            resp = c.post(f"/operator/travelers/{tid}/generate-first",
                          data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
            assert resp.status_code == 500


# ===================================================================
# Section A: Remaining regression items as route-level tests
# ===================================================================

class TestRouteRegression:
    def test_lockout(self, app):
        limiter = get_login_rate_limiter()
        limiter.reset("testclient")
        c = TestClient(app)
        for _ in range(5):
            c.get("/operator/login")
            csrf = c.cookies.get("lt_csrf")
            c.post("/operator/login",
                   data={"secret": "wrong", "csrf_token": csrf or ""},
                   cookies={"lt_csrf": csrf or ""})
        assert limiter.is_locked("testclient")
        limiter.reset("testclient")

    def test_login_retry(self, app):
        c = TestClient(app)
        c.get("/operator/login")
        csrf = c.cookies.get("lt_csrf")
        resp = c.post("/operator/login",
                      data={"secret": "wrong", "csrf_token": csrf or ""},
                      cookies={"lt_csrf": csrf or ""})
        assert "Invalid secret" in resp.text
        settings = get_settings()
        c.get("/operator/login")
        csrf2 = c.cookies.get("lt_csrf")
        resp2 = c.post("/operator/login",
                       data={"secret": settings.operator_secret, "csrf_token": csrf2 or ""},
                       cookies={"lt_csrf": csrf2 or ""})
        assert resp2.status_code in (200, 303)

    def test_traveler_token_retry(self, app):
        c = TestClient(app, follow_redirects=False)
        conn = get_connection()
        t = create_traveler(conn, display_name="TokRetry", destination="Seoul")
        _, raw_token = create_traveler_token(conn, t.id)
        conn.close()
        c.get("/traveler/enter")
        csrf = c.cookies.get("lt_csrf")
        resp = c.post("/traveler/enter",
                      data={"token": "bad", "csrf_token": csrf or ""},
                      cookies={"lt_csrf": csrf or ""})
        assert "Invalid" in resp.text
        c.get("/traveler/enter")
        csrf2 = c.cookies.get("lt_csrf")
        resp2 = c.post("/traveler/enter",
                       data={"token": raw_token, "csrf_token": csrf2 or ""},
                       cookies={"lt_csrf": csrf2 or ""})
        assert resp2.status_code in (200, 303)

    def test_create_traveler_exactly_one(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "SoloRoute", "Busan", csrf)
        conn = get_connection()
        cnt = conn.execute("SELECT COUNT(*) as c FROM travelers WHERE display_name = 'SoloRoute'").fetchone()["c"]
        conn.close()
        assert cnt == 1

    def test_invitation_digest_only(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "InvRoute", "Tokyo", csrf)
        raw = _issue_token_via_route(c, tid, csrf)
        assert len(raw) > 20
        conn = get_connection()
        row = conn.execute("SELECT token_hash FROM traveler_tokens WHERE traveler_id = ?", (tid,)).fetchone()
        conn.close()
        assert row["token_hash"] != raw

    def test_deactivate_route(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "DelRoute", "Berlin", csrf)
        resp = c.post(f"/operator/travelers/{tid}/deactivate",
                      data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        assert resp.status_code in (200, 303)
        conn = get_connection()
        assert not is_traveler_active(conn, tid)
        conn.close()

    def test_activate_route(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "ActRoute", "Rome", csrf)
        c.post(f"/operator/travelers/{tid}/deactivate",
               data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        resp = c.post(f"/operator/travelers/{tid}/activate",
                      data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        assert resp.status_code in (200, 303)
        conn = get_connection()
        assert is_traveler_active(conn, tid)
        conn.close()

    def test_publish_only_publication(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "PubRoute", "Lisbon", csrf)
        _generate_first_via_route(c, tid, csrf)
        conn = get_connection()
        ed = get_editions_by_traveler(conn, tid)[0]
        assert ed.generation_status == "pending_review"
        assert ed.publication_state == "pending"
        resp = _publish_via_route(c, ed.id, csrf)
        assert resp.status_code in (200, 303)
        ed2 = get_edition_by_id(conn, ed.id)
        assert ed2.generation_status == "pending_review"
        assert ed2.publication_state == "published"
        conn.close()

    def test_traveler_views_published(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "ViewRoute", "Seoul", csrf)
        raw = _issue_token_via_route(c, tid, csrf)
        _generate_first_via_route(c, tid, csrf)
        conn = get_connection()
        ed = get_editions_by_traveler(conn, tid)[0]
        update_edition_publication(conn, ed.id, "published")
        conn.close()
        _traveler_enter(c, raw)
        resp = c.get(f"/traveler/editions/{ed.id}")
        assert resp.status_code == 200
        assert ed.structured_content.get("publication_title", "") in resp.text

    def test_pending_invisible(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "PendRoute", "Seoul", csrf)
        raw = _issue_token_via_route(c, tid, csrf)
        _generate_first_via_route(c, tid, csrf)
        conn = get_connection()
        ed = get_editions_by_traveler(conn, tid)[0]
        conn.close()
        _traveler_enter(c, raw)
        resp = c.get("/traveler/")
        assert f"/traveler/editions/{ed.id}" not in resp.text

    def test_rendered_content_fields(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "RenderRoute", "부산", csrf)
        raw = _issue_token_via_route(c, tid, csrf)
        _generate_first_via_route(c, tid, csrf)
        conn = get_connection()
        ed = get_editions_by_traveler(conn, tid)[0]
        update_edition_publication(conn, ed.id, "published")
        sc = ed.structured_content
        conn.close()
        _traveler_enter(c, raw)
        resp = c.get(f"/traveler/editions/{ed.id}")
        assert resp.status_code == 200
        assert sc.get("publication_title", "") in resp.text
        if sc.get("sections"):
            assert sc["sections"][0].get("title", "") in resp.text

    def test_feedback_multi_checkbox(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "FbRoute", "Seoul", csrf)
        raw = _issue_token_via_route(c, tid, csrf)
        _generate_first_via_route(c, tid, csrf)
        conn = get_connection()
        ed = get_editions_by_traveler(conn, tid)[0]
        update_edition_publication(conn, ed.id, "published")
        conn.close()
        _traveler_enter(c, raw)
        csrf_t = c.cookies.get("lt_csrf")
        resp = c.post(f"/traveler/editions/{ed.id}/feedback",
                      data={"choices": ["quieter_places", "slower_pace", "more_local_food"],
                            "free_text": "Great", "csrf_token": csrf_t or ""},
                      cookies={"lt_csrf": csrf_t or ""})
        assert resp.status_code in (200, 303)
        conn2 = get_connection()
        fbs = get_feedback_by_edition(conn2, ed.id)
        assert len(fbs) == 1
        assert set(fbs[0].direction_choices) == {"quieter_places", "slower_pace", "more_local_food"}
        conn2.close()

    def test_feedback_duplicate_prevented(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "FbDup", "Seoul", csrf)
        raw = _issue_token_via_route(c, tid, csrf)
        _generate_first_via_route(c, tid, csrf)
        conn = get_connection()
        ed = get_editions_by_traveler(conn, tid)[0]
        update_edition_publication(conn, ed.id, "published")
        conn.close()
        _traveler_enter(c, raw)
        csrf_t = c.cookies.get("lt_csrf")
        c.post(f"/traveler/editions/{ed.id}/feedback",
               data={"choices": ["quieter_places"], "csrf_token": csrf_t or ""},
               cookies={"lt_csrf": csrf_t or ""})
        c.post(f"/traveler/editions/{ed.id}/feedback",
               data={"choices": ["slower_pace"], "csrf_token": csrf_t or ""},
               cookies={"lt_csrf": csrf_t or ""})
        conn2 = get_connection()
        fbs = get_feedback_by_edition(conn2, ed.id)
        assert len(fbs) == 1
        conn2.close()

    def test_reject_only_publication(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "RejRoute", "Hanoi", csrf)
        _generate_first_via_route(c, tid, csrf)
        conn = get_connection()
        ed = get_editions_by_traveler(conn, tid)[0]
        conn.close()
        resp = _reject_via_route(c, ed.id, csrf)
        assert resp.status_code in (200, 303)
        conn2 = get_connection()
        ed2 = get_edition_by_id(conn2, ed.id)
        assert ed2.generation_status == "pending_review"
        assert ed2.publication_state == "rejected"
        conn2.close()

    def test_reject_does_not_affect_published(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "RejIso", "Kyoto", csrf)
        _generate_first_via_route(c, tid, csrf)
        conn = get_connection()
        ed1 = get_editions_by_traveler(conn, tid)[0]
        update_edition_publication(conn, ed1.id, "published")

        ed2 = create_edition(conn, traveler_id=tid, edition_number=2)
        update_edition_content(conn, ed2.id, {"title": "Rej"})
        update_edition_generation_status(conn, ed2.id, "pending_review")
        conn.close()
        _reject_via_route(c, ed2.id, csrf)
        conn3 = get_connection()
        assert get_edition_by_id(conn3, ed1.id).publication_state == "published"
        assert get_edition_by_id(conn3, ed2.id).publication_state == "rejected"
        conn3.close()

    def test_csrf_required_on_all_mutations(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        routes = [
            ("/operator/travelers/create", {"display_name": "X", "destination": "Y",
                                            "trip_duration_nights": 1, "csrf_token": ""}),
            ("/operator/travelers/fake/deactivate", {"csrf_token": ""}),
            ("/operator/travelers/fake/activate", {"csrf_token": ""}),
            ("/operator/travelers/fake/invite", {"csrf_token": ""}),
            ("/operator/travelers/fake/rotate-invite", {"csrf_token": ""}),
            ("/operator/travelers/fake/generate-first", {"csrf_token": ""}),
            ("/operator/travelers/fake/generate-second", {"csrf_token": ""}),
            ("/operator/editions/fake/publish", {"csrf_token": ""}),
            ("/operator/editions/fake/reject", {"csrf_token": ""}),
        ]
        for path, data in routes:
            resp = c.post(path, data=data)
            assert resp.status_code in (403, 404, 422), f"{path}={resp.status_code}"

    def test_logout_csrf_in_templates(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        resp = c.get("/operator/")
        assert 'name="csrf_token"' in resp.text
        assert 'action="/operator/logout"' in resp.text

        conn = get_connection()
        t = create_traveler(conn, display_name="CstfR", destination="Paris")
        conn.close()
        resp2 = c.get(f"/operator/travelers/{t.id}")
        assert 'name="csrf_token"' in resp2.text

        c2 = TestClient(app, follow_redirects=False)
        conn = get_connection()
        t2 = create_traveler(conn, display_name="CstfR2", destination="Paris")
        _, raw_s, _ = create_traveler_session(conn, t2.id)
        conn.close()
        c2.cookies.set("lt_traveler_session", raw_s)
        resp3 = c2.get("/traveler/")
        assert 'name="csrf_token"' in resp3.text
        assert 'action="/traveler/logout"' in resp3.text

    def test_atomicity_deactivate(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "AtomRoute", "Lima", csrf)
        raw = _issue_token_via_route(c, tid, csrf)
        c.post(f"/operator/travelers/{tid}/deactivate",
               data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        conn = get_connection()
        assert not is_traveler_active(conn, tid)
        assert validate_traveler_token(conn, raw) is None
        conn.close()

    def test_durability(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "DurRoute", "Seoul", csrf)
        conn = get_connection()
        found = get_traveler_by_id(conn, tid)
        assert found is not None
        assert found.display_name == "DurRoute"
        conn.close()

    def test_ownership_block(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c)
        csrf = _op_csrf(c)
        tid_a = _create_traveler_via_route(c, "OwnA_R", "Seoul", csrf)
        tid_b = _create_traveler_via_route(c, "OwnB_R", "Tokyo", csrf)
        raw_a = _issue_token_via_route(c, tid_a, csrf)
        _generate_first_via_route(c, tid_b, csrf)
        conn = get_connection()
        ed_b = get_editions_by_traveler(conn, tid_b)[0]
        update_edition_publication(conn, ed_b.id, "published")
        conn.close()
        _traveler_enter(c, raw_a)
        resp = c.get(f"/traveler/editions/{ed_b.id}")
        assert resp.status_code == 404
