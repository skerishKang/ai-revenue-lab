"""Integration tests for edition repository."""

import pytest

from app.db import apply_migrations, get_connection
from app.domain.enums import EditionGenerationStatus, PublicationState
from app.edition_repository import (
    create_edition,
    get_edition_by_id,
    get_editions_by_traveler,
    update_edition_content,
    update_edition_generation_status,
    update_edition_publication,
)
from app.traveler_repository import create_traveler


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


class TestEditionRepository:
    def test_create_and_get(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        assert ed.id.startswith("ed_")
        assert ed.generation_status == EditionGenerationStatus.input_received
        assert ed.publication_state == PublicationState.pending

    def test_update_generation_status(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        update_edition_generation_status(conn, ed.id, EditionGenerationStatus.pending_review)
        fetched = get_edition_by_id(conn, ed.id)
        assert fetched is not None
        assert fetched.generation_status == EditionGenerationStatus.pending_review

    def test_update_content(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        content = {"publication_title": "테스트", "sections": []}
        update_edition_content(conn, ed.id, content)
        fetched = get_edition_by_id(conn, ed.id)
        assert fetched is not None
        assert fetched.structured_content["publication_title"] == "테스트"

    def test_update_publication(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        ed = create_edition(conn, traveler_id=t.id, edition_number=1)
        update_edition_publication(conn, ed.id, PublicationState.published)
        fetched = get_edition_by_id(conn, ed.id)
        assert fetched is not None
        assert fetched.publication_state == PublicationState.published

    def test_prior_edition_link(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        ed1 = create_edition(conn, traveler_id=t.id, edition_number=1)
        ed2 = create_edition(
            conn, traveler_id=t.id, edition_number=2, prior_edition_id=ed1.id
        )
        fetched = get_edition_by_id(conn, ed2.id)
        assert fetched is not None
        assert fetched.prior_edition_id == ed1.id

    def test_list_by_traveler(self, conn):
        t = create_traveler(conn, display_name="테스트", destination="부산")
        create_edition(conn, traveler_id=t.id, edition_number=1)
        create_edition(conn, traveler_id=t.id, edition_number=2)
        editions = get_editions_by_traveler(conn, t.id)
        assert len(editions) == 2
        assert editions[0].edition_number == 1
        assert editions[1].edition_number == 2
