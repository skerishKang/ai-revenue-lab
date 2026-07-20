"""Integration tests for input repository."""

import pytest

from app.db import apply_migrations, get_connection
from app.input_repository import create_input, get_input_by_id, get_inputs_by_traveler
from app.traveler_repository import create_traveler


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


class TestInputRepository:
    def test_create_and_get(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        inp = create_input(
            conn,
            traveler_id=t.id,
            raw_text="부산에서 2박 여행",
            destination="부산",
        )
        assert inp.id.startswith("in_")
        assert inp.sequence_number == 1
        fetched = get_input_by_id(conn, inp.id)
        assert fetched is not None

    def test_sequence_numbering(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        i1 = create_input(conn, traveler_id=t.id, raw_text="첫 번째", destination="부산")
        i2 = create_input(conn, traveler_id=t.id, raw_text="두 번째", destination="부산")
        i3 = create_input(conn, traveler_id=t.id, raw_text="세 번째", destination="부산")
        assert i1.sequence_number == 1
        assert i2.sequence_number == 2
        assert i3.sequence_number == 3

    def test_list_by_traveler(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        create_input(conn, traveler_id=t.id, raw_text="A", destination="부산")
        create_input(conn, traveler_id=t.id, raw_text="B", destination="부산")
        inputs = get_inputs_by_traveler(conn, t.id)
        assert len(inputs) == 2
        assert inputs[0].raw_text == "A"
        assert inputs[1].raw_text == "B"
