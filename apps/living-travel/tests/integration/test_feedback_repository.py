"""Integration tests for feedback repository."""

import pytest

from app.db import apply_migrations, get_connection
from app.edition_repository import create_edition
from app.feedback_repository import (
    create_feedback,
    get_feedback_by_edition,
    get_feedback_by_id,
    get_unapplied_feedback_for_traveler,
    mark_feedback_applied,
)
from app.traveler_repository import create_traveler


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


class TestFeedbackRepository:
    def test_create_and_get(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        fb = create_feedback(
            conn,
            traveler_id=t.id,
            edition_id=ed.id,
            direction_choices=["quieter_places"],
            free_text="조용한 곳",
        )
        assert fb.id.startswith("fb_")
        fetched = get_feedback_by_id(conn, fb.id)
        assert fetched is not None
        assert fetched.direction_choices == ["quieter_places"]

    def test_get_by_edition(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        create_feedback(conn, traveler_id=t.id, edition_id=ed.id)
        create_feedback(conn, traveler_id=t.id, edition_id=ed.id)
        fbs = get_feedback_by_edition(conn, ed.id)
        assert len(fbs) == 2

    def test_unapplied_feedback(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        fb = create_feedback(conn, traveler_id=t.id, edition_id=ed.id)
        unapplied = get_unapplied_feedback_for_traveler(conn, t.id)
        assert len(unapplied) == 1
        mark_feedback_applied(conn, fb.id)
        unapplied = get_unapplied_feedback_for_traveler(conn, t.id)
        assert len(unapplied) == 0

    def test_mark_applied(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        fb = create_feedback(conn, traveler_id=t.id, edition_id=ed.id)
        assert mark_feedback_applied(conn, fb.id) is True
        fetched = get_feedback_by_id(conn, fb.id)
        assert fetched is not None
        assert fetched.applied_to_next_edition is True
