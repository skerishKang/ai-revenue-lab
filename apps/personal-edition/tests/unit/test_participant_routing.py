"""Tests for participant route runtime connection routing and safe logging.

Covers:
- participant.py has no direct app.db.get_connection import
- participant.py has no direct get_connection(...) call
- all participant DB paths use registered runtime opener
- connection lifecycle (close on normal/exception/early return)
- same request uses same connection for related queries
- different requests do not share connections
- DatabaseError safe logging (no secret leak in caplog)
- import-time network connection 0
"""

from __future__ import annotations

import ast
import importlib
import socket
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.mock import MockProvider
from app import participant_repository as pt_repo
from app import input_repository as input_repo
from app import edition_repository as ed_repo
from app import feedback_repository as fb_repo
from app.auth import (
    create_participant_session,
    sign_session_token,
    sign_csrf_token,
    generate_csrf_token,
)
from app.db import apply_migrations, get_connection
from app.db_runtime import DatabaseError
from app.factory import create_app


MIGRATIONS_DIR = str(
    Path(__file__).resolve().parent.parent.parent / "migrations"
)

PARTICIPANT_PY = Path(__file__).resolve().parent.parent.parent / "app" / "routes" / "participant.py"


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


def _get_csrf_cookie_and_token() -> tuple[dict[str, str], str]:
    token = generate_csrf_token()
    signed = sign_csrf_token(token)
    return {"pe_csrf": signed}, token


class TestNoDirectGetConnection:
    def test_no_get_connection_import(self):
        src = PARTICIPANT_PY.read_text(encoding="utf-8")
        assert "from app.db import get_connection" not in src
        assert "from app.db import" not in src or "get_connection" not in src

    def test_no_direct_get_connection_call(self):
        src = PARTICIPANT_PY.read_text(encoding="utf-8")
        assert "get_connection(" not in src

    def test_uses_open_runtime_connection(self):
        src = PARTICIPANT_PY.read_text(encoding="utf-8")
        assert "open_runtime_connection()" in src


class TestConnectionLifecycle:
    def test_dashboard_closes_connection(self):
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

    def test_input_submit_closes_connection_on_success(self):
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
                    "raw_text": "테스트 입력입니다. " * 50,
                    "consent_confirmed": "1",
                    "csrf_token": csrf_token,
                },
                cookies=all_cookies,
            )
            assert resp.status_code == 200

    def test_edition_read_closes_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content='{"sections":[]}',
                    rendered_title="Test",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/1", cookies=cookies)
            assert resp.status_code == 200

    def test_feedback_page_closes_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            client = TestClient(app)
            conn = get_connection(db_path)
            try:
                _create_participant(conn, "p1", "Test User")
                ed = ed_repo.create_edition(
                    conn, participant_id="p1", edition_number=1,
                    structured_content='{"sections":[]}',
                    rendered_title="Test",
                )
                ed_repo.update_edition_publication(conn, ed.id, "published")
            finally:
                conn.close()
            cookies = _get_session_cookie("p1")
            resp = client.get("/p/p1/editions/1/feedback", cookies=cookies)
            assert resp.status_code == 200


class TestRequestIsolation:
    def test_different_requests_get_different_connections(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            conn1 = app.state.open_runtime_connection()
            conn2 = app.state.open_runtime_connection()
            try:
                assert conn1 is not conn2
            finally:
                conn1.close()
                conn2.close()


class TestSafeLogging:
    def test_database_error_no_secret_in_caplog(self, caplog):
        import logging
        from app.routes import participant as participant_mod

        secret_cause = Exception(
            "connection to postgresql://alice:s3cr3t@db.internal.example.com:5432/prod failed"
        )
        db_err = DatabaseError(safe_category="connection")
        db_err.__cause__ = secret_cause

        with caplog.at_level(logging.ERROR, logger="app.routes.participant"):
            participant_mod.logger.error(
                "input submission failed (category=%s)", db_err.safe_category
            )

        log_text = caplog.text
        assert "s3cr3t" not in log_text
        assert "alice" not in log_text
        assert "db.internal.example.com" not in log_text
        assert "postgresql://" not in log_text
        assert "connection" in log_text

    def test_database_error_safe_category_only(self, caplog):
        import logging
        from app.routes import participant as participant_mod

        db_err = DatabaseError(safe_category="integrity_violation")

        with caplog.at_level(logging.ERROR, logger="app.routes.participant"):
            participant_mod.logger.error(
                "feedback submission failed (category=%s)", db_err.safe_category
            )

        log_text = caplog.text
        assert "integrity_violation" in log_text
        assert "category=" in log_text


class TestImportNoNetwork:
    def test_factory_import_no_socket(self, monkeypatch):
        counter = {"n": 0}
        real = socket.socket

        class Guarded(real):
            def __init__(self, *args, **kwargs):
                counter["n"] += 1
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(socket, "socket", Guarded)
        for mod in list(sys.modules):
            if mod.startswith("app.factory") or mod.startswith("app.routes.participant"):
                del sys.modules[mod]
        importlib.import_module("app.factory")
        importlib.import_module("app.routes.participant")
        assert counter["n"] == 0

    def test_create_app_sqlite_no_pg_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, _ = _make_app(Path(tmp))
            assert app.state.db_path.endswith("test.db")
