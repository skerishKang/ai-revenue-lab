"""Shared test fixtures for Living Travel."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Generator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("LT_DATABASE_URL", ":memory:")
os.environ.setdefault("LT_OPERATOR_SECRET", "test-secret-12345")
os.environ.setdefault("LT_ENVIRONMENT", "testing")

from app.config import get_settings, reset_settings
from app.db import apply_migrations, get_connection
from app.factory import create_app
from app.security import reset_login_rate_limiter


@pytest.fixture(autouse=True)
def _ensure_operator_secret():
    """Ensure LT_OPERATOR_SECRET is always present for unit tests.

    The ``app`` fixture pops it on teardown; this autouse fixture restores
    it before every test so that Settings validation does not fail on the
    operator-secret check when running the full suite.
    """
    os.environ.setdefault("LT_OPERATOR_SECRET", "test-secret-12345")
    yield
    os.environ.setdefault("LT_OPERATOR_SECRET", "test-secret-12345")


@pytest.fixture()
def temp_db(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    apply_migrations(db_path)
    yield conn
    conn.close()


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
    os.environ.pop("LT_DATABASE_URL", None)
    os.environ.pop("LT_OPERATOR_SECRET", None)


@pytest.fixture()
def client(app):
    from starlette.testclient import TestClient
    return TestClient(app)


@pytest.fixture()
def sync_client(app):
    from starlette.testclient import TestClient
    return TestClient(app)


@pytest.fixture()
def seeded_db(temp_db: sqlite3.Connection) -> sqlite3.Connection:
    temp_db.execute(
        "INSERT INTO travelers (id, display_name, destination, trip_duration_nights, status, created_at, updated_at) "         "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("travel_test_001", "Alice", "Seoul", 3, "active", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    )
    temp_db.commit()
    return temp_db
