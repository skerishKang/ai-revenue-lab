import pytest

from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import Category
from app.repositories import brief_repository
from app.repositories.common import InactiveReaderError
from app.service import WorldFeedService
from tests.conftest import (
    event_id_map,
    event_source_ids_map,
    make_brief_provider,
    make_reader,
    make_source,
)


def _svc(provider):
    return WorldFeedService(provider=provider, settings=settings)


def _seed_four(conn, svc):
    svc.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
    svc.ingest_source_card(conn, make_source("s2", "ev-2", Category.NEIGHBORHOOD))
    svc.ingest_source_card(conn, make_source("s3", "ev-3", Category.OFFICIAL_EVENT))
    svc.ingest_source_card(conn, make_source("s4", "ev-4", Category.PLACE_CULTURE))
    svc.resolve_canonical_events(conn)
    return event_id_map(conn), event_source_ids_map(conn)


class TestReaderOwnership:
    def test_inactive_reader_cannot_get_brief(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed_four(conn, _svc(make_brief_provider([], [])))
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm))
        svc.create_reader(conn, make_reader("r-inactive", active=False))
        with pytest.raises(InactiveReaderError):
            svc.generate_first_brief(conn, "r-inactive")
        conn.close()

    def test_briefs_are_reader_scoped(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed_four(conn, _svc(make_brief_provider([], [])))
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm))
        svc.create_reader(conn, make_reader("r-a"))
        svc.create_reader(conn, make_reader("r-b"))
        svc.generate_first_brief(conn, "r-a")
        a_briefs = brief_repository.list_briefs_for_reader(conn, "r-a")
        b_briefs = brief_repository.list_briefs_for_reader(conn, "r-b")
        assert len(a_briefs) == 1
        assert len(b_briefs) == 0
        assert a_briefs[0].reader_id == "r-a"
        conn.close()
