"""Concurrency regression tests for invitation claim atomicity (H-1).

Verifies that the conditional token consume prevents TOCTOU races when
multiple Firebase UIDs attempt to claim the same invitation code
concurrently. Uses real separate DB connections (not shared :memory:).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from app import external_identity_repository as eid_repo
from app.db import apply_migrations
from app.firebase import PROVIDER_FIREBASE
from app.invitation_claim import claim_invitation
from app.security import create_traveler_token
from app.traveler_repository import create_traveler

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


def _seed_traveler_and_code(db_path: str) -> tuple[str, str]:
    conn = _sqlite_conn(db_path)
    rec = create_traveler(conn, display_name="RaceTarget", destination="Seoul")
    _token_id, raw_code = create_traveler_token(conn, rec.id)
    conn.close()
    return rec.id, raw_code


class TestSQLiteConcurrentClaim:
    def test_two_uids_same_code_exactly_one_wins(self, tmp_path: Path):
        db_path = str(tmp_path / "race.db")
        _setup_sqlite_db(db_path)
        traveler_id, code = _seed_traveler_and_code(db_path)

        barrier = threading.Barrier(2, timeout=10)
        results: list = [None, None]

        def worker(idx: int, subject: str):
            conn = _sqlite_conn(db_path)
            try:
                barrier.wait()
                results[idx] = claim_invitation(
                    conn,
                    provider=PROVIDER_FIREBASE,
                    subject=subject,
                    invitation_code=code,
                )
            finally:
                conn.close()

        t0 = threading.Thread(target=worker, args=(0, "uid-race-A"))
        t1 = threading.Thread(target=worker, args=(1, "uid-race-B"))
        t0.start()
        t1.start()
        t0.join(timeout=15)
        t1.join(timeout=15)

        successes = [r for r in results if r is not None and r.ok]
        failures = [r for r in results if r is not None and not r.ok]

        assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
        assert len(failures) == 1
        assert failures[0].error == "invalid_invitation"
        assert successes[0].traveler_id == traveler_id

        verify = _sqlite_conn(db_path)
        try:
            identities = verify.execute(
                "SELECT * FROM external_identities "
                "WHERE traveler_id = ? AND revoked_at IS NULL",
                (traveler_id,),
            ).fetchall()
            assert len(identities) == 1

            tokens = verify.execute(
                "SELECT is_active FROM traveler_tokens WHERE traveler_id = ?",
                (traveler_id,),
            ).fetchall()
            assert all(t["is_active"] == 0 for t in tokens)

            all_identities = verify.execute(
                "SELECT COUNT(*) AS n FROM external_identities"
            ).fetchone()
            assert all_identities["n"] == 1
        finally:
            verify.close()

    def test_link_failure_rolls_back_token_consume(self, tmp_path: Path):
        db_path = str(tmp_path / "rollback.db")
        _setup_sqlite_db(db_path)
        traveler_id, code = _seed_traveler_and_code(db_path)

        conn = _sqlite_conn(db_path)
        try:
            with patch(
                "app.invitation_claim.eid_repo.link_traveler", return_value=None
            ):
                result = claim_invitation(
                    conn,
                    provider=PROVIDER_FIREBASE,
                    subject="uid-rollback",
                    invitation_code=code,
                )
            assert not result.ok
            assert result.error == "invalid_invitation"

            token = conn.execute(
                "SELECT is_active FROM traveler_tokens WHERE traveler_id = ?",
                (traveler_id,),
            ).fetchone()
            assert token["is_active"] == 1

            identity_count = conn.execute(
                "SELECT COUNT(*) AS n FROM external_identities WHERE subject = ?",
                ("uid-rollback",),
            ).fetchone()
            assert identity_count["n"] == 0
        finally:
            conn.close()

    def test_already_consumed_token_rejected(self, tmp_path: Path):
        db_path = str(tmp_path / "consumed.db")
        _setup_sqlite_db(db_path)
        traveler_id, code = _seed_traveler_and_code(db_path)

        conn = _sqlite_conn(db_path)
        try:
            first = claim_invitation(
                conn,
                provider=PROVIDER_FIREBASE,
                subject="uid-first",
                invitation_code=code,
            )
            assert first.ok

            second = claim_invitation(
                conn,
                provider=PROVIDER_FIREBASE,
                subject="uid-second",
                invitation_code=code,
            )
            assert not second.ok
            assert second.error == "invalid_invitation"

            identity_count = conn.execute(
                "SELECT COUNT(*) AS n FROM external_identities WHERE subject = ?",
                ("uid-second",),
            ).fetchone()
            assert identity_count["n"] == 0
        finally:
            conn.close()


@pytest.mark.skipif(
    not PG_URL, reason="LT_TEST_PG_URL not set; skipping PostgreSQL concurrency tests"
)
class TestPostgresConcurrentClaim:
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

    def _seed(self):
        conn = self._pg_conn()
        rec = create_traveler(conn, display_name="PGRace", destination="Busan")
        _tid, raw_code = create_traveler_token(conn, rec.id)
        conn.close()
        return rec.id, raw_code

    def test_two_uids_same_code_exactly_one_wins(self, pg_clean):
        traveler_id, code = self._seed()

        barrier = threading.Barrier(2, timeout=10)
        results: list = [None, None]

        def worker(idx: int, subject: str):
            conn = self._pg_conn()
            try:
                barrier.wait()
                results[idx] = claim_invitation(
                    conn,
                    provider=PROVIDER_FIREBASE,
                    subject=subject,
                    invitation_code=code,
                )
            finally:
                conn.close()

        t0 = threading.Thread(target=worker, args=(0, "uid-pg-A"))
        t1 = threading.Thread(target=worker, args=(1, "uid-pg-B"))
        t0.start()
        t1.start()
        t0.join(timeout=15)
        t1.join(timeout=15)

        successes = [r for r in results if r is not None and r.ok]
        failures = [r for r in results if r is not None and not r.ok]

        assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
        assert len(failures) == 1
        assert failures[0].error == "invalid_invitation"
        assert successes[0].traveler_id == traveler_id

        verify = self._pg_conn()
        try:
            identities = verify.execute(
                "SELECT * FROM external_identities "
                "WHERE traveler_id = ? AND revoked_at IS NULL",
                (traveler_id,),
            ).fetchall()
            assert len(identities) == 1

            tokens = verify.execute(
                "SELECT is_active FROM traveler_tokens WHERE traveler_id = ?",
                (traveler_id,),
            ).fetchall()
            assert all(t["is_active"] == 0 for t in tokens)
        finally:
            verify.close()

    def test_already_consumed_token_rejected(self, pg_clean):
        traveler_id, code = self._seed()

        conn = self._pg_conn()
        try:
            first = claim_invitation(
                conn,
                provider=PROVIDER_FIREBASE,
                subject="uid-pg-first",
                invitation_code=code,
            )
            assert first.ok

            second = claim_invitation(
                conn,
                provider=PROVIDER_FIREBASE,
                subject="uid-pg-second",
                invitation_code=code,
            )
            assert not second.ok
            assert second.error == "invalid_invitation"

            identity_count = conn.execute(
                "SELECT COUNT(*) AS n FROM external_identities WHERE subject = ?",
                ("uid-pg-second",),
            ).fetchone()
            assert identity_count["n"] == 0
        finally:
            conn.close()
