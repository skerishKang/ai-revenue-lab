"""Phase 2A visual vertical slice tests — reader UI and editorial review.

Tests cover:
- Reader invite access (GET/POST)
- Canon read screen
- Choice submission with PRG redirect
- Pending status screen
- Pending branch body blocking
- Admin access and review queue
- Approve/reject
- Owner branch read after approval
- Foreign reader branch blocking
- Comment escaping
- CSRF rejection
- Reader/admin session separation
- Security headers
- /health
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth
from app import branch_repository as branch_repo
from app import choice_repository as choice_repo
from app import episode_repository as ep_repo
from app import reader_repository as reader_repo
from app.config import settings
from app.db import apply_migrations, get_connection
from app.dev_seed import _seed_canon, _seed_invite, _seed_world


# ── Helpers ────────────────────────────────────────────────────────────────


def _extract_csrf(html: str) -> str:
    """Extract CSRF token from an HTML form."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "CSRF token not found in form"
    return match.group(1)


def _seed_test_db(db_path: str) -> str:
    """Seed the test DB with world, canon, and invite. Returns invite code."""
    conn = get_connection(db_path)
    try:
        migrations_dir = str(Path(__file__).resolve().parent.parent / "migrations")
        apply_migrations(conn, migrations_dir)
        _seed_world(conn)
        _seed_canon(conn)
        code = _seed_invite(conn)
        return code
    finally:
        conn.close()


def _login_reader(client: TestClient, invite_code: str) -> TestClient:
    """Log in as a reader using an invite code. Returns the client (with cookies)."""
    resp = client.get("/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/access",
        data={"invite_code": invite_code, "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return client


def _login_admin(client: TestClient) -> TestClient:
    """Log in as admin. Returns the client (with cookies)."""
    resp = client.get("/admin/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/admin/access",
        data={"admin_secret": "test-admin-secret", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return client


def _logout_reader(client: TestClient) -> None:
    """Log out the current reader via the CSRF-protected POST /logout."""
    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/logout", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert resp.status_code == 303


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def app_client(temp_db_path):
    """Create a test app with web routes and seeded data."""
    orig = {
        "admin_secret": settings.admin_secret,
        "credential_hmac_key": settings.credential_hmac_key,
        "session_hmac_key": settings.session_hmac_key,
        "database_path": settings.database_path,
    }
    settings.admin_secret = "test-admin-secret"
    settings.credential_hmac_key = "test-credential-hmac-key"
    settings.session_hmac_key = "test-session-hmac-key"
    settings.database_path = temp_db_path

    try:
        from app.factory import create_app
        app = create_app()
        with TestClient(app, follow_redirects=False) as client:
            code = _seed_test_db(temp_db_path)
            yield client, code
    finally:
        for key, value in orig.items():
            setattr(settings, key, value)


@pytest.fixture
def db_conn(temp_db_path):
    """Provide a DB connection to the test app's database."""
    conn = get_connection(temp_db_path)
    migrations_dir = str(Path(__file__).resolve().parent.parent / "migrations")
    apply_migrations(conn, migrations_dir)
    yield conn
    conn.close()


# ── Reader access tests ────────────────────────────────────────────────────


def test_access_get_200(app_client):
    """GET /access returns 200."""
    client, _ = app_client
    resp = client.get("/access")
    assert resp.status_code == 200
    assert "Living Fiction" in resp.text
    assert "한 시간을 잃어버리는 도시" in resp.text


def test_invite_login(app_client):
    """Valid invite code logs in and redirects to /read."""
    client, code = app_client
    _login_reader(client, code)
    resp = client.get("/read", follow_redirects=False)
    assert resp.status_code == 200
    assert "CANON" in resp.text


def test_invalid_invite_privacy_safe(app_client):
    """Invalid invite code returns privacy-safe failure."""
    client, _ = app_client
    resp = client.get("/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/access",
        data={"invite_code": "invalid-code", "csrf_token": csrf},
    )
    assert resp.status_code == 200
    assert "올바르지 않거나" in resp.text
    # Should NOT reveal whether the code exists
    assert "already used" not in resp.text.lower()


def test_access_shows_ai_disclosure(app_client):
    """Access screen includes AI generation disclosure."""
    client, _ = app_client
    resp = client.get("/access")
    assert "AI" in resp.text


# ── Canon read tests ──────────────────────────────────────────────────────


def test_canon_read_200(app_client):
    """Canon read screen returns 200 after login."""
    client, code = app_client
    _login_reader(client, code)
    resp = client.get("/read")
    assert resp.status_code == 200
    assert "CANON 01" in resp.text


def test_canon_shows_choice_options(app_client):
    """Canon read screen displays choice option cards."""
    client, code = app_client
    _login_reader(client, code)
    resp = client.get("/read")
    assert resp.status_code == 200
    # Should show choice options as card UI
    assert "choice-card" in resp.text
    assert "제출하기" in resp.text


def test_canon_shows_optional_comment_field(app_client):
    """Canon read screen has an optional comment textarea."""
    client, code = app_client
    _login_reader(client, code)
    resp = client.get("/read")
    assert resp.status_code == 200
    assert "comment" in resp.text
    assert "textarea" in resp.text


# ── Choice submission tests ────────────────────────────────────────────────


def test_choice_submit_prg_redirect(app_client):
    """Choice submission returns 303 redirect (PRG pattern)."""
    client, code = app_client
    _login_reader(client, code)

    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/read",
        data={"choice": "0", "comment": "test comment", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/read/status" in resp.headers["location"]


def test_choice_creates_pending_branch(app_client, db_conn):
    """Choice submission creates a pending_review branch."""
    client, code = app_client
    _login_reader(client, code)

    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    client.post(
        "/read",
        data={"choice": "0", "comment": "test comment", "csrf_token": csrf},
        follow_redirects=False,
    )

    # Check branch exists in pending_review state
    branches = branch_repo.get_branches_by_reader(
        db_conn, _get_reader_id(db_conn, client)
    )
    assert len(branches) == 1
    ep = ep_repo.get_episode_by_id(db_conn, branches[0].branch_episode_id)
    assert ep.review_state == "pending_review"


def _get_reader_id(db_conn, client):
    """Get the reader ID from the session cookie."""
    # The reader is the most recently created
    readers = reader_repo.get_all_readers(db_conn)
    return readers[-1].id


# ── Pending status tests ──────────────────────────────────────────────────


def test_pending_status_screen(app_client):
    """Pending status screen returns 200 and shows timeline."""
    client, code = app_client
    _login_reader(client, code)

    # Submit a choice first
    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    client.post(
        "/read",
        data={"choice": "0", "comment": "test", "csrf_token": csrf},
        follow_redirects=False,
    )

    resp = client.get("/read/status")
    assert resp.status_code == 200
    assert "PENDING" in resp.text or "pending" in resp.text.lower()
    assert "timeline" in resp.text.lower()


def test_pending_branch_body_blocked(app_client, db_conn):
    """Pending branch body is blocked from reader view."""
    client, code = app_client
    _login_reader(client, code)

    # Submit a choice
    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    client.post(
        "/read",
        data={"choice": "0", "comment": "test", "csrf_token": csrf},
        follow_redirects=False,
    )

    # Get the branch ID
    reader_id = _get_reader_id(db_conn, client)
    branches = branch_repo.get_branches_by_reader(db_conn, reader_id)
    branch_id = branches[0].id

    # Try to access the pending branch
    resp = client.get(f"/read/branch/{branch_id}")
    assert resp.status_code == 403


# ── Admin tests ────────────────────────────────────────────────────────────


def test_admin_login(app_client):
    """Admin login with correct secret redirects to review queue."""
    client, _ = app_client
    _login_admin(client)
    resp = client.get("/admin/review")
    assert resp.status_code == 200


def test_admin_login_wrong_secret(app_client):
    """Admin login with wrong secret fails."""
    client, _ = app_client
    resp = client.get("/admin/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/admin/access",
        data={"admin_secret": "wrong", "csrf_token": csrf},
    )
    assert resp.status_code == 200
    assert "올바르지 않습니다" in resp.text


def test_review_queue_shows_pending(app_client):
    """Review queue shows pending branches after a choice is submitted."""
    client, code = app_client
    _login_reader(client, code)

    # Submit a choice
    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    client.post(
        "/read",
        data={"choice": "0", "comment": "test", "csrf_token": csrf},
        follow_redirects=False,
    )

    # Log in as admin and check review queue
    _login_admin(client)
    resp = client.get("/admin/review")
    assert resp.status_code == 200
    assert "EDITORIAL QUEUE" in resp.text


def test_review_detail_shows_branch(app_client):
    """Review detail shows branch content for admin."""
    client, code = app_client
    _login_reader(client, code)

    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    client.post(
        "/read",
        data={"choice": "0", "comment": "test comment", "csrf_token": csrf},
        follow_redirects=False,
    )

    _login_admin(client)
    resp = client.get("/admin/review")
    # Extract branch ID from the review queue
    match = re.search(r'/admin/review/([^"]+)"', resp.text)
    assert match, "Branch link not found in review queue"
    branch_id = match.group(1)

    resp = client.get(f"/admin/review/{branch_id}")
    assert resp.status_code == 200
    assert "REVIEW" in resp.text


def test_approve_branch(app_client, db_conn):
    """Admin approve changes branch state to published."""
    client, code = app_client
    _login_reader(client, code)

    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    client.post(
        "/read",
        data={"choice": "0", "comment": "test", "csrf_token": csrf},
        follow_redirects=False,
    )

    _login_admin(client)
    resp = client.get("/admin/review")
    match = re.search(r'/admin/review/([^"]+)"', resp.text)
    branch_id = match.group(1)

    # Get CSRF from review detail
    resp = client.get(f"/admin/review/{branch_id}")
    csrf = _extract_csrf(resp.text)

    resp = client.post(
        f"/admin/review/{branch_id}/approve",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Verify branch is published
    branch = branch_repo.get_branch(db_conn, branch_id)
    ep = ep_repo.get_episode_by_id(db_conn, branch.branch_episode_id)
    assert ep.review_state == "published"


def test_reject_branch(app_client, db_conn):
    """Admin reject changes branch state to rejected."""
    client, code = app_client
    _login_reader(client, code)

    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    client.post(
        "/read",
        data={"choice": "0", "comment": "test", "csrf_token": csrf},
        follow_redirects=False,
    )

    _login_admin(client)
    resp = client.get("/admin/review")
    match = re.search(r'/admin/review/([^"]+)"', resp.text)
    branch_id = match.group(1)

    resp = client.get(f"/admin/review/{branch_id}")
    csrf = _extract_csrf(resp.text)

    resp = client.post(
        f"/admin/review/{branch_id}/reject",
        data={"csrf_token": csrf, "rejection_reason": "test rejection"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    branch = branch_repo.get_branch(db_conn, branch_id)
    ep = ep_repo.get_episode_by_id(db_conn, branch.branch_episode_id)
    assert ep.review_state == "rejected"


def test_approve_then_owner_reads_branch(app_client, db_conn):
    """After approval, owner can read their published branch."""
    client, code = app_client
    _login_reader(client, code)

    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    client.post(
        "/read",
        data={"choice": "0", "comment": "test", "csrf_token": csrf},
        follow_redirects=False,
    )

    # Approve as admin
    _login_admin(client)
    resp = client.get("/admin/review")
    match = re.search(r'/admin/review/([^"]+)"', resp.text)
    branch_id = match.group(1)
    resp = client.get(f"/admin/review/{branch_id}")
    csrf = _extract_csrf(resp.text)
    client.post(
        f"/admin/review/{branch_id}/approve",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    # Log back in as reader and read the branch
    _logout_reader(client)
    _login_reader(client, code)
    resp = client.get(f"/read/branch/{branch_id}")
    assert resp.status_code == 200
    assert "PERSONAL BRANCH" in resp.text


def test_foreign_reader_branch_blocked(app_client, db_conn):
    """Foreign reader cannot access another reader's branch."""
    client, code = app_client
    _login_reader(client, code)

    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    client.post(
        "/read",
        data={"choice": "0", "comment": "test", "csrf_token": csrf},
        follow_redirects=False,
    )

    # Approve as admin
    _login_admin(client)
    resp = client.get("/admin/review")
    match = re.search(r'/admin/review/([^"]+)"', resp.text)
    branch_id = match.group(1)
    resp = client.get(f"/admin/review/{branch_id}")
    csrf = _extract_csrf(resp.text)
    client.post(
        f"/admin/review/{branch_id}/approve",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    # Create a second reader (login assumes a bound reader; it never creates one)
    _logout_reader(client)
    reader = reader_repo.create_reader(db_conn, display_name="다른 독자")
    raw_code = auth.generate_invite_code()
    auth.create_invite_credential(
        db_conn,
        raw_code,
        settings.credential_hmac_key,
        bound_reader_id=reader.id,
        expires_at="9999-12-31T23:59:59Z",
    )
    _login_reader(client, raw_code)

    # Try to access the first reader's branch
    resp = client.get(f"/read/branch/{branch_id}")
    assert resp.status_code == 403


# ── Escaping tests ─────────────────────────────────────────────────────────


def test_user_comment_escaping(app_client):
    """User comment with HTML is escaped in admin review."""
    client, code = app_client
    _login_reader(client, code)

    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    client.post(
        "/read",
        data={
            "choice": "0",
            "comment": "<script>alert('xss')</script>",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    _login_admin(client)
    resp = client.get("/admin/review")
    match = re.search(r'/admin/review/([^"]+)"', resp.text)
    branch_id = match.group(1)
    resp = client.get(f"/admin/review/{branch_id}")
    # Script tag should be escaped, not rendered
    assert "<script>alert('xss')</script>" not in resp.text
    assert "&lt;script&gt;" in resp.text


def test_generated_prose_escaping(app_client):
    """Generated prose is HTML-escaped in templates."""
    client, code = app_client
    _login_reader(client, code)
    resp = client.get("/read")
    assert resp.status_code == 200
    # Jinja autoescape should be active — no raw HTML injection
    assert "<script>" not in resp.text


# ── CSRF tests ─────────────────────────────────────────────────────────────


def test_csrf_missing_rejected(app_client):
    """POST without CSRF token is rejected with 403."""
    client, code = app_client
    _login_reader(client, code)
    resp = client.post("/read", data={"choice": "0"}, follow_redirects=False)
    assert resp.status_code == 403


def test_csrf_invalid_rejected(app_client):
    """POST with invalid CSRF token is rejected with 403."""
    client, code = app_client
    _login_reader(client, code)
    resp = client.post(
        "/read",
        data={"choice": "0", "csrf_token": "invalid"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


# ── Session separation tests ───────────────────────────────────────────────


def test_reader_admin_session_separation(app_client):
    """Reader session cannot access admin routes."""
    client, code = app_client
    _login_reader(client, code)
    resp = client.get("/admin/review")
    assert resp.status_code == 303
    assert "/admin/access" in resp.headers["location"]


def test_admin_reader_session_separation(app_client):
    """Admin session cannot access reader routes."""
    client, _ = app_client
    _login_admin(client)
    resp = client.get("/read")
    assert resp.status_code == 303
    assert "/access" in resp.headers["location"]


# ── Security headers tests ──────────────────────────────────────────────────


def test_security_headers(app_client):
    """Security headers are present on responses."""
    client, _ = app_client
    resp = client.get("/access")
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in resp.headers


def test_no_external_assets(app_client):
    """No external CSS, JS, or font assets are loaded."""
    client, _ = app_client
    resp = client.get("/access")
    assert "https://" not in resp.text
    assert "http://" not in resp.text
    # Only local static asset
    assert "/static/style.css" in resp.text


# ── Health test ────────────────────────────────────────────────────────────


def test_health_200(app_client):
    """/health returns 200 with provider info."""
    client, _ = app_client
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["ai_provider"] == "mock"
