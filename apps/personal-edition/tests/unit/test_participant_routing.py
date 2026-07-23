"""Tests for participant route runtime connection routing and safe logging.

Covers:
- participant.py has no direct app.db.get_connection import or call
- all participant DB paths use registered runtime opener
- RecordingRuntimeConnection observes close on normal/exception/early return
- real HTTP route safe logging (monkeypatched DatabaseError with secret cause)
- request isolation (no shared connection objects)
- static contract (AST)
- import-time network connection 0
"""

from __future__ import annotations

import ast
import importlib
import json
import logging
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

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
from app.db_runtime import DatabaseError, SqliteRuntimeConnection
from app.factory import create_app


MIGRATIONS_DIR = str(
    Path(__file__).resolve().parent.parent.parent / "migrations"
)

PARTICIPANT_PY = (
    Path(__file__).resolve().parent.parent.parent / "app" / "routes" / "participant.py"
)


# ---------------------------------------------------------------------------
# Recording connection wrapper
# ---------------------------------------------------------------------------


class RecordingRuntimeConnection:
    """Wraps a real SqliteRuntimeConnection and records lifecycle events."""

    _counter = 0

    def __init__(self, inner: SqliteRuntimeConnection):
        RecordingRuntimeConnection._counter += 1
        self.identity = RecordingRuntimeConnection._counter
        self._inner = inner
        self.execute_count = 0
        self.close_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    @property
    def closed(self) -> bool:
        return self.close_count > 0

    @property
    def in_transaction(self) -> bool:
        return self._inner.in_transaction

    def execute(self, sql: str, params: Any = ()) -> Any:
        self.execute_count += 1
        return self._inner.execute(sql, params)

    def begin_write(self) -> None:
        self._inner.begin_write()

    def commit(self) -> None:
        self.commit_count += 1
        self._inner.commit()

    def rollback(self) -> None:
        self.rollback_count += 1
        self._inner.rollback()

    def close(self) -> None:
        self.close_count += 1
        self._inner.close()


class ConnectionRecorder:
    """Installs a recording opener on app.state and tracks all connections."""

    def __init__(self, app):
        self.connections: list[RecordingRuntimeConnection] = []
        self._original = app.state.open_runtime_connection
        app.state.open_runtime_connection = self._open

    def _open(self) -> RecordingRuntimeConnection:
        inner = self._original()
        rec = RecordingRuntimeConnection(inner)
        self.connections.append(rec)
        return rec

    def assert_all_closed(self):
        for conn in self.connections:
            assert conn.close_count == 1, (
                f"connection #{conn.identity} close_count={conn.close_count}"
            )

    def assert_no_shared_objects(self):
        identities = [id(c) for c in self.connections]
        assert len(identities) == len(set(identities))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        SqliteRuntimeConnection(conn), participant_id=pid, display_name=name, preferred_language=lang
    )


def _get_session_cookie(participant_id: str) -> dict[str, str]:
    session_data = create_participant_session(participant_id)
    signed = sign_session_token(session_data)
    return {"pe_session": signed}


def _get_csrf_cookie_and_token() -> tuple[dict[str, str], str]:
    token = generate_csrf_token()
    signed = sign_csrf_token(token)
    return {"pe_csrf": signed}, token


def _setup_participant(tmp_path: Path):
    app, db_path = _make_app(tmp_path)
    conn = get_connection(db_path)
    try:
        prov = _create_participant(conn, "p1", "Test User")
    finally:
        conn.close()
    recorder = ConnectionRecorder(app)
    client = TestClient(app)
    cookies = _get_session_cookie("p1")
    return app, db_path, client, cookies, recorder, prov


def _setup_published_edition(tmp_path: Path):
    app, db_path = _make_app(tmp_path)
    conn = get_connection(db_path)
    try:
        _create_participant(conn, "p1", "Test User")
        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1,
            structured_content=json.dumps({"sections": [{"section_id": "s001"}]}),
            rendered_title="Test Edition",
        )
        ed_repo.update_edition_publication(conn, ed.id, "published")
    finally:
        conn.close()
    recorder = ConnectionRecorder(app)
    client = TestClient(app)
    cookies = _get_session_cookie("p1")
    return app, db_path, client, cookies, recorder


SECRET_URL = "postgresql://alice:s3cr3t@db.internal.example.com:5432/prod"
SECRET_CAUSE_MSG = (
    f"connection to {SECRET_URL} failed: "
    "SELECT * FROM participants WHERE id = 'x' params=('secret_param',) "
    "server closed the connection unexpectedly"
)


def _make_secret_database_error() -> DatabaseError:
    cause = Exception(SECRET_CAUSE_MSG)
    err = DatabaseError(safe_category="connection")
    err.__cause__ = cause
    return err


# ---------------------------------------------------------------------------
# Static contract (AST / source)
# ---------------------------------------------------------------------------


class TestStaticContract:
    def test_no_get_connection_import(self):
        src = PARTICIPANT_PY.read_text(encoding="utf-8")
        assert "from app.db import get_connection" not in src
        assert "from app.db import" not in src

    def test_no_direct_get_connection_call(self):
        src = PARTICIPANT_PY.read_text(encoding="utf-8")
        assert "get_connection(" not in src

    def test_uses_open_runtime_connection(self):
        src = PARTICIPANT_PY.read_text(encoding="utf-8")
        assert "open_runtime_connection()" in src

    def test_eight_runtime_opener_calls(self):
        src = PARTICIPANT_PY.read_text(encoding="utf-8")
        assert src.count("open_runtime_connection()") == 8

    def test_database_error_catch_before_generic(self):
        src = PARTICIPANT_PY.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                handler_types = []
                for h in node.handlers:
                    if h.type is not None:
                        if isinstance(h.type, ast.Name):
                            handler_types.append(h.type.id)
                        elif isinstance(h.type, ast.Attribute):
                            handler_types.append(h.type.attr)
                if "DatabaseError" in handler_types and "Exception" in handler_types:
                    db_idx = handler_types.index("DatabaseError")
                    exc_idx = handler_types.index("Exception")
                    assert db_idx < exc_idx

    def test_no_logger_exception_in_database_error_handler(self):
        src = PARTICIPANT_PY.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for h in node.handlers:
                    if h.type is not None and isinstance(h.type, ast.Name):
                        if h.type.id == "DatabaseError":
                            handler_src = ast.get_source_segment(src, h)
                            assert "logger.exception" not in (handler_src or "")

    def test_no_cause_logging_in_database_error_handler(self):
        src = PARTICIPANT_PY.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for h in node.handlers:
                    if h.type is not None and isinstance(h.type, ast.Name):
                        if h.type.id == "DatabaseError":
                            handler_src = ast.get_source_segment(src, h) or ""
                            assert "__cause__" not in handler_src


# ---------------------------------------------------------------------------
# Connection close verification (recording)
# ---------------------------------------------------------------------------


class TestConnectionClose:
    def test_token_access_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, _, recorder, prov = _setup_participant(Path(tmp))
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/access",
                data={"token": prov.one_time_token, "csrf_token": csrf_token},
                cookies=csrf_cookie,
                follow_redirects=False,
            )
            assert resp.status_code == 303
            recorder.assert_all_closed()

    def test_token_access_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, _, recorder, _ = _setup_participant(Path(tmp))
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/access",
                data={"token": "wrong-token", "csrf_token": csrf_token},
                cookies=csrf_cookie,
            )
            assert resp.status_code == 200
            recorder.assert_all_closed()

    def test_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder, _ = _setup_participant(Path(tmp))
            resp = client.get("/p/p1", cookies=cookies)
            assert resp.status_code == 200
            recorder.assert_all_closed()

    def test_input_submission_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder, _ = _setup_participant(Path(tmp))
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/p1/input",
                data={
                    "raw_text": "test input " * 50,
                    "consent_confirmed": "1",
                    "csrf_token": csrf_token,
                },
                cookies={**cookies, **csrf_cookie},
            )
            assert resp.status_code == 200
            recorder.assert_all_closed()

    def test_input_validation_early_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder, _ = _setup_participant(Path(tmp))
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/p1/input",
                data={"raw_text": "", "consent_confirmed": "1", "csrf_token": csrf_token},
                cookies={**cookies, **csrf_cookie},
            )
            assert resp.status_code == 200
            recorder.assert_all_closed()

    def test_input_repository_exception(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder, _ = _setup_participant(Path(tmp))

            def boom(*a, **kw):
                raise RuntimeError("simulated failure")

            monkeypatch.setattr(input_repo, "create_input", boom)
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/p1/input",
                data={
                    "raw_text": "test input " * 50,
                    "consent_confirmed": "1",
                    "csrf_token": csrf_token,
                },
                cookies={**cookies, **csrf_cookie},
            )
            assert resp.status_code == 200
            recorder.assert_all_closed()

    def test_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder, _ = _setup_participant(Path(tmp))
            resp = client.get("/p/p1/history", cookies=cookies)
            assert resp.status_code == 200
            recorder.assert_all_closed()

    def test_edition_read_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder = _setup_published_edition(Path(tmp))
            resp = client.get("/p/p1/editions/1", cookies=cookies)
            assert resp.status_code == 200
            recorder.assert_all_closed()

    def test_edition_not_found_early_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder = _setup_published_edition(Path(tmp))
            resp = client.get("/p/p1/editions/99", cookies=cookies)
            assert resp.status_code == 200
            recorder.assert_all_closed()

    def test_feedback_page_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder = _setup_published_edition(Path(tmp))
            resp = client.get("/p/p1/editions/1/feedback", cookies=cookies)
            assert resp.status_code == 200
            recorder.assert_all_closed()

    def test_feedback_target_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder = _setup_published_edition(Path(tmp))
            resp = client.get("/p/p1/editions/99/feedback", cookies=cookies)
            assert resp.status_code == 200
            recorder.assert_all_closed()

    def test_feedback_submission_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder = _setup_published_edition(Path(tmp))
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/p1/editions/1/feedback",
                data={
                    "direction_choices": "continue_direction",
                    "csrf_token": csrf_token,
                },
                cookies={**cookies, **csrf_cookie},
            )
            assert resp.status_code == 200
            recorder.assert_all_closed()

    def test_feedback_repository_exception(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder = _setup_published_edition(Path(tmp))

            def boom(*a, **kw):
                raise RuntimeError("simulated failure")

            monkeypatch.setattr(fb_repo, "create_feedback", boom)
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()
            resp = client.post(
                "/p/p1/editions/1/feedback",
                data={
                    "direction_choices": "continue_direction",
                    "csrf_token": csrf_token,
                },
                cookies={**cookies, **csrf_cookie},
            )
            assert resp.status_code == 200
            recorder.assert_all_closed()


# ---------------------------------------------------------------------------
# Request isolation
# ---------------------------------------------------------------------------


class TestRequestIsolation:
    def test_no_shared_connection_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder, _ = _setup_participant(Path(tmp))
            client.get("/p/p1", cookies=cookies)
            client.get("/p/p1/history", cookies=cookies)
            recorder.assert_no_shared_objects()
            recorder.assert_all_closed()

    def test_opener_returns_distinct_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path = _make_app(Path(tmp))
            c1 = app.state.open_runtime_connection()
            c2 = app.state.open_runtime_connection()
            try:
                assert c1 is not c2
            finally:
                c1.close()
                c2.close()


# ---------------------------------------------------------------------------
# Real route safe logging (input)
# ---------------------------------------------------------------------------


class TestInputSafeLogging:
    def test_database_error_route_no_secret_leak(self, monkeypatch, caplog):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder, _ = _setup_participant(Path(tmp))

            def raise_db_error(*a, **kw):
                raise _make_secret_database_error()

            monkeypatch.setattr(input_repo, "create_input", raise_db_error)
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()

            with caplog.at_level(logging.ERROR, logger="app.routes.participant"):
                resp = client.post(
                    "/p/p1/input",
                    data={
                        "raw_text": "test input " * 50,
                        "consent_confirmed": "1",
                        "csrf_token": csrf_token,
                    },
                    cookies={**cookies, **csrf_cookie},
                )

            assert resp.status_code == 200
            assert "error" in resp.text.lower() or "try again" in resp.text.lower()
            log_text = caplog.text
            assert "s3cr3t" not in log_text
            assert "alice" not in log_text
            assert "db.internal.example.com" not in log_text
            assert "postgresql://" not in log_text
            assert "secret_param" not in log_text
            assert "SELECT * FROM" not in log_text
            assert "server closed the connection" not in log_text
            assert "Traceback" not in log_text
            assert "category=connection" in log_text
            recorder.assert_all_closed()

    def test_generic_exception_still_works(self, monkeypatch, caplog):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder, _ = _setup_participant(Path(tmp))

            def raise_generic(*a, **kw):
                raise ValueError("something went wrong")

            monkeypatch.setattr(input_repo, "create_input", raise_generic)
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()

            with caplog.at_level(logging.ERROR, logger="app.routes.participant"):
                resp = client.post(
                    "/p/p1/input",
                    data={
                        "raw_text": "test input " * 50,
                        "consent_confirmed": "1",
                        "csrf_token": csrf_token,
                    },
                    cookies={**cookies, **csrf_cookie},
                )

            assert resp.status_code == 200
            assert "try again" in resp.text.lower() or "error" in resp.text.lower()
            recorder.assert_all_closed()


# ---------------------------------------------------------------------------
# Real route safe logging (feedback)
# ---------------------------------------------------------------------------


class TestFeedbackSafeLogging:
    def test_database_error_route_no_secret_leak(self, monkeypatch, caplog):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder = _setup_published_edition(Path(tmp))

            def raise_db_error(*a, **kw):
                raise _make_secret_database_error()

            monkeypatch.setattr(fb_repo, "create_feedback", raise_db_error)
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()

            with caplog.at_level(logging.ERROR, logger="app.routes.participant"):
                resp = client.post(
                    "/p/p1/editions/1/feedback",
                    data={
                        "direction_choices": "continue_direction",
                        "csrf_token": csrf_token,
                    },
                    cookies={**cookies, **csrf_cookie},
                )

            assert resp.status_code == 200
            assert "failed" in resp.text.lower() or "try again" in resp.text.lower()
            log_text = caplog.text
            assert "s3cr3t" not in log_text
            assert "alice" not in log_text
            assert "db.internal.example.com" not in log_text
            assert "postgresql://" not in log_text
            assert "secret_param" not in log_text
            assert "SELECT * FROM" not in log_text
            assert "server closed the connection" not in log_text
            assert "Traceback" not in log_text
            assert "category=connection" in log_text
            recorder.assert_all_closed()

    def test_generic_exception_still_works(self, monkeypatch, caplog):
        with tempfile.TemporaryDirectory() as tmp:
            app, db_path, client, cookies, recorder = _setup_published_edition(Path(tmp))

            def raise_generic(*a, **kw):
                raise ValueError("something went wrong")

            monkeypatch.setattr(fb_repo, "create_feedback", raise_generic)
            csrf_cookie, csrf_token = _get_csrf_cookie_and_token()

            with caplog.at_level(logging.ERROR, logger="app.routes.participant"):
                resp = client.post(
                    "/p/p1/editions/1/feedback",
                    data={
                        "direction_choices": "continue_direction",
                        "csrf_token": csrf_token,
                    },
                    cookies={**cookies, **csrf_cookie},
                )

            assert resp.status_code == 200
            assert "failed" in resp.text.lower() or "try again" in resp.text.lower()
            recorder.assert_all_closed()


# ---------------------------------------------------------------------------
# Import / network
# ---------------------------------------------------------------------------


class TestImportNoNetwork:
    def test_factory_and_participant_import_no_socket(self, monkeypatch):
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
