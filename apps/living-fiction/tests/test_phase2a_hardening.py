"""Phase 2A corrective-hardening tests.

Covers the CTO-review defect fixes:
- Invite codes are bound to a reader; login never creates a reader (Defect 1)
- Production runtime imports never reach the ``tests`` package (Defect 2)
- CSRF tokens are purpose-bound and not reusable across contexts (Defect 3)
- Logout is a CSRF-protected POST; GET logout is non-mutating (Defect 4)
- Approve/reject write an immutable audit row atomically (Defects 5/6)
- The reader ``/read`` query returns the latest published CANON episode (Defect 7)
- Sessions honour absolute expiry and revocation (Defect 9)
- Security headers are scoped by response kind (Defect 10)
- Web secrets fail closed and are validated strictly in production (Defect 10)
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth
from app import episode_repository as ep_repo
from app import reader_repository as reader_repo
from app.config import Settings, settings
from app.db import apply_migrations, get_connection
from app.dev_seed import _seed_canon, _seed_invite, _seed_world
from app.preview_data import WORLD_STATE

WORLD_ID = WORLD_STATE.world_id


# ── Helpers ────────────────────────────────────────────────────────────────


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "CSRF token not found in form"
    return match.group(1)


def _seed_test_db(db_path: str) -> str:
    conn = get_connection(db_path)
    try:
        migrations_dir = str(Path(__file__).resolve().parent.parent / "migrations")
        apply_migrations(conn, migrations_dir)
        _seed_world(conn)
        _seed_canon(conn)
        return _seed_invite(conn)
    finally:
        conn.close()


def _login_reader(client: TestClient, invite_code: str) -> None:
    resp = client.get("/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/access",
        data={"invite_code": invite_code, "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def _login_admin(client: TestClient) -> None:
    resp = client.get("/admin/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/admin/access",
        data={"admin_secret": "test-admin-secret", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def _logout_reader(client: TestClient) -> None:
    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/logout", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert resp.status_code == 303


def _submit_choice(client: TestClient) -> None:
    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    client.post(
        "/read",
        data={"choice": "0", "comment": "hardening", "csrf_token": csrf},
        follow_redirects=False,
    )


def _first_pending_branch_id(client: TestClient) -> str:
    resp = client.get("/admin/review")
    match = re.search(r'/admin/review/([^"]+)"', resp.text)
    assert match, "no pending branch in review queue"
    return match.group(1)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def app_client(temp_db_path):
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


# ── Defect 1: invite bound to a reader; login never creates one ────────────


def test_login_reuses_bound_reader_without_creating(app_client, db_conn):
    client, code = app_client
    before = db_conn.execute("SELECT COUNT(*) c FROM readers").fetchone()["c"]
    _login_reader(client, code)
    after = db_conn.execute("SELECT COUNT(*) c FROM readers").fetchone()["c"]
    assert after == before


def test_unbound_invite_cannot_login_or_create(app_client, db_conn):
    client, _ = app_client
    before = db_conn.execute("SELECT COUNT(*) c FROM readers").fetchone()["c"]
    code = auth.generate_invite_code()
    # No bound_reader_id → unusable for login.
    auth.create_invite_credential(db_conn, code, settings.credential_hmac_key)

    resp = client.get("/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/access", data={"invite_code": code, "csrf_token": csrf}
    )
    assert resp.status_code == 200
    assert "올바르지 않거나" in resp.text

    after = db_conn.execute("SELECT COUNT(*) c FROM readers").fetchone()["c"]
    assert after == before


def test_revoked_invite_cannot_login(app_client, db_conn):
    client, _ = app_client
    reader = reader_repo.create_reader(db_conn, display_name="취소 독자")
    code = auth.generate_invite_code()
    cred_id = auth.create_invite_credential(
        db_conn, code, settings.credential_hmac_key,
        bound_reader_id=reader.id, expires_at="9999-12-31T23:59:59Z",
    )
    assert auth.revoke_invite(db_conn, cred_id) is True

    resp = client.get("/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/access", data={"invite_code": code, "csrf_token": csrf}
    )
    assert resp.status_code == 200
    assert "올바르지 않거나" in resp.text


# ── Defect 2: production runtime never imports the tests package ───────────


def test_production_runtime_does_not_import_tests():
    root = Path(__file__).resolve().parent.parent
    script = (
        "import sys\n"
        "class _Blocker:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'tests' or name.startswith('tests.'):\n"
        "            raise ImportError('blocked import of ' + name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Blocker())\n"
        "import app.factory\n"
        "import app.web\n"
        "import app.dev_seed\n"
        "print('ISOLATION_OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "ISOLATION_OK" in result.stdout


# ── Defect 3: CSRF tokens are purpose-bound ────────────────────────────────


def test_csrf_tokens_are_purpose_bound():
    key = "test-key"
    token = "raw-session-token"

    reader_csrf = auth.compute_session_csrf(token, key, auth.CSRF_READER_SESSION)
    admin_csrf = auth.compute_session_csrf(token, key, auth.CSRF_ADMIN_SESSION)
    assert reader_csrf != admin_csrf

    assert auth.verify_session_csrf(
        token, key, auth.CSRF_READER_SESSION, reader_csrf
    )
    # A reader-purpose token must NOT satisfy an admin-purpose check.
    assert not auth.verify_session_csrf(
        token, key, auth.CSRF_ADMIN_SESSION, reader_csrf
    )

    preauth = auth.issue_preauth_csrf(key, auth.CSRF_READER_PREAUTH)
    assert auth.verify_preauth_csrf(
        key, auth.CSRF_READER_PREAUTH, preauth, preauth
    )
    assert not auth.verify_preauth_csrf(
        key, auth.CSRF_ADMIN_PREAUTH, preauth, preauth
    )


def test_reader_csrf_rejected_on_admin_endpoint(app_client, db_conn):
    client, code = app_client
    _login_reader(client, code)
    _submit_choice(client)

    # Grab the reader's session CSRF token from /read.
    reader_csrf = _extract_csrf(client.get("/read").text)

    _login_admin(client)
    branch_id = _first_pending_branch_id(client)

    # Using the reader-purpose token on an admin mutation must fail with 403.
    resp = client.post(
        f"/admin/review/{branch_id}/approve",
        data={"csrf_token": reader_csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403


# ── Defect 4: logout is a CSRF-protected POST; GET is non-mutating ─────────


def test_get_logout_is_non_mutating(app_client):
    client, code = app_client
    _login_reader(client, code)

    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303

    # Session still valid after a GET logout.
    assert client.get("/read", follow_redirects=False).status_code == 200


def test_post_logout_destroys_session(app_client):
    client, code = app_client
    _login_reader(client, code)

    _logout_reader(client)

    resp = client.get("/read", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/access"


# ── Defects 5/6: approve/reject write an atomic, immutable audit row ───────


def test_approve_writes_single_audit_row_and_publishes(app_client, db_conn):
    client, code = app_client
    _login_reader(client, code)
    _submit_choice(client)

    _login_admin(client)
    branch_id = _first_pending_branch_id(client)
    resp = client.get(f"/admin/review/{branch_id}")
    csrf = _extract_csrf(resp.text)
    client.post(
        f"/admin/review/{branch_id}/approve",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    rows = db_conn.execute(
        "SELECT decision, new_state FROM review_decisions WHERE branch_id = ?",
        (branch_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["decision"] == "approved"
    assert rows[0]["new_state"] == "published"


def test_reject_writes_audit_row_with_reason(app_client, db_conn):
    client, code = app_client
    _login_reader(client, code)
    _submit_choice(client)

    _login_admin(client)
    branch_id = _first_pending_branch_id(client)
    resp = client.get(f"/admin/review/{branch_id}")
    csrf = _extract_csrf(resp.text)
    client.post(
        f"/admin/review/{branch_id}/reject",
        data={"csrf_token": csrf, "rejection_reason": "품질 부족"},
        follow_redirects=False,
    )

    rows = db_conn.execute(
        "SELECT decision, rejection_reason, new_state "
        "FROM review_decisions WHERE branch_id = ?",
        (branch_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["decision"] == "rejected"
    assert rows[0]["rejection_reason"] == "품질 부족"


def test_duplicate_decision_conflicts_and_stays_single(app_client, db_conn):
    client, code = app_client
    _login_reader(client, code)
    _submit_choice(client)

    _login_admin(client)
    branch_id = _first_pending_branch_id(client)
    resp = client.get(f"/admin/review/{branch_id}")
    csrf = _extract_csrf(resp.text)
    client.post(
        f"/admin/review/{branch_id}/approve",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    # A second decision on the already-decided branch must fail cleanly.
    resp = client.post(
        f"/admin/review/{branch_id}/approve",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 409

    count = db_conn.execute(
        "SELECT COUNT(*) c FROM review_decisions WHERE branch_id = ?",
        (branch_id,),
    ).fetchone()["c"]
    assert count == 1


# ── Defect 7: /read serves the latest published CANON episode ──────────────


def test_latest_published_query_is_canon_only(app_client, db_conn):
    episode = ep_repo.get_latest_published_canon_episode(db_conn, WORLD_ID)
    assert episode is not None
    assert episode.episode_type == "canon"
    assert episode.review_state == "published"


# ── Defect 9: sessions honour absolute expiry and revocation ───────────────


def test_reader_session_expiry_and_revocation(db_conn):
    reader = reader_repo.create_reader(db_conn, display_name="세션 독자")
    token = auth.create_reader_session(db_conn, reader.id, "test-key")
    assert auth.get_reader_session(db_conn, token, "test-key") == reader.id

    # Expired → invalid.
    db_conn.execute(
        "UPDATE reader_sessions SET expires_at = '2000-01-01T00:00:00Z'"
    )
    db_conn.commit()
    assert auth.get_reader_session(db_conn, token, "test-key") is None

    # Restored expiry but revoked → invalid.
    db_conn.execute(
        "UPDATE reader_sessions SET expires_at = '9999-01-01T00:00:00Z', "
        "revoked_at = '2020-01-01T00:00:00Z'"
    )
    db_conn.commit()
    assert auth.get_reader_session(db_conn, token, "test-key") is None


def test_admin_session_expiry_and_revocation(db_conn):
    token = auth.create_admin_session(db_conn, "test-key")
    assert auth.get_admin_session(db_conn, token, "test-key") is True

    db_conn.execute(
        "UPDATE admin_sessions SET expires_at = '2000-01-01T00:00:00Z'"
    )
    db_conn.commit()
    assert auth.get_admin_session(db_conn, token, "test-key") is False

    db_conn.execute(
        "UPDATE admin_sessions SET expires_at = '9999-01-01T00:00:00Z', "
        "revoked_at = '2020-01-01T00:00:00Z'"
    )
    db_conn.commit()
    assert auth.get_admin_session(db_conn, token, "test-key") is False


# ── Defect 10: scoped security headers ─────────────────────────────────────


def test_html_responses_get_full_header_set(app_client):
    client, _ = app_client
    resp = client.get("/access")
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in resp.headers


def test_non_html_responses_get_minimal_headers(app_client):
    client, _ = app_client
    resp = client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers.get("Cache-Control") != "no-store"
    assert "Content-Security-Policy" not in resp.headers


# ── Defect 10: secret validation fails closed ──────────────────────────────


def test_secret_validation_requires_all_secrets():
    s = Settings(
        env="development",
        admin_secret="",
        credential_hmac_key="x",
        session_hmac_key="y",
    )
    with pytest.raises(ValueError):
        s.validate_web_secrets()


def test_secret_validation_dev_accepts_short_but_present():
    s = Settings(
        env="development",
        admin_secret="a",
        credential_hmac_key="b",
        session_hmac_key="c",
    )
    s.validate_web_secrets()  # non-empty is sufficient outside production


def test_secret_validation_prod_rejects_short():
    s = Settings(
        env="production",
        admin_secret="short",
        credential_hmac_key="also-short",
        session_hmac_key="tiny",
    )
    with pytest.raises(ValueError):
        s.validate_web_secrets()


def test_secret_validation_prod_rejects_reuse():
    shared = "a" * 40
    s = Settings(
        env="production",
        admin_secret=shared,
        credential_hmac_key=shared,
        session_hmac_key="b" * 40,
    )
    with pytest.raises(ValueError):
        s.validate_web_secrets()


def test_secret_validation_prod_rejects_placeholder():
    s = Settings(
        env="production",
        admin_secret="changeme",
        credential_hmac_key="b" * 40,
        session_hmac_key="c" * 40,
    )
    with pytest.raises(ValueError):
        s.validate_web_secrets()


def test_secret_validation_prod_accepts_strong_distinct():
    s = Settings(
        env="production",
        admin_secret="a" * 40,
        credential_hmac_key="b" * 40,
        session_hmac_key="c" * 40,
    )
    s.validate_web_secrets()  # no error
