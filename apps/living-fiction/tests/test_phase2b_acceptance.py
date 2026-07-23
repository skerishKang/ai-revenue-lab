import copy
import hashlib
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth
from app import branch_repository as branch_repo
from app import choice_repository as choice_repo
from app import choice_service
from app import episode_repository as ep_repo
from app import reader_repository as reader_repo
from app import review_decision_repository as rd_repo
from app import review_service
from app.ai.mock import MockProvider
from app.config import Settings, canonicalize_origin, settings
from app.db import apply_migrations, get_connection
from app.dev_seed import _seed_canon, _seed_invite, _seed_world
from app.preview_data import BRANCH_EPISODE_CONTENT, BRANCH_EPISODE_PLAN, WORLD_STATE
from app.utils import now_utc_iso
from app.web import _expected_origin, _verify_request_origin

WORLD_ID = WORLD_STATE.world_id
CANON_CHECKPOINT_ID = "checkpoint-canon-1"


def _strong_test_value(label: str) -> str:
    """Deterministically derive a structurally strong, distinct test secret.

    Generates a high-entropy value at runtime (instead of committing a literal
    that secret scanners flag) while keeping tests reproducible. Each label
    yields a unique >=32-char value that is not a repeating pattern or
    placeholder, so production secret-validation success tests stay meaningful.
    """
    digest = hashlib.sha256(
        f"living-fiction-test-{label}".encode("utf-8")
    ).hexdigest()
    return f"lf-test-{label}-{digest}"


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

    # Exactly one divergent submission wins (303 PRG redirect); the other is a
    # privacy-safe conflict (409). Any other combination (two 303s, a 500, etc.)
    # would mean the one-choice-per-canon contract broke under concurrency.
    assert sorted(results) == [303, 409]

    conn = get_connection(temp_db_path)
    try:
        choice_count = conn.execute("SELECT COUNT(*) FROM reader_choices").fetchone()[0]
        branch_count = conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
        personal_ep_count = conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE episode_type = 'personal_branch'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert choice_count == 1
    assert branch_count == 1
    assert personal_ep_count == 1


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
        admin_secret=_strong_test_value("admin"),
        credential_hmac_key=_strong_test_value("credential"),
        session_hmac_key=_strong_test_value("session"),
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
        # Malformed / out-of-range ports and malformed IPv6 must fail closed
        # (previously these were silently dropped by canonicalize_origin).
        "https://example.com:notaport",
        "https://example.com:99999",
        "https://[invalid",
    ]:
        s = Settings(
            env="production",
            admin_secret=_strong_test_value("admin"),
            credential_hmac_key=_strong_test_value("credential"),
            session_hmac_key=_strong_test_value("session"),
            allowed_origins=bad,
        )
        with pytest.raises(ValueError):
            s.validate_allowed_origins()


def test_mixed_valid_and_malformed_origin_fails_whole_config():
    # A single invalid entry among valid ones must reject the entire allowlist,
    # not silently drop the bad entry and keep the good ones.
    s = Settings(
        env="production",
        admin_secret=_strong_test_value("admin"),
        credential_hmac_key=_strong_test_value("credential"),
        session_hmac_key=_strong_test_value("session"),
        allowed_origins="https://good.example.com,https://example.com:99999",
    )
    with pytest.raises(ValueError):
        s.validate_allowed_origins()


def test_multiple_distinct_valid_origins_canonicalized_and_kept():
    s = Settings(
        env="production",
        admin_secret=_strong_test_value("admin"),
        credential_hmac_key=_strong_test_value("credential"),
        session_hmac_key=_strong_test_value("session"),
        allowed_origins=(
            "HTTPS://Example.com/,https://example.com:443,"
            "https://api.example.com:8443"
        ),
    )
    s.validate_allowed_origins()
    # The two example.com variants dedup to one; the distinct port stays.
    assert s.allowed_origins == "https://api.example.com:8443,https://example.com"


def test_valid_production_origin_startup_succeeds():
    s = Settings(
        env="production",
        admin_secret=_strong_test_value("admin"),
        credential_hmac_key=_strong_test_value("credential"),
        session_hmac_key=_strong_test_value("session"),
        allowed_origins="https://living-fiction.example.com",
    )
    s.validate_allowed_origins()


def _snapshot_web_settings():
    return {
        "env": settings.env,
        "admin_secret": settings.admin_secret,
        "credential_hmac_key": settings.credential_hmac_key,
        "session_hmac_key": settings.session_hmac_key,
        "allowed_origins": settings.allowed_origins,
        "database_path": settings.database_path,
        "database_backend": settings.database_backend,
        "database_url": settings.database_url,
    }


def _restore_web_settings(snapshot: dict) -> None:
    for key, value in snapshot.items():
        setattr(settings, key, value)


def test_create_app_production_malformed_origin_fails_startup(temp_db_path, monkeypatch):
    # A malformed allowlist entry must fail the real application startup with a
    # RuntimeError (the web layer wraps the config ValueError), not boot into a
    # silently-weakened allowlist.
    from app.factory import create_app

    # Production requires the postgres backend; configure a valid (unconnected)
    # postgres URL and stub the schema-current check so this test isolates the
    # origin validation without needing a live database.
    monkeypatch.setattr(
        "app.factory._verify_postgres_schema", lambda engine, migrations_dir: None
    )
    snapshot = _snapshot_web_settings()
    settings.env = "production"
    settings.admin_secret = _strong_test_value("admin")
    settings.credential_hmac_key = _strong_test_value("credential")
    settings.session_hmac_key = _strong_test_value("session")
    settings.allowed_origins = "https://example.com:99999"
    settings.database_path = temp_db_path
    settings.database_backend = "postgres"
    settings.database_url = "postgresql://user:pw@localhost:5432/db"
    try:
        with pytest.raises(RuntimeError, match="invalid origin"):
            create_app(enable_web=True)
    finally:
        _restore_web_settings(snapshot)


def test_create_app_production_valid_origin_starts_up(temp_db_path, monkeypatch):
    # Valid production settings (strong secrets + well-formed allowlist) boot the
    # full web surface successfully.
    from app.factory import create_app

    # Production requires the postgres backend; configure a valid (unconnected)
    # postgres URL and stub the schema-current check so this test isolates the
    # origin validation without needing a live database.
    monkeypatch.setattr(
        "app.factory._verify_postgres_schema", lambda engine, migrations_dir: None
    )
    snapshot = _snapshot_web_settings()
    settings.env = "production"
    settings.admin_secret = _strong_test_value("admin")
    settings.credential_hmac_key = _strong_test_value("credential")
    settings.session_hmac_key = _strong_test_value("session")
    settings.allowed_origins = "https://living-fiction.example.com"
    settings.database_path = temp_db_path
    settings.database_backend = "postgres"
    settings.database_url = "postgresql://user:pw@localhost:5432/db"
    try:
        app = create_app(enable_web=True)
        assert app is not None
    finally:
        _restore_web_settings(snapshot)


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


def _insert_canon_pointing_branch(db_conn, reader_id, canon_episode_id, choice_id):
    """Insert an abnormal branch whose ``branch_episode_id`` targets canon.

    This builds a real DB row (not a nonexistent id) that simulates a corrupted
    or mis-targeted branch, so the review service's canon-protection guard can
    be exercised against an actual branch record pointing at a canon episode.
    """
    branch_id = f"branch-canon-target-{choice_id}"
    db_conn.execute(
        "INSERT INTO branches (id, reader_id, canon_checkpoint_id, "
        "prior_episode_id, branch_episode_id, reader_choice_id, status, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
        (branch_id, reader_id, CANON_CHECKPOINT_ID, canon_episode_id,
         canon_episode_id, choice_id, now_utc_iso()),
    )
    db_conn.commit()
    return branch_id


def test_review_service_rejects_canon_target(db_conn):
    _seed_world(db_conn)
    _seed_canon(db_conn)
    canon_ep = ep_repo.get_latest_published_canon_episode(db_conn, WORLD_ID)
    canon_state_before = canon_ep.review_state
    reader = reader_repo.create_reader(db_conn, display_name="Canon Target")
    choice = choice_repo.create_reader_choice(
        db_conn, choice_id="choice-canon-target", reader_id=reader.id,
        canon_episode_id=canon_ep.id, choice_text="east",
    )
    branch_id = _insert_canon_pointing_branch(
        db_conn, reader.id, canon_ep.id, choice.id
    )

    # Both decisions must refuse to touch a branch that targets a canon episode.
    with pytest.raises(review_service.ReviewDecisionError):
        review_service.approve_branch(db_conn, branch_id=branch_id)
    with pytest.raises(review_service.ReviewDecisionError):
        review_service.reject_branch(
            db_conn, branch_id=branch_id, rejection_reason="not allowed"
        )

    # Canon review_state is immutable and no audit rows were written.
    canon_after = ep_repo.get_episode_by_id(db_conn, canon_ep.id)
    assert canon_after.review_state == canon_state_before
    assert rd_repo.get_decisions_for_branch(db_conn, branch_id) == []
    assert rd_repo.get_decisions_for_episode(db_conn, canon_ep.id) == []


def test_review_reason_normalization(db_conn):
    _seed_world(db_conn)
    _seed_canon(db_conn)
    reader = reader_repo.create_reader(db_conn, display_name="Review Reader")
    episode = ep_repo.get_latest_published_canon_episode(db_conn, WORLD_ID)
    r = _submit(db_conn, reader.id, episode.id, "east")
    assert r.status == "submitted"
    branch = branch_repo.get_branches_by_reader(db_conn, reader.id)[0]
    owner_before = branch.reader_id
    prior_before = branch.prior_episode_id
    checkpoint_before = branch.canon_checkpoint_id

    review_service.reject_branch(
        db_conn, branch_id=branch.id, rejection_reason="  품질   부족  "
    )

    # Episode is rejected and the audit row stores the normalized reason.
    ep_after = ep_repo.get_episode_by_id(db_conn, branch.branch_episode_id)
    assert ep_after.review_state == "rejected"
    decisions = rd_repo.get_decisions_for_branch(db_conn, branch.id)
    assert len(decisions) == 1
    assert decisions[0].decision == "rejected"
    assert decisions[0].rejection_reason == "품질 부족"

    # Branch owner and canon binding are unchanged by the rejection.
    branch_after = branch_repo.get_branch(db_conn, branch.id)
    assert branch_after.reader_id == owner_before
    assert branch_after.prior_episode_id == prior_before
    assert branch_after.canon_checkpoint_id == checkpoint_before


def test_review_reject_empty_reason_rejected(db_conn):
    _seed_world(db_conn)
    _seed_canon(db_conn)
    reader = reader_repo.create_reader(db_conn, display_name="Empty Reason")
    episode = ep_repo.get_latest_published_canon_episode(db_conn, WORLD_ID)
    r = _submit(db_conn, reader.id, episode.id, "east")
    assert r.status == "submitted"
    branch_id = branch_repo.get_branches_by_reader(db_conn, reader.id)[0].id
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


# ── §3 Provider protocol validation ───────────────────────────────────────


class _AttrsOnlyProvider:
    """Has the identity attributes but no generate_structured method."""

    provider_name = "attrs-only"
    model = "attrs-only-v1"
    cost_class = "free"


class _NonCallableGenerateProvider:
    """generate_structured exists but is not callable."""

    provider_name = "noncallable"
    model = "noncallable-v1"
    cost_class = "free"
    generate_structured = "not-a-method"


def test_injected_provider_missing_generate_structured_fails(temp_db_path):
    from app.factory import create_app

    with pytest.raises(RuntimeError, match="generate_structured"):
        create_app(
            db_path=temp_db_path, provider=_AttrsOnlyProvider(), enable_web=False
        )


def test_injected_provider_noncallable_generate_structured_fails(temp_db_path):
    from app.factory import create_app

    with pytest.raises(RuntimeError, match="generate_structured"):
        create_app(
            db_path=temp_db_path,
            provider=_NonCallableGenerateProvider(),
            enable_web=False,
        )


def test_injected_provider_satisfying_protocol_accepted(temp_db_path):
    from app.factory import create_app

    app = create_app(
        db_path=temp_db_path, provider=MockProvider(), enable_web=False
    )
    assert app.state.provider.provider_name == "mock"


# ── §4 allowed-origin canonicalization ────────────────────────────────────


def test_canonicalize_origin_normalizes_variants():
    assert canonicalize_origin("https://example.com") == "https://example.com"
    # Case + trailing slash collapse to the same canonical origin.
    assert canonicalize_origin("HTTPS://Example.com/") == "https://example.com"
    # Explicit default port is dropped.
    assert canonicalize_origin("https://example.com:443") == "https://example.com"
    assert canonicalize_origin("http://example.com:80") == "http://example.com"
    # Non-default port is preserved.
    assert (
        canonicalize_origin("https://example.com:8443")
        == "https://example.com:8443"
    )


def test_canonicalize_origin_supports_ipv6_with_brackets():
    # IPv6 hosts keep their brackets so the canonical origin stays a valid URL.
    assert canonicalize_origin("http://[::1]:8000") == "http://[::1]:8000"
    assert (
        canonicalize_origin("https://[2001:db8::1]")
        == "https://[2001:db8::1]"
    )


def test_canonicalize_origin_rejects_malformed():
    for bad in [
        "not-a-url",
        "ftp://example.com",
        "https://example.com/path",
        "https://example.com?q=1",
        "https://example.com#frag",
        "https://user:pass@example.com",
        "https://",
        "",
        # Malformed / out-of-range ports and malformed IPv6 must not raise —
        # they canonicalize to None so callers can return a generic 403.
        "https://example.com:notaport",
        "https://example.com:99999",
        "https://[invalid",
    ]:
        assert canonicalize_origin(bad) is None


def test_production_allowed_origins_canonicalized_and_deduped():
    s = Settings(
        env="production",
        admin_secret=_strong_test_value("admin"),
        credential_hmac_key=_strong_test_value("credential"),
        session_hmac_key=_strong_test_value("session"),
        allowed_origins="HTTPS://Example.com/,https://example.com:443,https://example.com",
    )
    s.validate_allowed_origins()
    # All three superficial variants collapse to one canonical origin.
    assert s.allowed_origins == "https://example.com"


def test_configured_origin_canonicalization_accepts_match(app_client):
    client, code = app_client
    orig = settings.allowed_origins
    # Configure a non-canonical origin; the request sends the canonical form.
    settings.allowed_origins = "HTTP://TestServer/"
    try:
        resp = client.get("/access")
        csrf = _extract_csrf(resp.text)
        resp = client.post(
            "/access",
            data={"invite_code": code, "csrf_token": csrf},
            headers={"Origin": "http://testserver"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
    finally:
        settings.allowed_origins = orig


def test_configured_origin_canonicalization_rejects_mismatch(app_client):
    client, code = app_client
    orig = settings.allowed_origins
    settings.allowed_origins = "https://living-fiction.example.com"
    try:
        resp = client.get("/access")
        csrf = _extract_csrf(resp.text)
        resp = client.post(
            "/access",
            data={"invite_code": code, "csrf_token": csrf},
            headers={"Origin": "http://testserver"},
            follow_redirects=False,
        )
        assert resp.status_code == 403
    finally:
        settings.allowed_origins = orig


# ── §3 request-origin verification contract (Origin + Host fallback) ──────


class _FakeRequestURL:
    def __init__(self, scheme: str):
        self.scheme = scheme


class _FakeRequest:
    """Minimal stand-in exposing only what ``_verify_request_origin`` reads."""

    def __init__(self, scheme: str = "https", headers: dict | None = None):
        self.url = _FakeRequestURL(scheme)
        self.headers = headers or {}


def _assert_origin_rejected(request) -> None:
    with pytest.raises(HTTPException) as exc:
        _verify_request_origin(request)
    assert exc.value.status_code == 403


def test_verify_origin_malformed_port_is_403_not_500():
    orig = settings.allowed_origins
    settings.allowed_origins = "https://example.com"
    try:
        # A malformed port must canonicalize to None -> generic 403, never a
        # ValueError bubbling up as HTTP 500.
        _assert_origin_rejected(
            _FakeRequest(headers={"origin": "https://example.com:notaport"})
        )
    finally:
        settings.allowed_origins = orig


def test_verify_origin_out_of_range_port_is_403():
    orig = settings.allowed_origins
    settings.allowed_origins = "https://example.com"
    try:
        _assert_origin_rejected(
            _FakeRequest(headers={"origin": "https://example.com:99999"})
        )
    finally:
        settings.allowed_origins = orig


def test_verify_origin_malformed_ipv6_is_403():
    orig = settings.allowed_origins
    settings.allowed_origins = "https://example.com"
    try:
        _assert_origin_rejected(
            _FakeRequest(headers={"origin": "https://[invalid"})
        )
    finally:
        settings.allowed_origins = orig


def test_verify_origin_configured_mismatch_is_403():
    orig = settings.allowed_origins
    settings.allowed_origins = "https://example.com"
    try:
        _assert_origin_rejected(
            _FakeRequest(headers={"origin": "https://other.example.com"})
        )
    finally:
        settings.allowed_origins = orig


def test_verify_origin_canonical_match_succeeds():
    orig = settings.allowed_origins
    settings.allowed_origins = "https://example.com"
    try:
        # Superficial variant (case + trailing slash) canonicalizes to the
        # configured origin and is accepted.
        _verify_request_origin(
            _FakeRequest(headers={"origin": "HTTPS://Example.com/"})
        )
    finally:
        settings.allowed_origins = orig


def test_verify_origin_host_fallback_malformed_host_is_403():
    orig = settings.allowed_origins
    settings.allowed_origins = "https://example.com"
    try:
        # No Origin header; a malformed Host must not crash -> generic 403.
        _assert_origin_rejected(
            _FakeRequest(scheme="https", headers={"host": "[invalid"})
        )
    finally:
        settings.allowed_origins = orig


def test_verify_origin_host_fallback_scheme_mismatch_is_403():
    orig = settings.allowed_origins
    settings.allowed_origins = "https://example.com"
    try:
        # http request cannot satisfy an https allowlist entry (full-origin,
        # not host-only, comparison).
        _assert_origin_rejected(
            _FakeRequest(scheme="http", headers={"host": "example.com"})
        )
    finally:
        settings.allowed_origins = orig


def test_verify_origin_host_fallback_default_port_succeeds():
    orig = settings.allowed_origins
    settings.allowed_origins = "https://example.com"
    try:
        # HTTPS request with an explicit default port canonicalizes to the
        # configured origin and is accepted via the Host fallback.
        _verify_request_origin(
            _FakeRequest(scheme="https", headers={"host": "example.com:443"})
        )
    finally:
        settings.allowed_origins = orig


def test_expected_origin_uses_scheme_and_host():
    req = _FakeRequest(scheme="https", headers={"host": "example.com:443"})
    assert _expected_origin(req) == "https://example.com:443"


# ── §5 pre-auth CSRF TTL ──────────────────────────────────────────────────


def test_preauth_csrf_token_carries_timestamp():
    token = auth.issue_preauth_csrf("k", auth.CSRF_READER_PREAUTH)
    parts = token.split(".")
    assert len(parts) == 3
    int(parts[1])  # embedded issued_at is an integer


def test_preauth_csrf_fresh_token_accepted():
    key = "test-key"
    token = auth.issue_preauth_csrf(key, auth.CSRF_READER_PREAUTH)
    assert auth.verify_preauth_csrf(key, auth.CSRF_READER_PREAUTH, token, token)


def test_preauth_csrf_expired_token_rejected():
    key = "test-key"
    token = auth.issue_preauth_csrf(key, auth.CSRF_READER_PREAUTH)
    future = datetime.now(timezone.utc) + timedelta(
        seconds=auth.PREAUTH_CSRF_TTL_SECONDS + 5
    )
    assert not auth.verify_preauth_csrf(
        key, auth.CSRF_READER_PREAUTH, token, token, now=future
    )


def test_preauth_csrf_future_dated_token_rejected():
    key = "test-key"
    token = auth.issue_preauth_csrf(key, auth.CSRF_READER_PREAUTH)
    # Verifying as if "now" is far in the past makes the token look future-dated
    # beyond the tolerated clock skew, so it must be rejected.
    past = datetime.now(timezone.utc) - timedelta(seconds=3600)
    assert not auth.verify_preauth_csrf(
        key, auth.CSRF_READER_PREAUTH, token, token, now=past
    )


def test_preauth_csrf_ttl_boundary_accepted_within_window():
    key = "test-key"
    token = auth.issue_preauth_csrf(key, auth.CSRF_READER_PREAUTH)
    # Just inside the TTL window the token is still valid.
    edge = datetime.now(timezone.utc) + timedelta(
        seconds=auth.PREAUTH_CSRF_TTL_SECONDS - 5
    )
    assert auth.verify_preauth_csrf(
        key, auth.CSRF_READER_PREAUTH, token, token, now=edge
    )


def test_preauth_csrf_tampered_timestamp_rejected():
    key = "test-key"
    token = auth.issue_preauth_csrf(key, auth.CSRF_READER_PREAUTH)
    nonce, issued_at, sig = token.split(".")
    # Rewriting the timestamp without re-signing breaks the MAC.
    forged = f"{nonce}.{int(issued_at) - 100000}.{sig}"
    assert not auth.verify_preauth_csrf(
        key, auth.CSRF_READER_PREAUTH, forged, forged
    )
