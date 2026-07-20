from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import BriefSequence, BriefStatus
from app.repositories import brief_repository
from app.service import WorldFeedService
from tests.conftest import (
    event_id_map,
    make_brief_provider,
    make_reader,
    make_source,
)
from app.domain.enums import Category


def _svc(provider):
    return WorldFeedService(provider=provider, settings=settings)


def _seed(conn, svc):
    svc.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
    svc.ingest_source_card(conn, make_source("s2", "ev-2", Category.NEIGHBORHOOD))
    svc.ingest_source_card(conn, make_source("s3", "ev-3", Category.OFFICIAL_EVENT))
    svc.ingest_source_card(conn, make_source("s4", "ev-4", Category.PLACE_CULTURE))
    svc.resolve_canonical_events(conn)
    return event_id_map(conn)


class TestFirstBrief:
    def test_first_brief_is_pending_review(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp = _seed(conn, _svc(make_brief_provider([], [])))
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values())))
        svc.create_reader(conn, make_reader("r1"))
        brief = svc.generate_first_brief(conn, "r1")
        assert brief.sequence == BriefSequence.FIRST.value
        assert brief.status == BriefStatus.PENDING_REVIEW.value
        assert brief.feedback_id is None
        # No automatic publication.
        assert brief.status != "published"
        conn.close()

    def test_first_brief_is_deterministic_and_idempotent(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp = _seed(conn, _svc(make_brief_provider([], [])))
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values())))
        svc.create_reader(conn, make_reader("r1"))
        first = svc.generate_first_brief(conn, "r1")
        second_call = svc.generate_first_brief(conn, "r1")
        # Same brief number -> no duplicate brief created.
        assert first.brief_number == second_call.brief_number
        assert brief_repository.count_briefs(conn) == 1
        conn.close()

    def test_first_brief_cites_only_selected_events(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp = _seed(conn, _svc(make_brief_provider([], [])))
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values())))
        svc.create_reader(conn, make_reader("r1"))
        brief = svc.generate_first_brief(conn, "r1")
        assert set(brief.selected_event_ids) == set(mp.values())
        conn.close()
