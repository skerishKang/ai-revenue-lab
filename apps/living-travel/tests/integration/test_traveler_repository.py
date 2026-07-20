"""Integration tests for traveler repository."""

import pytest

from app.db import apply_migrations, get_connection
from app.traveler_repository import (
    create_traveler,
    delete_traveler,
    get_all_travelers,
    get_traveler_by_id,
)


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


class TestTravelerRepository:
    def test_create_and_get(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        assert t.id.startswith("trav_")
        assert t.display_name == "테스트"
        assert t.destination == "부산"
        fetched = get_traveler_by_id(conn, t.id)
        assert fetched is not None
        assert fetched.id == t.id

    def test_get_nonexistent(self, conn):
        assert get_traveler_by_id(conn, "nonexistent") is None

    def test_list_travelers(self, conn):
        create_traveler(conn, display_name="A", destination="부산")
        create_traveler(conn, display_name="B", destination="서울")
        all_t = get_all_travelers(conn)
        assert len(all_t) == 2

    def test_delete_traveler(self, conn):
        t = create_traveler(conn, display_name="삭제", destination="부산")
        assert delete_traveler(conn, t.id) is True
        assert get_traveler_by_id(conn, t.id) is None
        assert delete_traveler(conn, t.id) is False

    def test_delete_nonexistent(self, conn):
        assert delete_traveler(conn, "nonexistent") is False

    def test_interests_and_exclusions(self, conn):
        t = create_traveler(
            conn,
            display_name="관심사",
            destination="부산",
            interests=["food", "walk"],
            exclusions=["nightlife"],
        )
        fetched = get_traveler_by_id(conn, t.id)
        assert fetched is not None
        assert fetched.interests == ["food", "walk"]
        assert fetched.exclusions == ["nightlife"]
