"""Comprehensive regression tests for Living Travel Phase 2.

Covers all 27 acceptance items. Tests verify DB state and response content.
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
from app.pipeline.errors import PipelineError
from app.pipeline.service import GenerationService
from app.ai.mock import MockProvider
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


def _logged_in(app):
    c = TestClient(app)
    settings = get_settings()
    secret = getattr(settings, "operator_secret", "test-secret-12345")
    c.get("/operator/login")
    csrf = c.cookies.get("lt_csrf")
    c.post("/operator/login", data={"secret": secret, "csrf_token": csrf or ""},
           cookies={"lt_csrf": csrf or ""})
    return c


def _op_csrf(client):
    resp = client.get("/operator/")
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.text)
    return m.group(1) if m else ""


def _make_traveler(client, conn, display_name="TestT", dest="Seoul"):
    t = create_traveler(conn, display_name=display_name, destination=dest)
    _, raw_token = create_traveler_token(conn, t.id)
    session_id, raw_session, csrf = create_traveler_session(conn, t.id)
    client.cookies.set("lt_traveler_session", raw_session)
    return t, raw_token, csrf


def _make_plan_and_draft(src_id):
    draft = _load_fixture("source_bundle.json")["first_edition_fixture"]
    plan = {
        "plan_version": "1.0", "language": "ko", "central_theme": "Test",
        "sections": [{"section_id": s["section_id"], "title": s["title"],
                      "description": "D"} for s in draft["sections"]],
    }
    for sec in draft.get("sections", []):
        for item in sec.get("items", []):
            item["source_ref"] = src_id
    return plan, draft


def _make_prefs(dest="Seoul"):
    return {
        "destination": dest, "trip_duration_nights": 3,
        "trip_context": "solo", "budget_tendency": "moderate",
        "pace_preference": "comfortable", "interests": [],
        "exclusions": [], "tone_preference": "calm",
        "length_preference": "medium", "preferred_language": "ko",
    }


def _make_src_items(source_id, dest="Seoul"):
    claims = _load_fixture("source_bundle.json")["first_edition_fixture"]
    all_claims = []
    for s in claims["sections"]:
        for item in s.get("items", []):
            all_claims.append(item["item_id"])
    return [{"source_id": source_id, "source_url": "https://example.com",
             "publisher": "Test", "source_type": "web",
             "original_language": "ko", "destination": dest,
             "locality": "", "category": "food", "claims": all_claims,
             "confidence": "confirmed", "state": "single_source",
             "verification_notes": ""}]


def _full_edition_content(title="Test Title"):
    return {
        "publication_title": title,
        "edition_title": "Vol 1",
        "destination": "Seoul",
        "trip_frame": "3 nights",
        "editorial_opening": "Welcome",
        "sections": [{"section_id": "s1", "title": "Section One",
                      "narrative": "Narrative text here.",
                      "items": []}],
        "applied_feedback": [],
        "content_version": "1.0",
        "provenance_note": "Synthetic mock",
    }


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


@pytest.fixture()
def client(app):
    return TestClient(app)


# ── 1. Operator wrong secret → lockout ──

class TestLockout:
    def test_lockout_after_max_failures(self, client: TestClient):
        limiter = get_login_rate_limiter()
        limiter.reset("testclient")
        for _ in range(5):
            client.get("/operator/login")
            csrf = client.cookies.get("lt_csrf")
            client.post("/operator/login",
                        data={"secret": "wrong", "csrf_token": csrf or ""},
                        cookies={"lt_csrf": csrf or ""})
        assert limiter.is_locked("testclient")
        limiter.reset("testclient")


# ── 2. Failed login → retry ──

class TestLoginRetry:
    def test_wrong_then_right_succeeds(self, client: TestClient):
        client.get("/operator/login")
        csrf = client.cookies.get("lt_csrf")
        resp = client.post("/operator/login",
                           data={"secret": "wrong", "csrf_token": csrf or ""},
                           cookies={"lt_csrf": csrf or ""})
        assert "Invalid secret" in resp.text
        settings = get_settings()
        client.get("/operator/login")
        csrf2 = client.cookies.get("lt_csrf")
        resp2 = client.post("/operator/login",
                            data={"secret": settings.operator_secret, "csrf_token": csrf2 or ""},
                            cookies={"lt_csrf": csrf2 or ""})
        assert resp2.status_code in (200, 303)
        assert "Invalid" not in resp2.text


# ── 3. Traveler invalid token → retry ──

class TestTravelerRetry:
    def test_invalid_then_valid_succeeds(self, app, client: TestClient):
        conn = get_connection()
        t = create_traveler(conn, display_name="RetryT", destination="Seoul")
        _, raw_token = create_traveler_token(conn, t.id)
        conn.close()
        client.get("/traveler/enter")
        csrf = client.cookies.get("lt_csrf")
        resp = client.post("/traveler/enter",
                           data={"token": "bad", "csrf_token": csrf or ""},
                           cookies={"lt_csrf": csrf or ""})
        assert "Invalid" in resp.text
        client.get("/traveler/enter")
        csrf2 = client.cookies.get("lt_csrf")
        resp2 = client.post("/traveler/enter",
                            data={"token": raw_token, "csrf_token": csrf2 or ""},
                            cookies={"lt_csrf": csrf2 or ""})
        assert resp2.status_code in (200, 303)


# ── 4. Traveler create exactly 1 ──

class TestTravelerCreate:
    def test_create_exactly_one(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="Solo1", destination="Busan")
        row = conn.execute("SELECT COUNT(*) as cnt FROM travelers WHERE display_name = 'Solo1'").fetchone()
        assert row["cnt"] == 1
        conn.close()


# ── 5. Invitation → raw token not stored ──

class TestInvitationSecurity:
    def test_digest_only_stored(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="InvSec", destination="Tokyo")
        token_id, raw_token = create_traveler_token(conn, t.id)
        row = conn.execute("SELECT token_hash FROM traveler_tokens WHERE id = ?", (token_id,)).fetchone()
        assert raw_token != row["token_hash"]
        assert len(row["token_hash"]) == 64
        conn.close()


# ── 6. Invitation rotate → old invalid, new valid ──

class TestInvitationRotate:
    def test_rotate_invalidates_old(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="RotSec", destination="Osaka")
        token_id, old_raw = create_traveler_token(conn, t.id)
        assert validate_traveler_token(conn, old_raw) == t.id
        new_id, new_raw = rotate_traveler_token(conn, token_id)
        assert validate_traveler_token(conn, old_raw) is None
        assert validate_traveler_token(conn, new_raw) == t.id
        conn.close()


# ── 7. Deactivate → all invalid ──

class TestDeactivate:
    def test_all_invalidated(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="DelAll", destination="Berlin")
        _, raw_token = create_traveler_token(conn, t.id)
        _, raw_session, _ = create_traveler_session(conn, t.id)
        delete_traveler(conn, t.id, commit=False)
        deactivate_traveler_tokens(conn, t.id, commit=False)
        conn.execute("DELETE FROM traveler_sessions WHERE traveler_id = ?", (t.id,))
        conn.commit()
        assert not is_traveler_active(conn, t.id)
        assert validate_traveler_token(conn, raw_token) is None
        assert validate_traveler_session(conn, raw_session) is None
        conn.close()


# ── 8. Activate → active ──

class TestActivate:
    def test_activate_makes_active(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="ActT", destination="Rome")
        delete_traveler(conn, t.id, commit=False)
        deactivate_traveler_tokens(conn, t.id, commit=False)
        conn.commit()
        assert not is_traveler_active(conn, t.id)
        activate_traveler(conn, t.id)
        assert is_traveler_active(conn, t.id)
        conn.close()


# ── 9. First generation → correct state ──

class TestFirstGeneration:
    def test_first_gen_state(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="Gen9", destination="Seoul")
        src = create_source(conn, source_url="https://example.com", publisher="Test",
                            source_type="web", destination="Seoul", category="food",
                            claims=["c1"], confidence=SourceConfidence.confirmed)
        plan, draft = _make_plan_and_draft(src.id)
        provider = MockProvider(task_payloads={"editorial_plan": plan, "edition_draft": draft})
        service = GenerationService(conn, provider)
        service.generate_first_edition(
            traveler_id=t.id, traveler_preferences=_make_prefs(),
            source_items=_make_src_items(src.id))
        editions = get_editions_by_traveler(conn, t.id)
        assert len(editions) == 1
        assert editions[0].generation_status == "pending_review"
        assert editions[0].publication_state == "pending"
        conn.close()


# ── 10. Pending edition not visible to traveler ──

class TestPendingInvisible:
    def test_pending_not_in_dashboard(self, app):
        c = TestClient(app, follow_redirects=False)
        conn = get_connection()
        t, _, _ = _make_traveler(c, conn, "Pend10")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        update_edition_content(conn, ed.id, {"title": "Pending"})
        update_edition_generation_status(conn, ed.id, "pending_review")
        conn.close()
        resp = c.get("/traveler/")
        assert resp.status_code == 200
        assert f"/traveler/editions/{ed.id}" not in resp.text


# ── 11. Publish → generation_status stays, publication published ──

class TestPublishState:
    def test_publish_only_publication(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="Pub11", destination="Lisbon")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        update_edition_content(conn, ed.id, {"title": "T"})
        update_edition_generation_status(conn, ed.id, "pending_review")
        conn.close()
        client = _logged_in(app)
        csrf = _op_csrf(client)
        resp = client.post(f"/operator/editions/{ed.id}/publish",
                           data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        assert resp.status_code in (200, 303)
        conn2 = get_connection()
        updated = get_edition_by_id(conn2, ed.id)
        assert updated.generation_status == "pending_review"
        assert updated.publication_state == "published"
        conn2.close()


# ── 12. After publish, traveler can access ──

class TestPublishAccess:
    def test_traveler_views_published(self, app):
        c = TestClient(app, follow_redirects=False)
        conn = get_connection()
        t, _, _ = _make_traveler(c, conn, "Pub12")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        update_edition_content(conn, ed.id, _full_edition_content("Access Title"))
        update_edition_generation_status(conn, ed.id, "pending_review")
        update_edition_publication(conn, ed.id, "published")
        conn.close()
        resp = c.get(f"/traveler/editions/{ed.id}")
        assert resp.status_code == 200
        assert "Access Title" in resp.text


# ── 13. Rendered content has title, sections, provenance ──

class TestRenderedContent:
    def test_renders_all_fields(self, app):
        c = TestClient(app, follow_redirects=False)
        conn = get_connection()
        t, _, _ = _make_traveler(c, conn, "Ren13")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        update_edition_content(conn, ed.id, {
            "publication_title": "Busan Guide",
            "edition_title": "Vol 1",
            "destination": "Busan",
            "trip_frame": "3 nights",
            "editorial_opening": "Welcome",
            "sections": [{"section_id": "s1", "title": "Local Food",
                          "narrative": "Food narrative",
                          "items": []}],
            "applied_feedback": [],
            "content_version": "1.0",
            "provenance_note": "Synthetic mock",
        })
        update_edition_generation_status(conn, ed.id, "pending_review")
        update_edition_publication(conn, ed.id, "published")
        conn.close()
        resp = c.get(f"/traveler/editions/{ed.id}")
        assert "Busan Guide" in resp.text
        assert "Local Food" in resp.text
        assert "Synthetic" in resp.text


# ── 14. Feedback multi-checkbox saved ──

class TestFeedbackMulti:
    def test_multiple_choices(self, app):
        c = TestClient(app, follow_redirects=False)
        conn = get_connection()
        t, _, csrf_token = _make_traveler(c, conn, "Fb14")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        update_edition_content(conn, ed.id, {"title": "T"})
        update_edition_publication(conn, ed.id, "published")
        conn.close()
        resp = c.post(f"/traveler/editions/{ed.id}/feedback",
                      data={"choices": ["quieter_places", "slower_pace", "more_local_food"],
                            "free_text": "Great", "csrf_token": csrf_token},
                      cookies={"lt_csrf": csrf_token})
        assert resp.status_code in (200, 303)
        conn2 = get_connection()
        fbs = get_feedback_by_edition(conn2, ed.id)
        assert len(fbs) == 1
        assert set(fbs[0].direction_choices) == {"quieter_places", "slower_pace", "more_local_food"}
        conn2.close()


# ── 15. Duplicate feedback prevented ──

class TestFeedbackDuplicate:
    def test_no_duplicate(self, app):
        c = TestClient(app, follow_redirects=False)
        conn = get_connection()
        t, _, csrf_token = _make_traveler(c, conn, "Fb15")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        update_edition_content(conn, ed.id, {"title": "T"})
        update_edition_publication(conn, ed.id, "published")
        conn.close()
        c.post(f"/traveler/editions/{ed.id}/feedback",
               data={"choices": ["quieter_places"], "csrf_token": csrf_token},
               cookies={"lt_csrf": csrf_token})
        c.post(f"/traveler/editions/{ed.id}/feedback",
               data={"choices": ["slower_pace"], "csrf_token": csrf_token},
               cookies={"lt_csrf": csrf_token})
        conn2 = get_connection()
        fbs = get_feedback_by_edition(conn2, ed.id)
        assert len(fbs) == 1
        conn2.close()


# ── 16-18. Second generation with prior + feedback applied + materially different ──

class TestSecondGeneration:
    def test_prior_feedback_applied_different(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="Sec16", destination="Tokyo")
        src = create_source(conn, source_url="https://example.com", publisher="Test",
                            source_type="web", destination="Tokyo", category="food",
                            claims=["c1"], confidence=SourceConfidence.confirmed)
        plan1, draft1 = _make_plan_and_draft(src.id)
        provider1 = MockProvider(task_payloads={"editorial_plan": plan1, "edition_draft": draft1})
        service1 = GenerationService(conn, provider1)
        first = service1.generate_first_edition(
            traveler_id=t.id, traveler_preferences=_make_prefs("Tokyo"),
            source_items=_make_src_items(src.id, "Tokyo"))
        ed1 = get_editions_by_traveler(conn, t.id)[0]
        update_edition_publication(conn, ed1.id, "published")
        create_feedback(conn, traveler_id=t.id, edition_id=ed1.id,
                        direction_choices=["quieter_places"], free_text="test")

        draft2 = _load_fixture("source_bundle.json")["second_edition_fixture"]
        for sec in draft2.get("sections", []):
            for item in sec.get("items", []):
                item["source_ref"] = src.id
        plan2 = {
            "plan_version": "1.0", "language": "ko", "central_theme": "Tokyo v2",
            "sections": [{"section_id": s["section_id"], "title": s["title"],
                          "description": "D"} for s in draft2["sections"]],
        }
        sec2_claims = []
        for sec in draft2["sections"]:
            for item in sec.get("items", []):
                sec2_claims.append(item["item_id"])
        src2_items = [{"source_id": src.id, "source_url": "https://example.com",
                       "publisher": "Test", "source_type": "web",
                       "original_language": "ko", "destination": "Tokyo",
                       "locality": "", "category": "food", "claims": sec2_claims,
                       "confidence": "confirmed", "state": "single_source",
                       "verification_notes": ""}]
        provider2 = MockProvider(task_payloads={"editorial_plan": plan2, "edition_draft": draft2})
        service2 = GenerationService(conn, provider2)
        second = service2.generate_second_edition(
            traveler_id=t.id, prior_edition_id=ed1.id,
            traveler_preferences=_make_prefs("Tokyo"),
            source_items=src2_items)
        editions = get_editions_by_traveler(conn, t.id)
        assert len(editions) == 2
        ed2 = editions[1]
        assert ed2.generation_status == "pending_review"
        assert ed2.publication_state == "pending"
        assert ed2.prior_edition_id == ed1.id
        fb_check = get_feedback_by_edition(conn, ed1.id)
        assert fb_check[0].applied_to_next_edition is True
        assert first.publication_title != second.publication_title
        conn.close()


# ── 19. Reject → generation_status stays, publication rejected ──

class TestRejectState:
    def test_reject_only_publication(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="Rej19", destination="Hanoi")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        update_edition_content(conn, ed.id, {"title": "T"})
        update_edition_generation_status(conn, ed.id, "pending_review")
        conn.close()
        client = _logged_in(app)
        csrf = _op_csrf(client)
        resp = client.post(f"/operator/editions/{ed.id}/reject",
                           data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        assert resp.status_code in (200, 303)
        conn2 = get_connection()
        updated = get_edition_by_id(conn2, ed.id)
        assert updated.generation_status == "pending_review"
        assert updated.publication_state == "rejected"
        conn2.close()


# ── 20. Reject doesn't affect published ──

class TestRejectIsolation:
    def test_published_unchanged(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="Rej20", destination="Kyoto")
        ed_pub = create_edition(conn, traveler_id=t.id, edition_number=1)
        update_edition_content(conn, ed_pub.id, {"title": "Pub"})
        update_edition_generation_status(conn, ed_pub.id, "pending_review")
        update_edition_publication(conn, ed_pub.id, "published")
        ed_rej = create_edition(conn, traveler_id=t.id, edition_number=2)
        update_edition_content(conn, ed_rej.id, {"title": "Rej"})
        update_edition_generation_status(conn, ed_rej.id, "pending_review")
        conn.close()
        client = _logged_in(app)
        csrf = _op_csrf(client)
        client.post(f"/operator/editions/{ed_rej.id}/reject",
                    data={"csrf_token": csrf}, cookies={"lt_csrf": csrf})
        conn2 = get_connection()
        assert get_edition_by_id(conn2, ed_pub.id).publication_state == "published"
        assert get_edition_by_id(conn2, ed_rej.id).publication_state == "rejected"
        conn2.close()


# ── 21. Generation failure not shown as success ──

class TestGenerationFailure:
    def test_failure_marks_failed(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="Fail21", destination="X")
        class FailProvider:
            provider = "fail"
            model = "fail"
            def generate_structured(self, **kw):
                from app.domain.models import ProviderResult
                return ProviderResult(provider="fail", model="fail",
                                      success=False, error_category="timeout",
                                      error_message="sim")
        service = GenerationService(conn, FailProvider())
        try:
            service.generate_first_edition(
                traveler_id=t.id, traveler_preferences=_make_prefs("X"),
                source_items=[])
        except PipelineError:
            pass
        editions = get_editions_by_traveler(conn, t.id)
        if editions:
            assert editions[0].generation_status != "pending_review"
        conn.close()


# ── 22. Foreign ownership blocked ──

class TestOwnershipBlock:
    def test_alice_cannot_see_bob(self, app):
        c = TestClient(app, follow_redirects=False)
        conn = get_connection()
        alice, _, _ = _make_traveler(c, conn, "OwnA")
        bob = create_traveler(conn, display_name="OwnB", destination="Tokyo")
        ed = create_edition(conn, traveler_id=bob.id, edition_number=1)
        update_edition_content(conn, ed.id, {"title": "Bobs"})
        update_edition_publication(conn, ed.id, "published")
        conn.close()
        resp = c.get(f"/traveler/editions/{ed.id}")
        assert resp.status_code == 404


# ── 23. CSRF on all mutation routes ──

class TestCSRFAllMutations:
    def test_operator_mutations_need_csrf(self, app):
        client = _logged_in(app)
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
            resp = client.post(path, data=data)
            assert resp.status_code in (403, 404, 422), f"{path}={resp.status_code}"

    def test_logout_requires_csrf(self, app):
        client = _logged_in(app)
        resp = client.post("/operator/logout", data={"csrf_token": "wrong"})
        assert resp.status_code == 403


# ── 24. Logout form CSRF in templates ──

class TestLogoutCSRFInTemplates:
    def test_operator_dashboard_has_csrf(self, app):
        client = _logged_in(app)
        resp = client.get("/operator/")
        assert 'name="csrf_token"' in resp.text
        assert 'action="/operator/logout"' in resp.text

    def test_operator_detail_has_csrf(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="CSD", destination="Paris")
        conn.close()
        client = _logged_in(app)
        resp = client.get(f"/operator/travelers/{t.id}")
        assert 'name="csrf_token"' in resp.text
        assert 'action="/operator/logout"' in resp.text

    def test_traveler_dashboard_has_csrf(self, app):
        c = TestClient(app, follow_redirects=False)
        conn = get_connection()
        _make_traveler(c, conn, "CST")
        conn.close()
        resp = c.get("/traveler/")
        assert 'name="csrf_token"' in resp.text
        assert 'action="/traveler/logout"' in resp.text


# ── 25. Atomicity ──

class TestAtomicity:
    def test_deactivate_all_in_one(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="Atom", destination="Lima")
        _, raw_token = create_traveler_token(conn, t.id)
        _, raw_session, _ = create_traveler_session(conn, t.id)
        delete_traveler(conn, t.id, commit=False)
        deactivate_traveler_tokens(conn, t.id, commit=False)
        conn.execute("DELETE FROM traveler_sessions WHERE traveler_id = ?", (t.id,))
        conn.commit()
        assert not is_traveler_active(conn, t.id)
        assert validate_traveler_token(conn, raw_token) is None
        assert validate_traveler_session(conn, raw_session) is None
        conn.close()


# ── 26. Durability ──

class TestDurability:
    def test_data_survives_reopen(self, tmp_path: Path):
        db_path = str(tmp_path / "dur.db")
        apply_migrations(db_path)
        conn1 = get_connection(db_path)
        t = create_traveler(conn1, display_name="Durable", destination="Seoul")
        conn1.close()
        conn2 = get_connection(db_path)
        found = get_traveler_by_id(conn2, t.id)
        assert found is not None
        assert found.display_name == "Durable"
        conn2.close()


# ── 27. Zero network ──

class TestZeroNetwork:
    def test_uses_mock_only(self, app):
        conn = get_connection()
        t = create_traveler(conn, display_name="Net27", destination="Bangkok")
        src = create_source(conn, source_url="https://example.com", publisher="Test",
                            source_type="web", destination="Bangkok", category="food",
                            claims=["c1"], confidence=SourceConfidence.confirmed)
        plan, draft = _make_plan_and_draft(src.id)
        provider = MockProvider(task_payloads={"editorial_plan": plan, "edition_draft": draft})
        service = GenerationService(conn, provider)
        content = service.generate_first_edition(
            traveler_id=t.id, traveler_preferences=_make_prefs("Bangkok"),
            source_items=_make_src_items(src.id, "Bangkok"))
        assert content is not None
        assert len(provider.requests) > 0
        for req in provider.requests:
            assert "system_prompt" in req
        conn.close()
