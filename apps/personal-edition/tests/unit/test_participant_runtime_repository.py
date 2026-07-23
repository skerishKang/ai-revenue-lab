"""Unit tests for participant_repository backend-neutral RuntimeConnection contract.

Covers:
- Race-safe SQL contract (begin_write, ON CONFLICT DO NOTHING, no pre-SELECT)
- Duplicate ID simulation via fake
- Token collision simulation via fake
- Retry exhaustion
- Unexpected DB error (no secret leak)
- Row compatibility (sqlite3.Row and dict)
- Static contract (no sqlite3 types, no BEGIN IMMEDIATE, no network at import)
- SQLite regression via real SqliteRuntimeConnection
"""

from __future__ import annotations

import ast
import importlib
import socket
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

import pytest

from app import participant_repository as repo
from app import security
from app.db import apply_migrations, get_connection
from app.db_runtime import DatabaseError, SqliteRuntimeConnection


REPO_PY = (
    Path(__file__).resolve().parent.parent.parent
    / "app"
    / "participant_repository.py"
)

MIGRATIONS_DIR = str(
    Path(__file__).resolve().parent.parent.parent / "migrations"
)


# ---------------------------------------------------------------------------
# Fake RuntimeConnection for controlled sequences
# ---------------------------------------------------------------------------


class FakeCursor:
    def __init__(self, rowcount: int = 0, rows: list[Any] | None = None):
        self._rowcount = rowcount
        self._rows = rows or []
        self._idx = 0

    @property
    def rowcount(self) -> int:
        return self._rowcount

    def fetchone(self) -> Any:
        if self._idx < len(self._rows):
            row = self._rows[self._idx]
            self._idx += 1
            return row
        return None

    def fetchall(self) -> list[Any]:
        return self._rows


class FakeRuntimeConnection:
    """Programmable fake that records calls and returns scripted results."""

    def __init__(self):
        self.in_transaction = False
        self.begin_write_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.execute_log: list[tuple[str, tuple]] = []
        self._script: list[FakeCursor] = []
        self._script_idx = 0

    def script_next(self, cursor: FakeCursor):
        self._script.append(cursor)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> FakeCursor:
        self.execute_log.append((sql, tuple(params)))
        if self._script_idx < len(self._script):
            cur = self._script[self._script_idx]
            self._script_idx += 1
            return cur
        return FakeCursor(rowcount=0)

    def begin_write(self) -> None:
        self.begin_write_count += 1
        self.in_transaction = True

    def commit(self) -> None:
        self.commit_count += 1
        self.in_transaction = False

    def rollback(self) -> None:
        self.rollback_count += 1
        self.in_transaction = False

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sqlite_runtime():
    conn = get_connection(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return SqliteRuntimeConnection(conn), conn


# ---------------------------------------------------------------------------
# Static contract
# ---------------------------------------------------------------------------


class TestStaticContract:
    def test_no_sqlite3_connection_annotation(self):
        src = REPO_PY.read_text(encoding="utf-8")
        assert "sqlite3.Connection" not in src

    def test_no_sqlite3_row_annotation(self):
        src = REPO_PY.read_text(encoding="utf-8")
        assert "sqlite3.Row" not in src

    def test_no_begin_immediate(self):
        src = REPO_PY.read_text(encoding="utf-8")
        assert "BEGIN IMMEDIATE" not in src

    def test_uses_begin_write(self):
        src = REPO_PY.read_text(encoding="utf-8")
        assert "conn.begin_write()" in src

    def test_no_sqlite3_import(self):
        src = REPO_PY.read_text(encoding="utf-8")
        assert "import sqlite3" not in src

    def test_import_no_network(self, monkeypatch):
        counter = {"n": 0}
        real = socket.socket

        class Guarded(real):
            def __init__(self, *args, **kwargs):
                counter["n"] += 1
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(socket, "socket", Guarded)
        for mod in list(sys.modules):
            if "participant_repository" in mod:
                del sys.modules[mod]
        importlib.import_module("app.participant_repository")
        assert counter["n"] == 0


# ---------------------------------------------------------------------------
# Race-safe SQL contract (fake)
# ---------------------------------------------------------------------------


class TestRaceSafeSQLContract:
    def test_create_calls_begin_write(self):
        fake = FakeRuntimeConnection()
        fake.script_next(FakeCursor(rowcount=1))
        repo.create_participant(
            fake, participant_id="p1", display_name="Test"
        )
        assert fake.begin_write_count == 1

    def test_no_pre_insert_select(self):
        fake = FakeRuntimeConnection()
        fake.script_next(FakeCursor(rowcount=1))
        repo.create_participant(
            fake, participant_id="p1", display_name="Test"
        )
        first_sql = fake.execute_log[0][0]
        assert first_sql.strip().upper().startswith("INSERT")

    def test_insert_has_on_conflict_do_nothing(self):
        fake = FakeRuntimeConnection()
        fake.script_next(FakeCursor(rowcount=1))
        repo.create_participant(
            fake, participant_id="p1", display_name="Test"
        )
        insert_sql = fake.execute_log[0][0]
        assert "ON CONFLICT DO NOTHING" in insert_sql

    def test_conflict_target_not_limited_to_token_hash(self):
        fake = FakeRuntimeConnection()
        fake.script_next(FakeCursor(rowcount=1))
        repo.create_participant(
            fake, participant_id="p1", display_name="Test"
        )
        insert_sql = fake.execute_log[0][0]
        assert "ON CONFLICT(access_token_hash)" not in insert_sql
        assert "ON CONFLICT (access_token_hash)" not in insert_sql

    def test_values_are_parameterized(self):
        fake = FakeRuntimeConnection()
        fake.script_next(FakeCursor(rowcount=1))
        repo.create_participant(
            fake, participant_id="p1", display_name="Test"
        )
        insert_sql = fake.execute_log[0][0]
        params = fake.execute_log[0][1]
        assert "?" in insert_sql
        assert "p1" in params
        assert "Test" in params

    def test_no_token_interpolation_in_sql(self):
        fake = FakeRuntimeConnection()
        fake.script_next(FakeCursor(rowcount=1))
        result = repo.create_participant(
            fake, participant_id="p1", display_name="Test"
        )
        insert_sql = fake.execute_log[0][0]
        assert result.one_time_token not in insert_sql
        for _, params in fake.execute_log:
            for p in params:
                if isinstance(p, str):
                    assert result.one_time_token != p or len(p) == 64


# ---------------------------------------------------------------------------
# Duplicate ID simulation (fake)
# ---------------------------------------------------------------------------


class TestDuplicateIDSimulation:
    def test_duplicate_id_raises(self):
        fake = FakeRuntimeConnection()
        fake.script_next(FakeCursor(rowcount=0))
        fake.script_next(FakeCursor(rowcount=1, rows=[(1,)]))
        with pytest.raises(repo.DuplicateParticipantError):
            repo.create_participant(
                fake, participant_id="dup", display_name="Test"
            )
        assert fake.commit_count == 0
        assert fake.rollback_count == 1

    def test_duplicate_id_no_token_retry(self, monkeypatch):
        call_count = [0]
        monkeypatch.setattr(
            security, "generate_token",
            lambda: (call_count.__setitem__(0, call_count[0] + 1) or "tok"),
        )
        fake = FakeRuntimeConnection()
        fake.script_next(FakeCursor(rowcount=0))
        fake.script_next(FakeCursor(rowcount=1, rows=[(1,)]))
        with pytest.raises(repo.DuplicateParticipantError):
            repo.create_participant(
                fake, participant_id="dup", display_name="Test"
            )
        assert call_count[0] == 1

    def test_duplicate_id_no_raw_detail(self):
        fake = FakeRuntimeConnection()
        fake.script_next(FakeCursor(rowcount=0))
        fake.script_next(FakeCursor(rowcount=1, rows=[(1,)]))
        with pytest.raises(repo.DuplicateParticipantError) as exc_info:
            repo.create_participant(
                fake, participant_id="dup", display_name="Test"
            )
        msg = str(exc_info.value)
        assert "dup" not in msg or "already exists" in msg


# ---------------------------------------------------------------------------
# Token collision simulation (fake)
# ---------------------------------------------------------------------------


class TestTokenCollisionSimulation:
    def test_collision_then_success(self, monkeypatch):
        tokens = iter(["tok1", "tok2"])
        monkeypatch.setattr(security, "generate_token", lambda: next(tokens))
        fake = FakeRuntimeConnection()
        fake.script_next(FakeCursor(rowcount=0))
        fake.script_next(FakeCursor(rowcount=0, rows=[]))
        fake.script_next(FakeCursor(rowcount=1))
        result = repo.create_participant(
            fake, participant_id="p1", display_name="Test"
        )
        assert result.one_time_token == "tok2"
        assert fake.commit_count == 1
        assert fake.rollback_count == 0

    def test_collision_retry_count(self, monkeypatch):
        call_count = [0]
        monkeypatch.setattr(
            security, "generate_token",
            lambda: (call_count.__setitem__(0, call_count[0] + 1) or "tok"),
        )
        fake = FakeRuntimeConnection()
        fake.script_next(FakeCursor(rowcount=0))
        fake.script_next(FakeCursor(rowcount=0, rows=[]))
        fake.script_next(FakeCursor(rowcount=1))
        repo.create_participant(
            fake, participant_id="p1", display_name="Test"
        )
        assert call_count[0] == 2


# ---------------------------------------------------------------------------
# Retry exhaustion (fake)
# ---------------------------------------------------------------------------


class TestRetryExhaustion:
    def test_exhaustion_raises_token_error(self, monkeypatch):
        monkeypatch.setattr(security, "generate_token", lambda: "tok")
        fake = FakeRuntimeConnection()
        for _ in range(repo.MAX_TOKEN_COLLISION_RETRIES):
            fake.script_next(FakeCursor(rowcount=0))
            fake.script_next(FakeCursor(rowcount=0, rows=[]))
        with pytest.raises(repo.TokenProvisioningError):
            repo.create_participant(
                fake, participant_id="p1", display_name="Test"
            )
        assert fake.rollback_count == 1
        assert fake.commit_count == 0

    def test_exhaustion_exact_retry_count(self, monkeypatch):
        call_count = [0]
        monkeypatch.setattr(
            security, "generate_token",
            lambda: (call_count.__setitem__(0, call_count[0] + 1) or "tok"),
        )
        fake = FakeRuntimeConnection()
        for _ in range(repo.MAX_TOKEN_COLLISION_RETRIES):
            fake.script_next(FakeCursor(rowcount=0))
            fake.script_next(FakeCursor(rowcount=0, rows=[]))
        with pytest.raises(repo.TokenProvisioningError):
            repo.create_participant(
                fake, participant_id="p1", display_name="Test"
            )
        assert call_count[0] == repo.MAX_TOKEN_COLLISION_RETRIES


# ---------------------------------------------------------------------------
# Unexpected DB error (fake)
# ---------------------------------------------------------------------------


class TestUnexpectedDBError:
    def test_db_error_rollback_no_secret_leak(self):
        secret_cause = Exception(
            "postgresql://alice:s3cr3t@db.internal:5432/prod connection refused"
        )
        db_err = DatabaseError(safe_category="connection")
        db_err.__cause__ = secret_cause

        fake = FakeRuntimeConnection()

        def exploding_execute(sql, params=()):
            fake.execute_log.append((sql, tuple(params)))
            raise db_err

        fake.execute = exploding_execute
        with pytest.raises(DatabaseError) as exc_info:
            repo.create_participant(
                fake, participant_id="p1", display_name="Test"
            )
        assert fake.rollback_count == 1
        msg = str(exc_info.value)
        assert "s3cr3t" not in msg
        assert "alice" not in msg
        assert "db.internal" not in msg
        assert "postgresql://" not in msg

    def test_unexpected_rowcount_fails_closed(self):
        fake = FakeRuntimeConnection()
        fake.script_next(FakeCursor(rowcount=5))
        with pytest.raises(repo.RepositoryTransactionError):
            repo.create_participant(
                fake, participant_id="p1", display_name="Test"
            )
        assert fake.rollback_count == 1
        assert fake.commit_count == 0


# ---------------------------------------------------------------------------
# Row compatibility
# ---------------------------------------------------------------------------


class TestRowCompatibility:
    def test_sqlite3_row(self):
        rt, raw = _make_sqlite_runtime()
        result = repo.create_participant(
            rt, participant_id="p1", display_name="Test"
        )
        found = repo.get_participant_by_id(rt, "p1")
        assert found is not None
        assert found.id == "p1"
        assert found.display_name == "Test"
        rt.close()

    def test_dict_row(self):
        row_dict = {
            "id": "p1",
            "display_name": "Test",
            "preferred_language": "ko",
            "status": "active",
            "created_at": "2026-01-01T00:00:00.000Z",
            "updated_at": "2026-01-01T00:00:00.000Z",
            "deleted_at": None,
        }
        record = repo._row_to_record(row_dict)
        assert record.id == "p1"
        assert record.display_name == "Test"
        assert record.deleted_at is None


# ---------------------------------------------------------------------------
# SQLite regression (real SqliteRuntimeConnection)
# ---------------------------------------------------------------------------


class TestSQLiteRegression:
    def test_create_success(self):
        rt, _ = _make_sqlite_runtime()
        result = repo.create_participant(
            rt, participant_id="p1", display_name="Test User"
        )
        assert result.participant.id == "p1"
        assert result.one_time_token
        rt.close()

    def test_get_by_token(self):
        rt, _ = _make_sqlite_runtime()
        result = repo.create_participant(
            rt, participant_id="p1", display_name="Test User"
        )
        found = repo.get_active_participant_by_token(rt, result.one_time_token)
        assert found is not None
        assert found.id == "p1"
        rt.close()

    def test_get_by_id(self):
        rt, _ = _make_sqlite_runtime()
        repo.create_participant(rt, participant_id="p1", display_name="Test")
        found = repo.get_participant_by_id(rt, "p1")
        assert found is not None
        assert found.id == "p1"
        rt.close()

    def test_duplicate_participant(self):
        rt, _ = _make_sqlite_runtime()
        repo.create_participant(rt, participant_id="p1", display_name="First")
        with pytest.raises(repo.DuplicateParticipantError):
            repo.create_participant(
                rt, participant_id="p1", display_name="Second"
            )
        rt.close()

    def test_token_collision_retry(self, monkeypatch):
        tokens = iter(["tok1", "tok2"])
        hashes = {}
        orig_hash = security.hash_token

        def fake_hash(token):
            if token == "tok1":
                return "collision_hash"
            return orig_hash(token)

        monkeypatch.setattr(security, "generate_token", lambda: next(tokens))
        monkeypatch.setattr(security, "hash_token", fake_hash)

        rt, raw = _make_sqlite_runtime()
        raw.execute(
            "INSERT INTO participants "
            "(id, display_name, access_token_hash, preferred_language, "
            "tone_preference, length_preference, status, created_at, updated_at) "
            "VALUES ('other', 'Other', 'collision_hash', 'ko', "
            "'calm_editorial', 'standard', 'active', '2026-01-01', '2026-01-01')"
        )
        raw.commit()

        result = repo.create_participant(
            rt, participant_id="p1", display_name="Test"
        )
        assert result.one_time_token == "tok2"
        rt.close()

    def test_bounded_retry_exhaustion(self, monkeypatch):
        monkeypatch.setattr(security, "generate_token", lambda: "tok")
        monkeypatch.setattr(security, "hash_token", lambda t: "fixed_hash")

        rt, raw = _make_sqlite_runtime()
        raw.execute(
            "INSERT INTO participants "
            "(id, display_name, access_token_hash, preferred_language, "
            "tone_preference, length_preference, status, created_at, updated_at) "
            "VALUES ('other', 'Other', 'fixed_hash', 'ko', "
            "'calm_editorial', 'standard', 'active', '2026-01-01', '2026-01-01')"
        )
        raw.commit()

        with pytest.raises(repo.TokenProvisioningError):
            repo.create_participant(
                rt, participant_id="p1", display_name="Test"
            )
        rt.close()

    def test_delete_success(self):
        rt, _ = _make_sqlite_runtime()
        repo.create_participant(rt, participant_id="p1", display_name="Test")
        assert repo.delete_participant(rt, "p1") is True
        found = repo.get_participant_by_id(rt, "p1")
        assert found.status == "deleted"
        rt.close()

    def test_delete_again_false(self):
        rt, _ = _make_sqlite_runtime()
        repo.create_participant(rt, participant_id="p1", display_name="Test")
        repo.delete_participant(rt, "p1")
        assert repo.delete_participant(rt, "p1") is False
        rt.close()

    def test_connection_already_active(self):
        rt, raw = _make_sqlite_runtime()
        raw.execute("BEGIN")
        with pytest.raises(repo.RepositoryTransactionError):
            repo.create_participant(
                rt, participant_id="p1", display_name="Test"
            )
        raw.rollback()
        rt.close()

    def test_transaction_rollback_on_error(self, monkeypatch):
        rt, raw = _make_sqlite_runtime()

        def boom(*a, **kw):
            raise RuntimeError("simulated")

        monkeypatch.setattr(security, "generate_token", boom)
        with pytest.raises(RuntimeError):
            repo.create_participant(
                rt, participant_id="p1", display_name="Test"
            )
        assert raw.in_transaction is False
        rt.close()
