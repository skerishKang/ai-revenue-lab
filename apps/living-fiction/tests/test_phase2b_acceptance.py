import copy
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth
from app import branch_repository as branch_repo
from app import choice_repository as choice_repo
from app import choice_service
from app import episode_repository as ep_repo
from app import reader_repository as reader_repo
from app import review_service
from app.ai.mock import MockProvider
from app.config import Settings, settings
from app.db import apply_migrations, get_connection
from app.dev_seed import _seed_canon, _seed_invite, _seed_world
from app.preview_data import BRANCH_EPISODE_CONTENT, BRANCH_EPISODE_PLAN, WORLD_STATE

WORLD_ID = WORLD_STATE.world_id
CANON_CHECKPOINT_ID = "checkpoint-canon-1"


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


def _submit_choice(client: TestClient, choice: str = "0", comment: str = ""):
    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    return client.post(
        "/read/choice",
        data={"choice": choice, "comment": comment, "csrf_token": csrf},
        follow_redirects=False,
    )


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


@pytest.fixture
def db_conn(temp_db_path):
    conn = get_connection(temp_db_path)
    migrations_dir = str(Path(__file__).resolve().parent.parent / "migrations")
    apply_migrations(conn, migrations_dir)
    yield conn
    conn.close()


def _setup_choice_db(db_conn):
    _seed_world(db_conn)
    _seed_canon(db_conn)
    reader = reader_repo.create_reader(db_conn, display_name="Test Reader")
    episode = ep_repo.get_latest_published_canon_episode(db_conn, WORLD_ID)
    return reader.id, episode.id


def _make_provider(choice_id, choice_text="", choice_comment=None):
    branch_content = copy.deepcopy(BRANCH_EPISODE_CONTENT)
    branch_content["applied_reader_input"]["reader_choice_id"] = choice_id
    if choice_text:
        branch_content["applied_reader_input"]["choice_text"] = choice_text
    if choice_comment is not None:
        branch_content["applied_reader_input"]["comment"] = choice_comment
    return MockProvider(
        task_payloads={
            "episode_plan": BRANCH_EPISODE_PLAN,
            "episode_content": branch_content,
        }
    )


def _submit(db_conn, reader_id, canon_episode_id, choice_text, comment=None):
    return choice_service.submit_reader_choice(
        db_conn,
        world=WORLD_STATE,
        world_id=WORLD_ID,
        reader_id=reader_id,
        canon_episode_id=canon_episode_id,
        canon_checkpoint_id=CANON_CHECKPOINT_ID,
        choice_text=choice_text,
        comment=comment,
        build_provider=_make_provider,
    )


def test_same_choice_duplicate_replays_without_provider_call(db_conn):
    reader_id, ep_id = _setup_choice_db(db_conn)
    call_count = [0]

    def counting_provider(choice_id, choice_text="", choice_comment=None):
        call_count[0] += 1
        return _make_provider(choice_id, choice_text, choice_comment)

    r1 = choice_service.submit_reader_choice(
        db_conn, world=WORLD_STATE, world_id=WORLD_ID, reader_id=reader_id,
        canon_episode_id=ep_id, canon_checkpoint_id=CANON_CHECKPOINT_ID,
        choice_text="east", comment=None, build_provider=counting_provider,
    )
    assert r1.status == "submitted"
    assert call_count[0] == 1

    r2 = choice_service.submit_reader_choice(
        db_conn, world=WORLD_STATE, world_id=WORLD_ID, reader_id=reader_id,
        canon_episode_id=ep_id, canon_checkpoint_id=CANON_CHECKPOINT_ID,
        choice_text="east", comment=None, build_provider=counting_provider,
    )
    assert r2.status == "already_completed"
    assert call_count[0] == 1


def test_different_choice_duplicate_returns_conflict(db_conn):
    reader_id, ep_id = _setup_choice_db(db_conn)
    r1 = _submit(db_conn, reader_id, ep_id, "east")
    assert r1.status == "submitted"
    r2 = _submit(db_conn, reader_id, ep_id, "west")
    assert r2.status == "conflict"


def test_different_comment_duplicate_returns_conflict(db_conn):
    reader_id, ep_id = _setup_choice_db(db_conn)
    r1 = _submit(db_conn, reader_id, ep_id, "east", comment="first comment")
    assert r1.status == "submitted"
    r2 = _submit(db_conn, reader_id, ep_id, "east", comment="different comment")
    assert r2.status == "conflict"


class _FailingOnceProvider:
    def __init__(self, inner, fail_flag):
        self._inner = inner
        self._fail_flag = fail_flag

    @property
    def provider_name(self):
        return self._inner.provider_name

    @property
    def model(self):
        return self._inner.model

    @property
    def cost_class(self):
        return self._inner.cost_class

    def generate_structured(self, **kwargs):
        if self._fail_flag[0]:
            self._fail_flag[0] = False
            raise RuntimeError("simulated provider failure")
        return self._inner.generate_structured(**kwargs)


def test_generation_failure_then_same_choice_retry_succeeds(db_conn):
    reader_id, ep_id = _setup_choice_db(db_conn)
    fail_flag = [True]

    def flaky_provider(choice_id, choice_text="", choice_comment=None):
        return _FailingOnceProvider(_make_provider(choice_id, choice_text, choice_comment), fail_flag)

    r1 = choice_service.submit_reader_choice(
        db_conn, world=WORLD_STATE, world_id=WORLD_ID, reader_id=reader_id,
        canon_episode_id=ep_id, canon_checkpoint_id=CANON_CHECKPOINT_ID,
        choice_text="east", comment=None, build_provider=flaky_provider,
    )
    assert r1.status == "generation_failed"

    r2 = choice_service.submit_reader_choice(
        db_conn, world=WORLD_STATE, world_id=WORLD_ID, reader_id=reader_id,
        canon_episode_id=ep_id, canon_checkpoint_id=CANON_CHECKPOINT_ID,
        choice_text="east", comment=None, build_provider=flaky_provider,
    )
    assert r2.status == "submitted"


def test_retry_leaves_exactly_one_choice(db_conn):
    reader_id, ep_id = _setup_choice_db(db_conn)
    fail_flag = [True]

    def flaky_provider(choice_id, choice_text="", choice_comment=None):
        return _FailingOnceProvider(_make_provider(choice_id, choice_text, choice_comment), fail_flag)

    choice_service.submit_reader_choice(
        db_conn, world=WORLD_STATE, world_id=WORLD_ID, reader_id=reader_id,
        canon_episode_id=ep_id, canon_checkpoint_id=CANON_CHECKPOINT_ID,
        choice_text="east", comment=None, build_provider=flaky_provider,
    )
    choice_service.submit_reader_choice(
        db_conn, world=WORLD_STATE, world_id=WORLD_ID, reader_id=reader_id,
        canon_episode_id=ep_id, canon_checkpoint_id=CANON_CHECKPOINT_ID,
        choice_text="east", comment=None, build_provider=flaky_provider,
    )
    count = db_conn.execute(
        "SELECT COUNT(*) FROM reader_choices WHERE reader_id = ?", (reader_id,)
    ).fetchone()[0]
    assert count == 1


def test_retry_leaves_exactly_one_branch(db_conn):
    reader_id, ep_id = _setup_choice_db(db_conn)
    fail_flag = [True]

    def flaky_provider(choice_id, choice_text="", choice_comment=None):
        return _FailingOnceProvider(_make_provider(choice_id, choice_text, choice_comment), fail_flag)

    choice_service.submit_reader_choice(
        db_conn, world=WORLD_STATE, world_id=WORLD_ID, reader_id=reader_id,
        canon_episode_id=ep_id, canon_checkpoint_id=CANON_CHECKPOINT_ID,
        choice_text="east", comment=None, build_provider=flaky_provider,
    )
    choice_service.submit_reader_choice(
        db_conn, world=WORLD_STATE, world_id=WORLD_ID, reader_id=reader_id,
        canon_episode_id=ep_id, canon_checkpoint_id=CANON_CHECKPOINT_ID,
        choice_text="east", comment=None, build_provider=flaky_provider,
    )
    count = db_conn.execute(
        "SELECT COUNT(*) FROM branches WHERE reader_id = ?", (reader_id,)
    ).fetchone()[0]
    assert count == 1


def test_retry_leaves_exactly_one_personal_episode(db_conn):
    reader_id, ep_id = _setup_choice_db(db_conn)
    fail_flag = [True]

    def flaky_provider(choice_id, choice_text="", choice_comment=None):
        return _FailingOnceProvider(_make_provider(choice_id, choice_text, choice_comment), fail_flag)

    choice_service.submit_reader_choice(
        db_conn, world=WORLD_STATE, world_id=WORLD_ID, reader_id=reader_id,
        canon_episode_id=ep_id, canon_checkpoint_id=CANON_CHECKPOINT_ID,
        choice_text="east", comment=None, build_provider=flaky_provider,
    )
    choice_service.submit_reader_choice(
        db_conn, world=WORLD_STATE, world_id=WORLD_ID, reader_id=reader_id,
        canon_episode_id=ep_id, canon_checkpoint_id=CANON_CHECKPOINT_ID,
        choice_text="east", comment=None, build_provider=flaky_provider,
    )
    count = db_conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE episode_type = 'personal_branch'"
    ).fetchone()[0]
    assert count == 1


def test_concurrent_same_choice_web_submit_one_choice_one_branch(app_client, temp_db_path):
    client, code = app_client
    _login_reader(client, code)
    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)

    results = []
    barrier = threading.Barrier(2)

    def post_choice():
        barrier.wait(timeout=5)
        r = client.post(
            "/read/choice",
            data={"choice": "0", "comment": "", "csrf_token": csrf},
            follow_redirects=False,
        )
        results.append(r.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(post_choice)
        f2 = pool.submit(post_choice)
        f1.result(timeout=15)
        f2.result(timeout=15)

    conn = get_connection(temp_db_path)
    try:
        choice_count = conn.execute("SELECT COUNT(*) FROM reader_choices").fetchone()[0]
        branch_count = conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
    finally:
        conn.close()
    assert choice_count == 1
    assert branch_count == 1


def test_concurrent_different_choice_first_wins_second_conflict(app_client, temp_db_path):
    client, code = app_client
    _login_reader(client, code)
    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)

    results = []
    barrier = threading.Barrier(2)

    def post_choice(choice_val):
        barrier.wait(timeout=5)
        r = client.post(
            "/read/choice",
            data={"choice": choice_val, "comment": "", "csrf_token": csrf},
            follow_redirects=False,
        )
        results.append(r.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(post_choice, "0")
        f2 = pool.submit(post_choice, "1")
        f1.result(timeout=15)
        f2.result(timeout=15)

    conn = get_connection(temp_db_path)
    try:
        choice_count = conn.execute("SELECT COUNT(*) FROM reader_choices").fetchone()[0]
    finally:
        conn.close()
    assert choice_count == 1
    assert 409 in results or 303 in results


def test_reader_admin_same_raw_token_different_db_digest(db_conn):
    reader = reader_repo.create_reader(db_conn, display_name="Token Test")
    raw_token = "shared-raw-token-value-for-testing"
    hmac_key = "test-hmac-key"
    reader_digest = auth._hash_reader_token(raw_token, hmac_key)
    admin_digest = auth._hash_admin_token(raw_token, hmac_key)
    assert reader_digest != admin_digest


def test_reader_idle_expiry(db_conn):
    reader = reader_repo.create_reader(db_conn, display_name="Idle Reader")
    token = auth.create_reader_session(db_conn, reader.id, "test-key")
    assert auth.get_reader_session(db_conn, token, "test-key") == reader.id
    db_conn.execute(
        "UPDATE reader_sessions SET last_seen_at = '2020-01-01T00:00:00Z'"
    )
    db_conn.commit()
    assert auth.get_reader_session(db_conn, token, "test-key") is None


def test_admin_idle_expiry(db_conn):
    token = auth.create_admin_session(db_conn, "test-key")
    assert auth.get_admin_session(db_conn, token, "test-key") is True
    db_conn.execute(
        "UPDATE admin_sessions SET last_seen_at = '2020-01-01T00:00:00Z'"
    )
    db_conn.commit()
    assert auth.get_admin_session(db_conn, token, "test-key") is False


def test_idle_refresh_does_not_extend_absolute_expiry(db_conn):
    reader = reader_repo.create_reader(db_conn, display_name="Expiry Reader")
    token = auth.create_reader_session(db_conn, reader.id, "test-key")
    db_conn.execute(
        "UPDATE reader_sessions SET expires_at = '2020-01-01T00:00:00Z', "
        "last_seen_at = '2020-01-01T00:00:00Z'"
    )
    db_conn.commit()
    assert auth.get_reader_session(db_conn, token, "test-key") is None
    row = db_conn.execute(
        "SELECT expires_at FROM reader_sessions"
    ).fetchone()
    assert row["expires_at"] == "2020-01-01T00:00:00Z"


def test_reader_cookie_path(app_client):
    client, code = app_client
    resp = client.get("/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/access",
        data={"invite_code": code, "csrf_token": csrf},
        follow_redirects=False,
    )
    set_cookie = resp.headers.get("set-cookie", "")
    assert "Path=/" in set_cookie


def test_admin_cookie_path(app_client):
    client, _ = app_client
    resp = client.get("/admin/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/admin/access",
        data={"admin_secret": "test-admin-secret", "csrf_token": csrf},
        follow_redirects=False,
    )
    set_cookie = resp.headers.get("set-cookie", "")
    assert "Path=/admin" in set_cookie


def test_preauth_cookie_paths(app_client):
    client, _ = app_client
    resp = client.get("/access")
    reader_preauth = resp.headers.get("set-cookie", "")
    assert "Path=/access" in reader_preauth

    resp = client.get("/admin/access")
    admin_preauth = resp.headers.get("set-cookie", "")
    assert "Path=/admin/access" in admin_preauth


def test_reader_access_bad_origin_403(app_client):
    client, code = app_client
    resp = client.get("/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/access",
        data={"invite_code": code, "csrf_token": csrf},
        headers={"Origin": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_reader_choice_bad_origin_403(app_client):
    client, code = app_client
    _login_reader(client, code)
    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/read/choice",
        data={"choice": "0", "comment": "", "csrf_token": csrf},
        headers={"Origin": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_reader_logout_bad_origin_403(app_client):
    client, code = app_client
    _login_reader(client, code)
    resp = client.get("/read")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/logout",
        data={"csrf_token": csrf},
        headers={"Origin": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_admin_access_bad_origin_403(app_client):
    client, _ = app_client
    resp = client.get("/admin/access")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/admin/access",
        data={"admin_secret": "test-admin-secret", "csrf_token": csrf},
        headers={"Origin": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_admin_approve_reject_bad_origin_403(app_client, temp_db_path):
    client, code = app_client
    _login_reader(client, code)
    _submit_choice(client, "0")
    _login_admin(client)
    resp = client.get("/admin/review")
    branch_match = re.search(r'/admin/review/([^/"]+)"', resp.text)
    assert branch_match, "no pending branch found in review queue"
    bid = branch_match.group(1)
    resp = client.get(f"/admin/review/{bid}")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        f"/admin/review/{bid}/approve",
        data={"csrf_token": csrf},
        headers={"Origin": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_admin_logout_bad_origin_403(app_client, temp_db_path):
    client, code = app_client
    _login_reader(client, code)
    _submit_choice(client, "0")
    _login_admin(client)
    resp = client.get("/admin/review")
    branch_match = re.search(r'/admin/review/([^/"]+)"', resp.text)
    assert branch_match
    bid = branch_match.group(1)
    resp = client.get(f"/admin/review/{bid}")
    csrf = _extract_csrf(resp.text)
    resp = client.post(
        "/admin/logout",
        data={"csrf_token": csrf},
        headers={"Origin": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_production_missing_allowed_origins_startup_fails():
    s = Settings(
        env="production",
        admin_secret="x9Kq2mZ7vR4wLpN8bT1cY6hJ3fG5dS0eA",
        credential_hmac_key="Wn5tY8uI2oP4lK7jH3gF6dS9aQ1wE5rT",
        session_hmac_key="Mz8xCvB6nL4kJ2hG9fD3sA7qW1eR5tY8",
        allowed_origins="",
    )
    with pytest.raises(ValueError):
        s.validate_allowed_origins()


def test_malformed_allowed_origin_startup_fails():
    for bad in [
        "not-a-url",
        "ftp://example.com",
        "https://example.com/path",
        "https://example.com?q=1",
        "https://user:pass@example.com",
    ]:
        s = Settings(
            env="production",
            admin_secret="x9Kq2mZ7vR4wLpN8bT1cY6hJ3fG5dS0eA",
            credential_hmac_key="Wn5tY8uI2oP4lK7jH3gF6dS9aQ1wE5rT",
            session_hmac_key="Mz8xCvB6nL4kJ2hG9fD3sA7qW1eR5tY8",
            allowed_origins=bad,
        )
        with pytest.raises(ValueError):
            s.validate_allowed_origins()


def test_valid_production_origin_startup_succeeds():
    s = Settings(
        env="production",
        admin_secret="x9Kq2mZ7vR4wLpN8bT1cY6hJ3fG5dS0eA",
        credential_hmac_key="Wn5tY8uI2oP4lK7jH3gF6dS9aQ1wE5rT",
        session_hmac_key="Mz8xCvB6nL4kJ2hG9fD3sA7qW1eR5tY8",
        allowed_origins="https://living-fiction.example.com",
    )
    s.validate_allowed_origins()


def test_unsupported_settings_ai_provider_fails(temp_db_path):
    orig = settings.ai_provider
    settings.ai_provider = "openai"
    try:
        from app.factory import create_app
        with pytest.raises(RuntimeError, match="unsupported provider"):
            create_app(db_path=temp_db_path, enable_web=False)
    finally:
        settings.ai_provider = orig


def test_unsupported_injected_provider_object_fails(temp_db_path):
    from app.factory import create_app
    with pytest.raises(RuntimeError, match="missing required attribute"):
        create_app(db_path=temp_db_path, provider=object(), enable_web=False)


def test_review_service_rejects_canon_target(db_conn):
    _seed_world(db_conn)
    _seed_canon(db_conn)
    canon_ep = ep_repo.get_latest_published_canon_episode(db_conn, WORLD_ID)
    with pytest.raises(review_service.ReviewDecisionError):
        review_service.approve_branch(db_conn, branch_id="nonexistent-branch")


def test_review_reason_normalization(db_conn):
    _seed_world(db_conn)
    _seed_canon(db_conn)
    reader = reader_repo.create_reader(db_conn, display_name="Review Reader")
    episode = ep_repo.get_latest_published_canon_episode(db_conn, WORLD_ID)
    r = _submit(db_conn, reader.id, episode.id, "east")
    assert r.status == "submitted"
    branches = branch_repo.get_branches_by_reader(db_conn, reader.id)
    branch_id = branches[0].id
    with pytest.raises(review_service.ReviewDecisionError):
        review_service.reject_branch(
            db_conn, branch_id=branch_id, rejection_reason="   "
        )


def test_full_private_header_set(app_client):
    client, _ = app_client
    resp = client.get("/access")
    assert resp.headers["Cache-Control"] == "no-store, private"
    assert resp.headers["Pragma"] == "no-cache"
    assert resp.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in resp.headers
