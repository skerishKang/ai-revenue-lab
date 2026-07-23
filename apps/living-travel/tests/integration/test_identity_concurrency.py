"""Concurrency and atomicity tests for external identity lifecycle.

Covers:
- ensure_identity concurrent INSERT race (SQLite + PostgreSQL)
- atomic traveler/operator link (no TOCTOU)
- revoked identity relink blocked at repository level
- admin bind failure rollback (no partial state)
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

import pytest

from app import external_identity_repository as eid_repo
from app.db import apply_migrations
from app.firebase import PROVIDER_FIREBASE

PG_URL = os.environ.get("LT_TEST_PG_URL", "")


def _setup_sqlite_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    apply_migrations(db_path)
    conn.close()


def _sqlite_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


class TestSQLiteEnsureIdentityConcurrency:
    def test_concurrent_ensure_identity_single_row(self, tmp_path: Path):
        db_path = str(tmp_path / "race.db")
        _setup_sqlite_db(db_path)

        barrier = threading.Barrier(2, timeout=10)
        results: list = [None, None]

        def worker(idx: int):
            conn = _sqlite_conn(db_path)
            try:
                barrier.wait()
                results[idx] = eid_repo.ensure_identity(
                    conn, PROVIDER_FIREBASE, "uid-concurrent"
                )
            finally:
                conn.close()

        t0 = threading.Thread(target=worker, args=(0,))
        t1 = threading.Thread(target=worker, args=(1,))
        t0.start()
        t1.start()
        t0.join(timeout=15)
        t1.join(timeout=15)

        assert results[0] is not None
        assert results[1] is not None
        assert results[0].id == results[1].id

        verify = _sqlite_conn(db_path)
        try:
            count = verify.execute(
                "SELECT COUNT(*) AS n FROM external_identities WHERE subject = ?",
                ("uid-concurrent",),
            ).fetchone()
            assert count["n"] == 1
        finally:
            verify.close()

    def test_ensure_identity_idempotent(self, tmp_path: Path):
        db_path = str(tmp_path / "idem.db")
        _setup_sqlite_db(db_path)
        conn = _sqlite_conn(db_path)
        try:
            first = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, "uid-idem")
            second = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, "uid-idem")
            assert first.id == second.id
        finally:
            conn.close()


class TestSQLiteAtomicLinking:
    def test_link_traveler_blocked_when_operator(self, tmp_path: Path):
        db_path = str(tmp_path / "link.db")
        _setup_sqlite_db(db_path)
        conn = _sqlite_conn(db_path)
        try:
            identity = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, "uid-op")
            eid_repo.link_operator(conn, identity.id, "op_test_1")
            result = eid_repo.link_traveler(conn, identity.id, "trav_test_1")
            assert result is None
            row = conn.execute(
                "SELECT traveler_id, operator_id FROM external_identities WHERE id = ?",
                (identity.id,),
            ).fetchone()
            assert row["traveler_id"] is None
            assert row["operator_id"] == "op_test_1"
        finally:
            conn.close()

    def test_link_operator_blocked_when_traveler(self, tmp_path: Path):
        db_path = str(tmp_path / "link2.db")
        _setup_sqlite_db(db_path)
        conn = _sqlite_conn(db_path)
        try:
            conn.execute(
                "INSERT INTO travelers (id, display_name, destination, trip_duration_nights, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("trav_test_2", "T2", "Seoul", 2, "active", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
            )
            conn.commit()
            identity = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, "uid-trav")
            eid_repo.link_traveler(conn, identity.id, "trav_test_2")
            result = eid_repo.link_operator(conn, identity.id, "op_test_2")
            assert result is None
            row = conn.execute(
                "SELECT traveler_id, operator_id FROM external_identities WHERE id = ?",
                (identity.id,),
            ).fetchone()
            assert row["operator_id"] is None
            assert row["traveler_id"] == "trav_test_2"
        finally:
            conn.close()

    def test_concurrent_traveler_and_operator_link_exactly_one_wins(self, tmp_path: Path):
        db_path = str(tmp_path / "dual.db")
        _setup_sqlite_db(db_path)
        conn_setup = _sqlite_conn(db_path)
        identity = eid_repo.ensure_identity(conn_setup, PROVIDER_FIREBASE, "uid-dual")
        identity_id = identity.id
        conn_setup.close()

        barrier = threading.Barrier(2, timeout=10)
        results: list = [None, None]

        def link_traveler_worker():
            conn = _sqlite_conn(db_path)
            try:
                barrier.wait()
                results[0] = eid_repo.link_traveler(conn, identity_id, "trav_dual")
            finally:
                conn.close()

        def link_operator_worker():
            conn = _sqlite_conn(db_path)
            try:
                barrier.wait()
                results[1] = eid_repo.link_operator(conn, identity_id, "op_dual")
            finally:
                conn.close()

        t0 = threading.Thread(target=link_traveler_worker)
        t1 = threading.Thread(target=link_operator_worker)
        t0.start()
        t1.start()
        t0.join(timeout=15)
        t1.join(timeout=15)

        successes = [r for r in results if r is not None]
        assert len(successes) == 1

        verify = _sqlite_conn(db_path)
        try:
            row = verify.execute(
                "SELECT traveler_id, operator_id FROM external_identities WHERE id = ?",
                (identity_id,),
            ).fetchone()
            filled = [v for v in (row["traveler_id"], row["operator_id"]) if v is not None]
            assert len(filled) == 1
        finally:
            verify.close()


class TestSQLiteRevokedIdentity:
    def test_revoked_identity_cannot_link_traveler(self, tmp_path: Path):
        db_path = str(tmp_path / "revoked.db")
        _setup_sqlite_db(db_path)
        conn = _sqlite_conn(db_path)
        try:
            identity = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, "uid-revoked")
            eid_repo.revoke_identity(conn, identity.id)
            result = eid_repo.link_traveler(conn, identity.id, "trav_revoked")
            assert result is None
            row = conn.execute(
                "SELECT traveler_id FROM external_identities WHERE id = ?",
                (identity.id,),
            ).fetchone()
            assert row["traveler_id"] is None
        finally:
            conn.close()

    def test_revoked_identity_cannot_link_operator(self, tmp_path: Path):
        db_path = str(tmp_path / "revoked2.db")
        _setup_sqlite_db(db_path)
        conn = _sqlite_conn(db_path)
        try:
            identity = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, "uid-revoked2")
            eid_repo.revoke_identity(conn, identity.id)
            result = eid_repo.link_operator(conn, identity.id, "op_revoked")
            assert result is None
            row = conn.execute(
                "SELECT operator_id FROM external_identities WHERE id = ?",
                (identity.id,),
            ).fetchone()
            assert row["operator_id"] is None
        finally:
            conn.close()


class TestSQLiteAdminBindRollback:
    def test_bind_failure_leaves_no_partial_state(self, tmp_path: Path):
        db_path = str(tmp_path / "rollback.db")
        _setup_sqlite_db(db_path)
        conn = _sqlite_conn(db_path)
        try:
            conn.execute(
                "INSERT INTO travelers (id, display_name, destination, trip_duration_nights, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("trav_rb", "RB", "Seoul", 2, "active", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
            )
            conn.commit()
            identity = eid_repo.ensure_identity(
                conn, PROVIDER_FIREBASE, "uid-rb", commit=False
            )
            eid_repo.link_traveler(conn, identity.id, "trav_rb", commit=False)
            result = eid_repo.link_operator(conn, identity.id, "op_rb", commit=False)
            assert result is None
            conn.rollback()
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM external_identities WHERE subject = ?",
                ("uid-rb",),
            ).fetchone()
            assert row["n"] == 0
        finally:
            conn.close()

    def test_operator_id_does_not_contain_firebase_uid(self, tmp_path: Path):
        db_path = str(tmp_path / "opid.db")
        _setup_sqlite_db(db_path)
        conn = _sqlite_conn(db_path)
        try:
            identity = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, "uid-privacy")
            import secrets as _secrets

            operator_id = f"op_{_secrets.token_urlsafe(16)}"
            eid_repo.link_operator(conn, identity.id, operator_id)
            row = conn.execute(
                "SELECT operator_id FROM external_identities WHERE id = ?",
                (identity.id,),
            ).fetchone()
            assert "uid-privacy" not in row["operator_id"]
            assert row["operator_id"].startswith("op_")
        finally:
            conn.close()


@pytest.mark.skipif(
    not PG_URL, reason="LT_TEST_PG_URL not set; skipping PostgreSQL identity tests"
)
class TestPostgresIdentityConcurrency:
    @pytest.fixture()
    def pg_env(self, monkeypatch):
        monkeypatch.setenv("LT_DATABASE_BACKEND", "postgresql")
        monkeypatch.setenv("LT_AUTH_MODE", "legacy")
        monkeypatch.setenv("LT_ENVIRONMENT", "testing")
        monkeypatch.setenv("LT_OPERATOR_SECRET", "test-secret-12345")
        monkeypatch.setenv("LT_DATABASE_URL", PG_URL)
        monkeypatch.setenv("LT_MIGRATION_DATABASE_URL", PG_URL)
        from app.config import reset_settings

        reset_settings()
        yield PG_URL
        reset_settings()

    @pytest.fixture()
    def pg_clean(self, pg_env):
        import psycopg

        conn = psycopg.connect(PG_URL, autocommit=True)
        tables = [
            "deactivation_requests", "traveler_sessions", "traveler_tokens",
            "operator_sessions", "feedback", "editions", "travel_inputs",
            "sources", "generation_runs", "pilot_evidence",
            "external_identities", "travelers", "schema_migrations",
        ]
        with conn.cursor() as cur:
            for t in tables:
                cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
        conn.close()

        from app.db import apply_migrations as am

        am()
        return PG_URL

    def _pg_conn(self):
        from app.db import get_connection

        return get_connection()

    def test_concurrent_ensure_identity_single_row(self, pg_clean):
        barrier = threading.Barrier(2, timeout=10)
        results: list = [None, None]

        def worker(idx: int):
            conn = self._pg_conn()
            try:
                barrier.wait()
                results[idx] = eid_repo.ensure_identity(
                    conn, PROVIDER_FIREBASE, "uid-pg-concurrent"
                )
            finally:
                conn.close()

        t0 = threading.Thread(target=worker, args=(0,))
        t1 = threading.Thread(target=worker, args=(1,))
        t0.start()
        t1.start()
        t0.join(timeout=15)
        t1.join(timeout=15)

        assert results[0] is not None
        assert results[1] is not None
        assert results[0].id == results[1].id

        verify = self._pg_conn()
        try:
            count = verify.execute(
                "SELECT COUNT(*) AS n FROM external_identities WHERE subject = ?",
                ("uid-pg-concurrent",),
            ).fetchone()
            assert count["n"] == 1
        finally:
            verify.close()

    def test_concurrent_traveler_and_operator_link_exactly_one_wins(self, pg_clean):
        conn_setup = self._pg_conn()
        identity = eid_repo.ensure_identity(conn_setup, PROVIDER_FIREBASE, "uid-pg-dual")
        identity_id = identity.id
        conn_setup.close()

        barrier = threading.Barrier(2, timeout=10)
        results: list = [None, None]

        def link_traveler_worker():
            conn = self._pg_conn()
            try:
                barrier.wait()
                results[0] = eid_repo.link_traveler(conn, identity_id, "trav_pg_dual")
            finally:
                conn.close()

        def link_operator_worker():
            conn = self._pg_conn()
            try:
                barrier.wait()
                results[1] = eid_repo.link_operator(conn, identity_id, "op_pg_dual")
            finally:
                conn.close()

        t0 = threading.Thread(target=link_traveler_worker)
        t1 = threading.Thread(target=link_operator_worker)
        t0.start()
        t1.start()
        t0.join(timeout=15)
        t1.join(timeout=15)

        successes = [r for r in results if r is not None]
        assert len(successes) == 1

        verify = self._pg_conn()
        try:
            row = verify.execute(
                "SELECT traveler_id, operator_id FROM external_identities WHERE id = ?",
                (identity_id,),
            ).fetchone()
            filled = [v for v in (row["traveler_id"], row["operator_id"]) if v is not None]
            assert len(filled) == 1
        finally:
            verify.close()

    def test_revoked_identity_cannot_link(self, pg_clean):
        conn = self._pg_conn()
        try:
            identity = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, "uid-pg-revoked")
            eid_repo.revoke_identity(conn, identity.id)
            assert eid_repo.link_traveler(conn, identity.id, "trav_pg_rev") is None
            assert eid_repo.link_operator(conn, identity.id, "op_pg_rev") is None
        finally:
            conn.close()
