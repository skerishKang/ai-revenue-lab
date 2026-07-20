"""Integration tests for source repository."""

import pytest

from app.db import apply_migrations, get_connection
from app.source_repository import (
    create_source,
    get_source_by_id,
    get_sources_by_destination,
)


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


class TestSourceRepository:
    def test_create_and_get(self, conn):
        s = create_source(
            conn,
            source_url="https://example.com",
            publisher="테스트",
            source_type="tourism_authority",
            destination="부산",
            category="overview",
        )
        assert s.id.startswith("src_")
        fetched = get_source_by_id(conn, s.id)
        assert fetched is not None
        assert fetched.publisher == "테스트"

    def test_get_by_destination(self, conn):
        create_source(
            conn,
            source_url="https://a.com",
            publisher="A",
            source_type="gov",
            destination="부산",
            category="market",
        )
        create_source(
            conn,
            source_url="https://b.com",
            publisher="B",
            source_type="gov",
            destination="서울",
            category="market",
        )
        busan_sources = get_sources_by_destination(conn, "부산")
        assert len(busan_sources) == 1

    def test_claims_stored_as_json(self, conn):
        s = create_source(
            conn,
            source_url="https://c.com",
            publisher="C",
            source_type="gov",
            destination="부산",
            category="overview",
            claims=["claim1", "claim2"],
        )
        fetched = get_source_by_id(conn, s.id)
        assert fetched is not None
        assert fetched.claims == ["claim1", "claim2"]
