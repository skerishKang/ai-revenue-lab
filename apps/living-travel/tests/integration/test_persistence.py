"""Integration tests for Living Travel file-backed persistence."""

import json
import os
from pathlib import Path

import pytest

from app.db import apply_migrations, get_connection
from app.edition_repository import create_edition, get_edition_by_id, update_edition_content
from app.traveler_repository import create_traveler, get_traveler_by_id


@pytest.fixture
def file_db(tmp_path):
    return str(tmp_path / "persist_test.db")


class TestFileBackedPersistence:
    def test_traveler_persists_across_connections(self, file_db):
        apply_migrations(file_db)
        conn1 = get_connection(file_db)
        t = create_traveler(conn1, display_name="지속", destination="부산")
        tid = t.id
        conn1.close()

        conn2 = get_connection(file_db)
        fetched = get_traveler_by_id(conn2, tid)
        assert fetched is not None
        assert fetched.display_name == "지속"
        conn2.close()

    def test_edition_content_persists(self, file_db):
        apply_migrations(file_db)
        conn1 = get_connection(file_db)
        t = create_traveler(conn1, display_name="테스트", destination="부산")
        ed = create_edition(conn1, traveler_id=t.id, edition_number=1)
        content = {"publication_title": "지속 테스트", "sections": []}
        update_edition_content(conn1, ed.id, content)
        conn1.close()

        conn2 = get_connection(file_db)
        fetched = get_edition_by_id(conn2, ed.id)
        assert fetched is not None
        assert fetched.structured_content["publication_title"] == "지속 테스트"
        conn2.close()

    def test_db_file_exists_on_disk(self, file_db):
        apply_migrations(file_db)
        assert os.path.exists(file_db)
        size = os.path.getsize(file_db)
        assert size > 0
