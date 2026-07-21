"""Shared test conftest for Living Fiction tests."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def temp_db_path():
    """Provide a temporary file-backed SQLite database path."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="lf_test_")
    os.close(fd)
    os.unlink(path)  # remove so SQLite creates fresh
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def db_conn(temp_db_path):
    """Provide a migrated SQLite connection."""
    from app.db import apply_migrations, get_connection
    conn = get_connection(temp_db_path)
    migrations_dir = str(
        Path(__file__).resolve().parent.parent / "migrations"
    )
    apply_migrations(conn, migrations_dir)
    yield conn
    conn.close()
