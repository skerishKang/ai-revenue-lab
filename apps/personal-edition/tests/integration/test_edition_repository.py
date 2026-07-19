import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app import edition_repository as ed_repo
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


class TestEditionCreate:
    def test_create_edition_stores_record(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        result = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )

        assert result.participant_id == "p1"
        assert result.edition_number == 1
        assert result.generation_status == "pending_review"
        assert result.publication_state == "pending"
        assert result.id
        conn.close()

    def test_create_edition_with_content(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        content = json.dumps({"title": "Test", "sections": []})
        result = ed_repo.create_edition(
            conn,
            participant_id="p1",
            edition_number=1,
            structured_content=content,
            rendered_title="Test Edition",
        )

        assert result.structured_content == content
        assert result.rendered_title == "Test Edition"
        conn.close()

    def test_create_edition_rejects_duplicate_number(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        with pytest.raises(ed_repo.EditionStateConflict):
            ed_repo.create_edition(
                conn, participant_id="p1", edition_number=1
            )
        conn.close()

    def test_create_edition_rejects_invalid_json(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        with pytest.raises(ed_repo.EditionValidationError):
            ed_repo.create_edition(
                conn,
                participant_id="p1",
                edition_number=1,
                structured_content="not json {{{",
            )
        conn.close()

    def test_create_edition_rejects_missing_participant(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        with pytest.raises(ed_repo.EditionValidationError):
            ed_repo.create_edition(
                conn, participant_id="missing", edition_number=1
            )
        conn.close()

    def test_create_edition_with_prior_edition(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        e1 = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        e2 = ed_repo.create_edition(
            conn,
            participant_id="p1",
            edition_number=2,
            prior_edition_id=e1.id,
        )
        assert e2.prior_edition_id == e1.id
        conn.close()

    def test_create_edition_rejects_invalid_prior(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        with pytest.raises(ed_repo.EditionValidationError):
            ed_repo.create_edition(
                conn,
                participant_id="p1",
                edition_number=1,
                prior_edition_id="nonexistent",
            )
        conn.close()

    def test_create_edition_rejects_cross_participant_prior(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn, "p1")
        _setup_participant(conn, "p2")

        e1 = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        with pytest.raises(ed_repo.EditionValidationError):
            ed_repo.create_edition(
                conn,
                participant_id="p2",
                edition_number=1,
                prior_edition_id=e1.id,
            )
        conn.close()

    def test_create_edition_rejects_cross_participant_input(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn, "p1")
        _setup_participant(conn, "p2")

        inp = input_repo.create_input(
            conn, participant_id="p1", raw_text="text"
        )
        with pytest.raises(ed_repo.EditionValidationError):
            ed_repo.create_edition(
                conn,
                participant_id="p2",
                edition_number=1,
                input_id=inp.id,
            )
        conn.close()

    def test_create_edition_rejects_deleted_input(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        inp = input_repo.create_input(
            conn, participant_id="p1", raw_text="text"
        )
        input_repo.delete_input(conn, inp.id)

        with pytest.raises(ed_repo.EditionValidationError):
            ed_repo.create_edition(
                conn,
                participant_id="p1",
                edition_number=1,
                input_id=inp.id,
            )
        conn.close()

    def test_create_edition_rejects_existing_transaction(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        conn.execute("BEGIN")
        with pytest.raises(repo.RepositoryTransactionError):
            ed_repo.create_edition(
                conn, participant_id="p1", edition_number=1
            )
        conn.close()


class TestEditionLookup:
    def test_get_edition_by_id(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        created = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        found = ed_repo.get_edition_by_id(conn, created.id)
        assert found is not None
        assert found.edition_number == 1
        conn.close()

    def test_get_edition_by_id_returns_none(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        assert ed_repo.get_edition_by_id(conn, "nope") is None
        conn.close()

    def test_get_editions_by_participant(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed_repo.create_edition(conn, participant_id="p1", edition_number=1)
        ed_repo.create_edition(conn, participant_id="p1", edition_number=2)

        editions = ed_repo.get_editions_by_participant(conn, "p1")
        assert len(editions) == 2
        assert editions[0].edition_number == 1
        assert editions[1].edition_number == 2
        conn.close()


class TestEditionPublicationTransition:
    def test_pending_to_published(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        updated = ed_repo.update_edition_publication(
            conn, ed.id, "published"
        )
        assert updated is not None
        assert updated.publication_state == "published"
        assert updated.published_at is not None
        assert updated.generation_status == "pending_review"
        conn.close()

    def test_pending_to_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        updated = ed_repo.update_edition_publication(
            conn, ed.id, "rejected"
        )
        assert updated is not None
        assert updated.publication_state == "rejected"
        assert updated.reviewed_at is not None
        conn.close()

    def test_invalid_transition_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        ed_repo.update_edition_publication(conn, ed.id, "published")

        with pytest.raises(ed_repo.EditionStateConflict):
            ed_repo.update_edition_publication(conn, ed.id, "rejected")
        conn.close()

    def test_published_cannot_transition(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        ed_repo.update_edition_publication(conn, ed.id, "published")

        with pytest.raises(ed_repo.EditionStateConflict):
            ed_repo.update_edition_publication(conn, ed.id, "pending")
        conn.close()

    def test_update_status_returns_none_for_missing(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        result = ed_repo.update_edition_publication(
            conn, "nonexistent", "published"
        )
        assert result is None
        conn.close()

    def test_invalid_publication_state_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        with pytest.raises(ed_repo.EditionValidationError):
            ed_repo.update_edition_publication(
                conn, ed.id, "invalid_state"
            )
        conn.close()


class TestEditionContent:
    def test_update_content_on_pending(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        content = json.dumps({"updated": True})
        updated = ed_repo.update_edition_content(
            conn, ed.id, structured_content=content, rendered_title="New"
        )
        assert updated is not None
        assert updated.structured_content == content
        assert updated.rendered_title == "New"
        conn.close()

    def test_update_content_rejects_after_publish(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        ed_repo.update_edition_publication(conn, ed.id, "published")

        with pytest.raises(ed_repo.EditionStateConflict):
            ed_repo.update_edition_content(
                conn, ed.id,
                structured_content=json.dumps({"x": 1}),
            )
        conn.close()

    def test_update_content_rejects_after_reject(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        ed_repo.update_edition_publication(conn, ed.id, "rejected")

        with pytest.raises(ed_repo.EditionStateConflict):
            ed_repo.update_edition_content(
                conn, ed.id,
                structured_content=json.dumps({"x": 1}),
            )
        conn.close()

    def test_update_content_rejects_invalid_json(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        with pytest.raises(ed_repo.EditionValidationError):
            ed_repo.update_edition_content(
                conn, ed.id, structured_content="bad json"
            )
        conn.close()


class TestEditionDelete:
    def test_delete_pending_edition(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        assert ed_repo.delete_edition(conn, ed.id) is True

        found = ed_repo.get_edition_by_id(conn, ed.id)
        assert found.generation_status == "deleted"
        conn.close()

    def test_delete_rejects_published_edition(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        ed_repo.update_edition_publication(conn, ed.id, "published")

        with pytest.raises(ed_repo.EditionStateConflict):
            ed_repo.delete_edition(conn, ed.id)
        conn.close()

    def test_delete_edition_returns_false_for_missing(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        assert ed_repo.delete_edition(conn, "nope") is False
        conn.close()

    def test_delete_edition_idempotent(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup_participant(conn)

        ed = ed_repo.create_edition(
            conn, participant_id="p1", edition_number=1
        )
        assert ed_repo.delete_edition(conn, ed.id) is True
        assert ed_repo.delete_edition(conn, ed.id) is False
        conn.close()


class TestEditionFilePersistence:
    def test_edition_persists_after_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "test.db")
            conn = get_connection(db_path)
            apply_migrations(conn, "migrations")
            _setup_participant(conn)

            content = json.dumps({"persist": True})
            created = ed_repo.create_edition(
                conn,
                participant_id="p1",
                edition_number=1,
                structured_content=content,
                rendered_title="Persistent",
            )
            ed_repo.update_edition_publication(
                conn, created.id, "published"
            )
            conn.close()

            conn2 = get_connection(db_path)
            found = ed_repo.get_edition_by_id(conn2, created.id)
            assert found is not None
            assert found.publication_state == "published"
            assert found.structured_content == content
            assert found.rendered_title == "Persistent"
            assert found.published_at is not None
            conn2.close()
