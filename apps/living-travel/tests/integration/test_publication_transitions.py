"""Tests for terminal publication-state transitions (Task E).

Verifies:
- pending → published / rejected succeed
- rejected → published and published → rejected are blocked
- duplicate publish/reject return 409
- concurrent publish vs reject: exactly one wins
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

import pytest

from app.db import apply_migrations
from app.edition_repository import (
    create_edition,
    get_edition_by_id,
    transition_edition_publication,
    update_edition_generation_status,
)

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


def _seed_reviewable_edition(db_path: str) -> str:
    conn = _sqlite_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO travelers (id, display_name, destination, trip_duration_nights, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("trav_pub", "PubTest", "Seoul", 2, "active", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
        )
        conn.commit()
        edition = create_edition(conn, traveler_id="trav_pub", edition_number=1)
        update_edition_generation_status(conn, edition.id, "pending_review")
        return edition.id
    finally:
        conn.close()


class TestSQLitePublicationTransitions:
    def test_pending_to_published(self, tmp_path: Path):
        db_path = str(tmp_path / "pub.db")
        _setup_sqlite_db(db_path)
        edition_id = _seed_reviewable_edition(db_path)
        conn = _sqlite_conn(db_path)
        try:
            assert transition_edition_publication(conn, edition_id, "pending", "published")
            ed = get_edition_by_id(conn, edition_id)
            assert ed is not None
            assert ed.publication_state == "published"
        finally:
            conn.close()

    def test_pending_to_rejected(self, tmp_path: Path):
        db_path = str(tmp_path / "rej.db")
        _setup_sqlite_db(db_path)
        edition_id = _seed_reviewable_edition(db_path)
        conn = _sqlite_conn(db_path)
        try:
            assert transition_edition_publication(conn, edition_id, "pending", "rejected")
            ed = get_edition_by_id(conn, edition_id)
            assert ed is not None
            assert ed.publication_state == "rejected"
        finally:
            conn.close()

    def test_rejected_cannot_be_published(self, tmp_path: Path):
        db_path = str(tmp_path / "rej2.db")
        _setup_sqlite_db(db_path)
        edition_id = _seed_reviewable_edition(db_path)
        conn = _sqlite_conn(db_path)
        try:
            assert transition_edition_publication(conn, edition_id, "pending", "rejected")
            assert not transition_edition_publication(conn, edition_id, "pending", "published")
            ed = get_edition_by_id(conn, edition_id)
            assert ed is not None
            assert ed.publication_state == "rejected"
        finally:
            conn.close()

    def test_published_cannot_be_rejected(self, tmp_path: Path):
        db_path = str(tmp_path / "pub2.db")
        _setup_sqlite_db(db_path)
        edition_id = _seed_reviewable_edition(db_path)
        conn = _sqlite_conn(db_path)
        try:
            assert transition_edition_publication(conn, edition_id, "pending", "published")
            assert not transition_edition_publication(conn, edition_id, "pending", "rejected")
            ed = get_edition_by_id(conn, edition_id)
            assert ed is not None
            assert ed.publication_state == "published"
        finally:
            conn.close()

    def test_duplicate_publish_returns_false(self, tmp_path: Path):
        db_path = str(tmp_path / "dup.db")
        _setup_sqlite_db(db_path)
        edition_id = _seed_reviewable_edition(db_path)
        conn = _sqlite_conn(db_path)
        try:
            assert transition_edition_publication(conn, edition_id, "pending", "published")
            assert not transition_edition_publication(conn, edition_id, "pending", "published")
        finally:
            conn.close()

    def test_duplicate_reject_returns_false(self, tmp_path: Path):
        db_path = str(tmp_path / "dup2.db")
        _setup_sqlite_db(db_path)
        edition_id = _seed_reviewable_edition(db_path)
        conn = _sqlite_conn(db_path)
        try:
            assert transition_edition_publication(conn, edition_id, "pending", "rejected")
            assert not transition_edition_publication(conn, edition_id, "pending", "rejected")
        finally:
            conn.close()

    def test_non_reviewable_edition_cannot_transition(self, tmp_path: Path):
        db_path = str(tmp_path / "nonrev.db")
        _setup_sqlite_db(db_path)
        conn = _sqlite_conn(db_path)
        try:
            conn.execute(
                "INSERT INTO travelers (id, display_name, destination, trip_duration_nights, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("trav_nr", "NRTest", "Seoul", 2, "active", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
            )
            conn.commit()
            edition = create_edition(conn, traveler_id="trav_nr", edition_number=1)
            assert not transition_edition_publication(conn, edition.id, "pending", "published")
        finally:
            conn.close()

    def test_concurrent_publish_vs_reject_exactly_one_wins(self, tmp_path: Path):
        db_path = str(tmp_path / "race.db")
        _setup_sqlite_db(db_path)
        edition_id = _seed_reviewable_edition(db_path)

        barrier = threading.Barrier(2, timeout=10)
        results: list = [None, None]

        def publish_worker():
            conn = _sqlite_conn(db_path)
            try:
                barrier.wait()
                results[0] = transition_edition_publication(conn, edition_id, "pending", "published")
            finally:
                conn.close()

        def reject_worker():
            conn = _sqlite_conn(db_path)
            try:
                barrier.wait()
                results[1] = transition_edition_publication(conn, edition_id, "pending", "rejected")
            finally:
                conn.close()

        t0 = threading.Thread(target=publish_worker)
        t1 = threading.Thread(target=reject_worker)
        t0.start()
        t1.start()
        t0.join(timeout=15)
        t1.join(timeout=15)

        assert results[0] is not None
        assert results[1] is not None
        assert sum(results) == 1

        verify = _sqlite_conn(db_path)
        try:
            ed = get_edition_by_id(verify, edition_id)
            assert ed is not None
            assert ed.publication_state in ("published", "rejected")
        finally:
            verify.close()


@pytest.mark.skipif(
    not PG_URL, reason="LT_TEST_PG_URL not set; skipping PostgreSQL publication tests"
)
class TestPostgresPublicationTransitions:
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

    def _seed_reviewable(self):
        conn = self._pg_conn()
        try:
            conn.execute(
                "INSERT INTO travelers (id, display_name, destination, trip_duration_nights, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("trav_pg_pub", "PGPubTest", "Busan", 2, "active", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
            )
            conn.commit()
            edition = create_edition(conn, traveler_id="trav_pg_pub", edition_number=1)
            update_edition_generation_status(conn, edition.id, "pending_review")
            return edition.id
        finally:
            conn.close()

    def test_pending_to_published(self, pg_clean):
        edition_id = self._seed_reviewable()
        conn = self._pg_conn()
        try:
            assert transition_edition_publication(conn, edition_id, "pending", "published")
            ed = get_edition_by_id(conn, edition_id)
            assert ed is not None
            assert ed.publication_state == "published"
        finally:
            conn.close()

    def test_rejected_cannot_be_published(self, pg_clean):
        edition_id = self._seed_reviewable()
        conn = self._pg_conn()
        try:
            assert transition_edition_publication(conn, edition_id, "pending", "rejected")
            assert not transition_edition_publication(conn, edition_id, "pending", "published")
        finally:
            conn.close()

    def test_concurrent_publish_vs_reject_exactly_one_wins(self, pg_clean):
        edition_id = self._seed_reviewable()

        barrier = threading.Barrier(2, timeout=10)
        results: list = [None, None]

        def publish_worker():
            conn = self._pg_conn()
            try:
                barrier.wait()
                results[0] = transition_edition_publication(conn, edition_id, "pending", "published")
            finally:
                conn.close()

        def reject_worker():
            conn = self._pg_conn()
            try:
                barrier.wait()
                results[1] = transition_edition_publication(conn, edition_id, "pending", "rejected")
            finally:
                conn.close()

        t0 = threading.Thread(target=publish_worker)
        t1 = threading.Thread(target=reject_worker)
        t0.start()
        t1.start()
        t0.join(timeout=15)
        t1.join(timeout=15)

        assert sum(results) == 1

        verify = self._pg_conn()
        try:
            ed = get_edition_by_id(verify, edition_id)
            assert ed is not None
            assert ed.publication_state in ("published", "rejected")
        finally:
            verify.close()
