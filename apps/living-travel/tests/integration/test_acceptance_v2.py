"""Additional acceptance tests for Living Travel Phase 2 CTO requirements.

Covers: personalization, exact feedback with section-level verification,
failure UI, atomicity, failure allow-list.
All tests use TestClient against actual production routes.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.config import get_settings, reset_settings
from app.db import apply_migrations, get_connection
from app.edition_repository import (
    get_edition_by_id,
    get_editions_by_traveler,
    update_edition_publication,
)
from app.factory import create_app
from app.feedback_repository import create_feedback, get_feedback_by_edition
from app.security import (
    create_traveler_session,
    create_traveler_token,
    get_login_rate_limiter,
    reset_login_rate_limiter,
)
from app.traveler_repository import create_traveler


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
    client.get("/operator/login")
    csrf = client.cookies.get("lt_csrf")
    client.post("/operator/login", data={"secret": settings.operator_secret, "csrf_token": csrf or ""},
               cookies={"lt_csrf": csrf or ""})


def _op_csrf(client: TestClient) -> str:
    resp = client.get("/operator/")
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.text)
    return m.group(1) if m else ""


def _create_traveler_via_route(client: TestClient, name: str, dest: str, csrf: str,
                                nights: int = 3) -> str:
    resp = client.post("/operator/travelers/create",
                       data={"display_name": name, "destination": dest,
                             "trip_duration_nights": nights, "csrf_token": csrf},
                       cookies={"lt_csrf": csrf})
    assert resp.status_code in (200, 303)
    conn = get_connection()
    t = conn.execute("SELECT id FROM travelers WHERE display_name = ?", (name,)).fetchone()
    conn.close()
    return t["id"]


def _issue_token_via_route(client: TestClient, traveler_id: str, csrf: str) -> str:
    resp = client.post(f"/operator/travelers/{traveler_id}/invite",
                       data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
    assert resp.status_code == 200
    m = re.search(r'class="token-value">([A-Za-z0-9_-]+)<', resp.text)
    return m.group(1)


def _traveler_enter(client: TestClient, raw_token: str):
    client.get("/traveler/enter")
    csrf = client.cookies.get("lt_csrf")
    client.post("/traveler/enter", data={"token": raw_token, "csrf_token": csrf or ""},
                cookies={"lt_csrf": csrf or ""})


def _first_gen(client, tid, csrf):
    return client.post(f"/operator/travelers/{tid}/generate-first",
                       data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})


def _second_gen(client, tid, csrf):
    return client.post(f"/operator/travelers/{tid}/generate-second",
                       data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})


# ===================================================================
# Personalization
# ===================================================================

class TestPersonalization:
    def test_first_edition_two_destinations(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c); csrf = _op_csrf(c)
        tb = _create_traveler_via_route(c, "PersB", "부산", csrf, nights=2)
        ts = _create_traveler_via_route(c, "PersS", "서울", csrf, nights=4)
        _first_gen(c, tb, csrf); _first_gen(c, ts, csrf)

        conn = get_connection()
        sc_b = get_editions_by_traveler(conn, tb)[0].structured_content
        sc_s = get_editions_by_traveler(conn, ts)[0].structured_content
        conn.close()

        assert sc_b["destination"] == "부산"
        assert sc_s["destination"] == "서울"
        assert "2박" in sc_b["trip_frame"]
        assert "4박" in sc_s["trip_frame"]
        assert all("부산" in s["title"] for s in sc_b.get("sections", []))
        assert all("서울" in s["title"] for s in sc_s.get("sections", []))
        assert sc_b["publication_title"] != sc_s["publication_title"]
        assert sc_b["edition_title"] != sc_s["edition_title"]
        assert sc_b["editorial_opening"] != sc_s["editorial_opening"]

    def test_second_edition_cross_destination_no_busan_leak(self, app):
        """Seoul second edition must NOT contain Busan phrases."""
        c = TestClient(app, follow_redirects=False)
        _operator_login(c); csrf = _op_csrf(c)

        tb = _create_traveler_via_route(c, "XDB", "부산", csrf, nights=2)
        ts = _create_traveler_via_route(c, "XDS", "서울", csrf, nights=4)

        rtb = _issue_token_via_route(c, tb, csrf); rts = _issue_token_via_route(c, ts, csrf)
        _first_gen(c, tb, csrf); _first_gen(c, ts, csrf)

        conn = get_connection()
        e1b = get_editions_by_traveler(conn, tb)[0]; e1s = get_editions_by_traveler(conn, ts)[0]
        update_edition_publication(conn, e1b.id, "published"); update_edition_publication(conn, e1s.id, "published")
        conn.close()

        _traveler_enter(c, rtb); ctf = c.cookies.get("lt_csrf")
        c.post(f"/traveler/editions/{e1b.id}/feedback", data={"choices": ["quieter_places"], "csrf_token": ctf or ""}, cookies={"lt_csrf": ctf or ""})
        _traveler_enter(c, rts); ctf = c.cookies.get("lt_csrf")
        c.post(f"/traveler/editions/{e1s.id}/feedback", data={"choices": ["more_local_food"], "csrf_token": ctf or ""}, cookies={"lt_csrf": ctf or ""})

        _operator_login(c); csrf = _op_csrf(c)
        _second_gen(c, tb, csrf); _second_gen(c, ts, csrf)

        conn = get_connection()
        eds_b = get_editions_by_traveler(conn, tb); eds_s = get_editions_by_traveler(conn, ts)
        sc_b = eds_b[1].structured_content if len(eds_b) > 1 else {}
        sc_s = eds_s[1].structured_content if len(eds_s) > 1 else {}
        conn.close()

        assert sc_s, "Seoul second edition should exist"
        assert sc_s["destination"] == "서울", f"Expected 서울, got {sc_s.get('destination')}"

        BANNED = ["부산", "Busan", "해운대"]
        for phrase in BANNED:
            assert phrase not in sc_s.get("publication_title", ""), f"Seoul title contains {phrase}"
            assert phrase not in sc_s.get("edition_title", ""), f"Seoul edition_title contains {phrase}"
            assert phrase not in sc_s.get("editorial_opening", ""), f"Seoul opening contains {phrase}"
            assert phrase not in sc_s.get("trip_frame", ""), f"Seoul trip_frame contains {phrase}"
            for sec in sc_s.get("sections", []):
                assert phrase not in sec.get("title", ""), f"Seoul section title contains {phrase}"

        assert sc_b["destination"] == "부산"
        assert "2박" in sc_b["trip_frame"]
        assert "4박" in sc_s["trip_frame"]


# ===================================================================
# Exact feedback
# ===================================================================

class TestExactFeedback:
    def _setup_first(self, c, name, dest, csrf, nights=3):
        tid = _create_traveler_via_route(c, name, dest, csrf, nights=nights)
        raw = _issue_token_via_route(c, tid, csrf)
        _first_gen(c, tid, csrf)
        conn = get_connection()
        ed = get_editions_by_traveler(conn, tid)[0]
        update_edition_publication(conn, ed.id, "published")
        conn.close()
        return tid, raw, ed

    def test_lower_budget_exact_section(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c); csrf = _op_csrf(c)
        tid, raw, ed1 = self._setup_first(c, "FbExact", "부산", csrf)

        _traveler_enter(c, raw); ctf = c.cookies.get("lt_csrf")
        c.post(f"/traveler/editions/{ed1.id}/feedback",
               data={"choices": ["lower_budget"], "csrf_token": ctf or ""},
               cookies={"lt_csrf": ctf or ""})

        _operator_login(c); csrf = _op_csrf(c)
        _second_gen(c, tid, csrf)

        conn = get_connection()
        eds = get_editions_by_traveler(conn, tid)
        assert len(eds) == 2
        sc2 = eds[1].structured_content
        conn.close()

        app_fb = sc2.get("applied_feedback", [])
        assert len(app_fb) >= 1

        fb1 = app_fb[0]
        assert fb1["feedback_id"] != ""
        assert "lower_budget" in fb1["requested_change"]
        assert fb1["affected_section_ids"] == ["sec_budget"]

        section_ids = {s["section_id"] for s in sc2.get("sections", [])}
        assert "sec_budget" in section_ids

        budget_sec = next((s for s in sc2.get("sections", []) if s["section_id"] == "sec_budget"), None)
        assert budget_sec is not None
        assert "예산" in budget_sec["narrative"] or "budget" in budget_sec["narrative"].lower() or "비용" in budget_sec["narrative"]

        not_applied = [d for fb in app_fb for d in ["quieter_places", "slower_pace", "more_local_food"]
                       if d in fb.get("requested_change", "")]
        assert len(not_applied) == 0, f"Unrelated feedback found: {not_applied}"

        conn = get_connection()
        fl = get_feedback_by_edition(conn, ed1.id)
        assert fl[0].applied_to_next_edition is True
        conn.close()

    def test_quieter_and_less_walking_exact_sections(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c); csrf = _op_csrf(c)
        tid, raw, ed1 = self._setup_first(c, "FbQuiet2", "부산", csrf)

        _traveler_enter(c, raw); ctf = c.cookies.get("lt_csrf")
        c.post(f"/traveler/editions/{ed1.id}/feedback",
               data={"choices": ["quieter_places", "less_walking"],
                     "free_text": "조용하고 걷기 적게", "csrf_token": ctf or ""},
               cookies={"lt_csrf": ctf or ""})

        _operator_login(c); csrf = _op_csrf(c)
        _second_gen(c, tid, csrf)

        conn = get_connection()
        eds = get_editions_by_traveler(conn, tid)
        assert len(eds) == 2
        sc2 = eds[1].structured_content
        conn.close()

        app_fb = sc2.get("applied_feedback", [])
        assert len(app_fb) >= 1

        fb1 = app_fb[0]
        assert "quieter_places" in fb1["requested_change"]
        assert "less_walking" in fb1["requested_change"]
        assert "sec_quiet" in fb1["affected_section_ids"]
        assert "sec_low_effort" in fb1["affected_section_ids"]

        section_ids = {s["section_id"] for s in sc2.get("sections", [])}
        assert "sec_quiet" in section_ids
        assert "sec_low_effort" in section_ids

        quiet_sec = next((s for s in sc2.get("sections", []) if s["section_id"] == "sec_quiet"), None)
        assert quiet_sec is not None
        assert "조용" in quiet_sec["narrative"]

        low_sec = next((s for s in sc2.get("sections", []) if s["section_id"] == "sec_low_effort"), None)
        assert low_sec is not None
        assert "이동" in low_sec["narrative"]

        not_applied = [d for fb in app_fb for d in ["lower_budget", "more_practical"]
                       if d in fb.get("requested_change", "")]
        assert len(not_applied) == 0


# ===================================================================
# Failure UI & allow-list
# ===================================================================

class TestFailureUI:
    def test_failure_category_in_redirect(self, app):
        c = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        _operator_login(c); csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "FailR", "부산", csrf)

        def fp(*a, **kw):
            from app.ai.mock import MockProvider
            p = MockProvider()
            def fail(**k):
                from app.domain.models import ProviderResult
                return ProviderResult(provider="mf", model="mf", success=False, error_category="timeout", error_message="sim")
            p.generate_structured = fail; return p

        with patch("app.web.routes.operator.create_mock_provider", side_effect=fp):
            r = c.post(f"/operator/travelers/{tid}/generate-first", data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        loc = r.headers.get("location", "")
        assert "?failure=" in loc

        detail = c.get(loc); assert detail.status_code == 200
        assert "unknown" in detail.text.lower() or "timeout" in detail.text.lower()

    def test_failure_allowlist_blocks_arbitrary(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c); csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "FailAL", "부산", csrf)

        detail = c.get(f"/operator/travelers/{tid}?failure=timeout")
        assert "Generation failed (timeout)" in detail.text

        detail2 = c.get(f"/operator/travelers/{tid}?failure=validation_error")
        assert "Generation failed (validation_error)" in detail2.text

        detail3 = c.get(f"/operator/travelers/{tid}?failure=<script>alert(1)</script>")
        assert "Generation failed" not in detail3.text

        detail4 = c.get(f"/operator/travelers/{tid}?failure=made_up_category_12345")
        assert "Generation failed" not in detail4.text

        detail5 = c.get(f"/operator/travelers/{tid}?failure=Too many failed attempts. Please try again later.")
        assert "Generation failed" not in detail5.text

    def test_no_private_content(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c); csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "FailP", "부산", csrf)

        def fp(*a, **kw):
            from app.ai.mock import MockProvider
            p = MockProvider()
            def fail(**k):
                from app.domain.models import ProviderResult
                return ProviderResult(provider="mf", model="mf", success=False, error_category="timeout", error_message="SECRET_LEAK")
            p.generate_structured = fail; return p

        with patch("app.web.routes.operator.create_mock_provider", side_effect=fp):
            r = c.post(f"/operator/travelers/{tid}/generate-first", data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        body = r.text if hasattr(r, "text") else ""
        assert "SECRET_LEAK" not in body
        assert "system_prompt" not in body

    def test_prior_published_maintained(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c); csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "FailPr", "부산", csrf)
        _first_gen(c, tid, csrf)

        conn = get_connection()
        ed1 = get_editions_by_traveler(conn, tid)[0]
        ed1_content = ed1.structured_content
        update_edition_publication(conn, ed1.id, "published")
        create_feedback(conn, traveler_id=tid, edition_id=ed1.id, direction_choices=["quieter_places"], free_text="t")
        conn.close()

        def fp(*a, **kw):
            from app.ai.mock import MockProvider
            p = MockProvider()
            def fail(**k):
                from app.domain.models import ProviderResult
                return ProviderResult(provider="mf", model="mf", success=False, error_category="timeout", error_message="sim")
            p.generate_structured = fail; return p

        with patch("app.web.routes.operator.create_second_mock_provider", side_effect=fp):
            _second_gen(c, tid, csrf)

        conn = get_connection()
        assert get_edition_by_id(conn, ed1.id).publication_state == "published"
        assert get_edition_by_id(conn, ed1.id).structured_content == ed1_content
        fl = get_feedback_by_edition(conn, ed1.id)
        assert fl[0].applied_to_next_edition is False
        conn.close()


# ===================================================================
# Atomicity
# ===================================================================

class TestAtomicity:
    def test_invite_rollback(self, app):
        c = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        _operator_login(c); csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "AtInv", "부산", csrf)
        _issue_token_via_route(c, tid, csrf)

        conn = get_connection()
        old = conn.execute("SELECT id FROM traveler_tokens WHERE traveler_id = ? AND is_active = 1", (tid,)).fetchone()
        old_id = old["id"]
        sess = conn.execute("SELECT id FROM traveler_sessions WHERE traveler_id = ?", (tid,)).fetchone()
        old_sess = sess["id"] if sess else None
        conn.close()

        with patch("app.web.routes.operator.create_traveler_token", side_effect=RuntimeError("fail")):
            r = c.post(f"/operator/travelers/{tid}/invite", data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
            assert r.status_code == 500

        conn = get_connection()
        assert conn.execute("SELECT id FROM traveler_tokens WHERE id = ? AND is_active = 1", (old_id,)).fetchone() is not None
        if old_sess:
            assert conn.execute("SELECT id FROM traveler_sessions WHERE id = ?", (old_sess,)).fetchone() is not None
        new = conn.execute("SELECT id FROM traveler_tokens WHERE traveler_id = ? AND id != ?", (tid, old_id)).fetchall()
        assert len(new) == 0
        conn.close()

    def test_second_gen_failure_rollback(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c); csrf = _op_csrf(c)
        tid = _create_traveler_via_route(c, "AtFb", "부산", csrf)
        raw = _issue_token_via_route(c, tid, csrf)
        _first_gen(c, tid, csrf)

        conn = get_connection()
        ed1 = get_editions_by_traveler(conn, tid)[0]
        update_edition_publication(conn, ed1.id, "published")
        create_feedback(conn, traveler_id=tid, edition_id=ed1.id, direction_choices=["quieter_places"], free_text="t")
        conn.close()
        _traveler_enter(c, raw)

        _operator_login(c); csrf = _op_csrf(c)

        def fp(*a, **kw):
            from app.ai.mock import MockProvider
            p = MockProvider()
            def fail(**k):
                from app.domain.models import ProviderResult
                return ProviderResult(provider="mf", model="mf", success=False, error_category="timeout", error_message="sim")
            p.generate_structured = fail; return p

        with patch("app.web.routes.operator.create_second_mock_provider", side_effect=fp):
            _second_gen(c, tid, csrf)

        conn = get_connection()
        eds = get_editions_by_traveler(conn, tid)
        assert len(eds) == 1
        fl = get_feedback_by_edition(conn, ed1.id)
        assert fl[0].applied_to_next_edition is False
        conn.close()


# ===================================================================
# Full preferences test
# ===================================================================

class TestFullPreferences:
    def test_all_preferences_reflected(self, app):
        c = TestClient(app, follow_redirects=False)
        _operator_login(c); csrf = _op_csrf(c)

        tid = _create_traveler_via_route(c, "FullPref", "서울", csrf, nights=2)
        conn = get_connection()
        conn.execute("UPDATE travelers SET trip_context = 'family', pace_preference = 'relaxed', "
                     "budget_tendency = 'budget', tone_preference = 'calm', "
                     "length_preference = 'short', preferred_language = 'ko' WHERE id = ?", (tid,))
        conn.commit()
        conn.close()

        _first_gen(c, tid, csrf)

        conn = get_connection()
        sc = get_editions_by_traveler(conn, tid)[0].structured_content
        conn.close()

        assert sc["destination"] == "서울"
        assert sc["trip_frame"] == "2박 3일"
        assert "가족" in sc.get("publication_title", "") or "family" in sc.get("publication_title", "").lower()
        assert "합리" in sc.get("editorial_opening", "")
        assert "여유" in sc.get("editorial_opening", "")
        assert "천천히" in sc.get("editorial_opening", "")

        sections = sc.get("sections", [])
        assert len(sections) <= 1, f"short length should limit sections, got {len(sections)}"
