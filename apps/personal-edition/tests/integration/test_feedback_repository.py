import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app import edition_repository as ed_repo
from app import feedback_repository as fb_repo
from app import participant_repository as repo
from app.db import apply_migrations, get_connection
from app.db_runtime import SqliteRuntimeConnection


def _setup_participant(conn, pid="p1"):
    repo.create_participant(
        SqliteRuntimeConnection(conn),
        participant_id=pid,
        display_name="Test User",
        preferred_language="ko",
    )


def _setup_edition(conn, pid="p1", ed_num=1):
    return ed_repo.create_edition(
        conn, participant_id=pid, edition_number=ed_num
    )


_VALID_DIR = json.dumps(["more_practical"])
_VALID_DIR_2 = json.dumps(["shorter", "longer"])
_VALID_DIR_3 = json.dumps(["continue_direction"])


class TestFeedbackCreate:
    def test_create_feedback_stores_record(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        result = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=ed.id,
            direction_choices=_VALID_DIR,
        )

        assert result.participant_id == "p1"
        assert result.edition_id == ed.id
        assert json.loads(result.direction_choices) == ["more_practical"]
        assert result.applied_to_next_edition == 0
        assert result.id
        conn.close()

    def test_create_feedback_rejects_missing_participant(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        with pytest.raises(fb_repo.FeedbackValidationError):
            fb_repo.create_feedback(
                conn,
                participant_id="missing",
                edition_id=ed.id,
                direction_choices=_VALID_DIR,
            )
        conn.close()

    def test_create_feedback_rejects_missing_edition(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        with pytest.raises(fb_repo.FeedbackValidationError):
            fb_repo.create_feedback(
                conn,
                participant_id="p1",
                edition_id="nonexistent",
                direction_choices=_VALID_DIR,
            )
        conn.close()

    def test_create_feedback_rejects_wrong_participant(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn, "p1")
        _setup_participant(conn, "p2")
        ed = _setup_edition(conn, "p1")

        with pytest.raises(fb_repo.FeedbackValidationError):
            fb_repo.create_feedback(
                conn,
                participant_id="p2",
                edition_id=ed.id,
                direction_choices=_VALID_DIR,
            )
        conn.close()

    def test_create_feedback_rejects_empty_direction(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        with pytest.raises(fb_repo.FeedbackValidationError):
            fb_repo.create_feedback(
                conn,
                participant_id="p1",
                edition_id=ed.id,
                direction_choices="",
            )
        conn.close()

    def test_create_feedback_rejects_non_json_direction(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        with pytest.raises(fb_repo.FeedbackValidationError):
            fb_repo.create_feedback(
                conn,
                participant_id="p1",
                edition_id=ed.id,
                direction_choices="not-json",
            )
        conn.close()

    def test_create_feedback_rejects_scalar_direction(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        with pytest.raises(fb_repo.FeedbackValidationError):
            fb_repo.create_feedback(
                conn,
                participant_id="p1",
                edition_id=ed.id,
                direction_choices='"shorter"',
            )
        conn.close()

    def test_create_feedback_rejects_invalid_direction_value(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        with pytest.raises(fb_repo.FeedbackValidationError):
            fb_repo.create_feedback(
                conn,
                participant_id="p1",
                edition_id=ed.id,
                direction_choices=json.dumps(["invalid_direction"]),
            )
        conn.close()

    def test_create_feedback_rejects_empty_array(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        with pytest.raises(fb_repo.FeedbackValidationError):
            fb_repo.create_feedback(
                conn,
                participant_id="p1",
                edition_id=ed.id,
                direction_choices="[]",
            )
        conn.close()

    def test_create_feedback_rejects_existing_transaction(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        conn.execute("BEGIN")
        with pytest.raises(repo.RepositoryTransactionError):
            fb_repo.create_feedback(
                conn,
                participant_id="p1",
                edition_id=ed.id,
                direction_choices=_VALID_DIR,
            )
        conn.close()

    def test_create_feedback_with_valid_timestamp(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        result = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=ed.id,
            direction_choices=_VALID_DIR,
            submitted_at="2026-01-15T10:30:00.000Z",
        )
        assert result.submitted_at == "2026-01-15T10:30:00.000Z"
        conn.close()

    def test_create_feedback_rejects_invalid_timestamp(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        with pytest.raises(fb_repo.FeedbackValidationError):
            fb_repo.create_feedback(
                conn,
                participant_id="p1",
                edition_id=ed.id,
                direction_choices=_VALID_DIR,
                submitted_at="not-a-timestamp",
            )
        conn.close()


class TestFeedbackLookup:
    def test_get_feedback_by_id(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        created = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=ed.id,
            direction_choices=_VALID_DIR,
        )
        found = fb_repo.get_feedback_by_id(conn, created.id)
        assert found is not None
        assert json.loads(found.direction_choices) == ["more_practical"]
        conn.close()

    def test_get_feedback_by_id_returns_none(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        assert fb_repo.get_feedback_by_id(conn, "nope") is None
        conn.close()

    def test_get_feedback_by_edition(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=ed.id,
            direction_choices=_VALID_DIR,
        )
        fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=ed.id,
            direction_choices=_VALID_DIR_2,
        )

        feedbacks = fb_repo.get_feedback_by_edition(conn, ed.id)
        assert len(feedbacks) == 2
        conn.close()


class TestFeedbackMarkApplied:
    def test_mark_applied(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        fb = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=ed.id,
            direction_choices=_VALID_DIR,
        )
        updated = fb_repo.mark_feedback_applied(conn, fb.id)
        assert updated is not None
        assert updated.applied_to_next_edition == 1
        conn.close()

    def test_mark_applied_idempotent(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        fb = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=ed.id,
            direction_choices=_VALID_DIR,
        )
        fb_repo.mark_feedback_applied(conn, fb.id)
        result = fb_repo.mark_feedback_applied(conn, fb.id)
        assert result is None
        conn.close()


class TestFeedbackDelete:
    def test_delete_feedback(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        fb = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=ed.id,
            direction_choices=_VALID_DIR,
        )
        assert fb_repo.delete_feedback(conn, fb.id) is True
        assert fb_repo.get_feedback_by_id(conn, fb.id) is None
        conn.close()

    def test_delete_feedback_returns_false_for_missing(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        assert fb_repo.delete_feedback(conn, "nope") is False
        conn.close()


class TestFeedbackFilePersistence:
    def test_feedback_persists_after_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "test.db")
            conn = get_connection(db_path)
            apply_migrations(conn, "migrations")
            _setup_participant(conn)
            ed = _setup_edition(conn)

            created = fb_repo.create_feedback(
                conn,
                participant_id="p1",
                edition_id=ed.id,
                direction_choices=_VALID_DIR,
                free_text="More details please",
            )
            fb_repo.mark_feedback_applied(conn, created.id)
            conn.close()

            conn2 = get_connection(db_path)
            found = fb_repo.get_feedback_by_id(conn2, created.id)
            assert found is not None
            assert json.loads(found.direction_choices) == ["more_practical"]
            assert found.free_text == "More details please"
            assert found.applied_to_next_edition == 1
            conn2.close()


class TestFeedbackTimestampValidation:
    def test_valid_timestamp_accepted(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        result = fb_repo.create_feedback(
            conn,
            participant_id="p1",
            edition_id=ed.id,
            direction_choices=_VALID_DIR,
            submitted_at="2026-07-20T09:23:46.123Z",
        )
        assert result.submitted_at == "2026-07-20T09:23:46.123Z"
        conn.close()

    def test_calendar_invalid_month_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        with pytest.raises(fb_repo.FeedbackValidationError):
            fb_repo.create_feedback(
                conn,
                participant_id="p1",
                edition_id=ed.id,
                direction_choices=_VALID_DIR,
                submitted_at="2026-13-20T09:23:46.123Z",
            )
        conn.close()

    def test_calendar_invalid_day_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)
        ed = _setup_edition(conn)

        with pytest.raises(fb_repo.FeedbackValidationError):
            fb_repo.create_feedback(
                conn,
                participant_id="p1",
                edition_id=ed.id,
                direction_choices=_VALID_DIR,
                submitted_at="2026-02-30T09:23:46.123Z",
            )
        conn.close()
