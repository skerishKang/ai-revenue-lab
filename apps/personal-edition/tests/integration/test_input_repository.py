import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app import input_repository as input_repo
from app import participant_repository as repo
from app.db import apply_migrations, get_connection


def _setup_participant(conn, pid="p1"):
    repo.create_participant(
        conn,
        participant_id=pid,
        display_name="Test User",
        preferred_language="ko",
    )


class TestInputCreate:
    def test_create_input_stores_record(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        result = input_repo.create_input(
            conn,
            participant_id="p1",
            raw_text="Hello world",
            consent_confirmed=1,
        )

        assert result.participant_id == "p1"
        assert result.raw_text == "Hello world"
        assert result.consent_confirmed == 1
        assert result.sequence_number == 1
        assert result.deleted_at is None
        assert result.id
        conn.close()

    def test_sequence_number_increments(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        r1 = input_repo.create_input(
            conn, participant_id="p1", raw_text="First"
        )
        r2 = input_repo.create_input(
            conn, participant_id="p1", raw_text="Second"
        )
        r3 = input_repo.create_input(
            conn, participant_id="p1", raw_text="Third"
        )

        assert r1.sequence_number == 1
        assert r2.sequence_number == 2
        assert r3.sequence_number == 3
        conn.close()

    def test_different_participants_have_separate_sequences(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn, "p1")
        _setup_participant(conn, "p2")

        r1 = input_repo.create_input(
            conn, participant_id="p1", raw_text="P1 text"
        )
        r2 = input_repo.create_input(
            conn, participant_id="p2", raw_text="P2 text"
        )

        assert r1.sequence_number == 1
        assert r2.sequence_number == 1
        conn.close()

    def test_create_input_rejects_missing_participant(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        with pytest.raises(input_repo.InputValidationError):
            input_repo.create_input(
                conn, participant_id="nonexistent", raw_text="text"
            )
        conn.close()

    def test_create_input_rejects_empty_raw_text(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        with pytest.raises(input_repo.InputValidationError):
            input_repo.create_input(
                conn, participant_id="p1", raw_text=""
            )
        conn.close()

    def test_create_input_rejects_invalid_consent(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        with pytest.raises(input_repo.InputValidationError):
            input_repo.create_input(
                conn, participant_id="p1", raw_text="text",
                consent_confirmed=2,
            )
        conn.close()

    def test_create_input_rejects_existing_transaction(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        conn.execute("BEGIN")
        with pytest.raises(repo.RepositoryTransactionError):
            input_repo.create_input(
                conn, participant_id="p1", raw_text="text"
            )
        conn.close()


class TestInputLookup:
    def test_get_input_by_id(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        created = input_repo.create_input(
            conn, participant_id="p1", raw_text="Hello"
        )
        found = input_repo.get_input_by_id(conn, created.id)
        assert found is not None
        assert found.raw_text == "Hello"
        conn.close()

    def test_get_input_by_id_returns_none(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        assert input_repo.get_input_by_id(conn, "nonexistent") is None
        conn.close()

    def test_get_inputs_by_participant(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        input_repo.create_input(conn, participant_id="p1", raw_text="A")
        input_repo.create_input(conn, participant_id="p1", raw_text="B")

        inputs = input_repo.get_inputs_by_participant(conn, "p1")
        assert len(inputs) == 2
        assert inputs[0].raw_text == "A"
        assert inputs[1].raw_text == "B"
        conn.close()

    def test_get_inputs_by_participant_returns_empty(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        inputs = input_repo.get_inputs_by_participant(conn, "nobody")
        assert inputs == []
        conn.close()


class TestInputUpdate:
    def test_update_normalized_text(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        created = input_repo.create_input(
            conn, participant_id="p1", raw_text="Hello"
        )
        updated = input_repo.update_input_normalized_text(
            conn, created.id, "hello world"
        )
        assert updated is not None
        assert updated.normalized_text == "hello world"
        conn.close()

    def test_update_normalized_text_returns_none_for_missing(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        result = input_repo.update_input_normalized_text(
            conn, "nonexistent", "text"
        )
        assert result is None
        conn.close()


class TestInputDelete:
    def test_delete_input_sets_deleted_at(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        created = input_repo.create_input(
            conn, participant_id="p1", raw_text="Delete me"
        )
        assert input_repo.delete_input(conn, created.id) is True

        found = input_repo.get_input_by_id(conn, created.id)
        assert found is not None
        assert found.deleted_at is not None
        conn.close()

    def test_delete_input_returns_false_for_missing(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        assert input_repo.delete_input(conn, "nonexistent") is False
        conn.close()

    def test_delete_input_idempotent(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        created = input_repo.create_input(
            conn, participant_id="p1", raw_text="text"
        )
        assert input_repo.delete_input(conn, created.id) is True
        assert input_repo.delete_input(conn, created.id) is False
        conn.close()


class TestInputTransactionRollback:
    def test_create_input_rollback_on_participant_check_failure(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        with pytest.raises(input_repo.InputValidationError):
            input_repo.create_input(
                conn, participant_id="missing", raw_text="text"
            )
        assert conn.in_transaction is False
        conn.close()


class TestInputFilePersistence:
    def test_input_persists_after_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "test.db")
            conn = get_connection(db_path)
            apply_migrations(conn, "migrations")
            _setup_participant(conn)

            created = input_repo.create_input(
                conn, participant_id="p1", raw_text="Persistent"
            )
            conn.close()

            conn2 = get_connection(db_path)
            found = input_repo.get_input_by_id(conn2, created.id)
            assert found is not None
            assert found.raw_text == "Persistent"
            assert found.sequence_number == 1
            conn2.close()


class TestInputForeignKey:
    def test_input_references_existing_participant(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        result = input_repo.create_input(
            conn, participant_id="p1", raw_text="FK test"
        )
        row = conn.execute(
            "SELECT participant_id FROM inputs WHERE id = ?",
            (result.id,),
        ).fetchone()
        assert row["participant_id"] == "p1"
        conn.close()


class TestInputTimestampValidation:
    def test_valid_timestamp_accepted(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        result = input_repo.create_input(
            conn, participant_id="p1", raw_text="text",
            submitted_at="2026-07-20T09:23:46.123Z",
        )
        assert result.submitted_at == "2026-07-20T09:23:46.123Z"
        conn.close()

    def test_calendar_invalid_month_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        with pytest.raises(input_repo.InputValidationError):
            input_repo.create_input(
                conn, participant_id="p1", raw_text="text",
                submitted_at="2026-13-20T09:23:46.123Z",
            )
        conn.close()

    def test_calendar_invalid_day_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        with pytest.raises(input_repo.InputValidationError):
            input_repo.create_input(
                conn, participant_id="p1", raw_text="text",
                submitted_at="2026-02-30T09:23:46.123Z",
            )
        conn.close()

    def test_shape_invalid_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        with pytest.raises(input_repo.InputValidationError):
            input_repo.create_input(
                conn, participant_id="p1", raw_text="text",
                submitted_at="not-a-timestamp",
            )
        conn.close()
