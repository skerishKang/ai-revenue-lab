from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import Category, FeedbackAction
from app.domain.models import FeedbackInput
from app.repositories import brief_repository, feedback_repository
from app.service import WorldFeedService
from tests.conftest import (
    event_id_map,
    make_brief_provider,
    make_reader,
    make_source,
)


def _svc(provider):
    return WorldFeedService(provider=provider, settings=settings)


def _seed(conn):
    svc = _svc(make_brief_provider([], []))
    svc.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
    svc.ingest_source_card(conn, make_source("s2", "ev-2", Category.NEIGHBORHOOD))
    svc.resolve_canonical_events(conn)
    return event_id_map(conn)


class TestIdempotency:
    def test_duplicate_first_brief_does_not_create_new_number(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp = _seed(conn)
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values())))
        svc.create_reader(conn, make_reader("r1"))
        a = svc.generate_first_brief(conn, "r1")
        b = svc.generate_first_brief(conn, "r1")
        assert a.brief_number == b.brief_number
        assert brief_repository.count_briefs(conn) == 1
        conn.close()

    def test_duplicate_feedback_applied_exactly_once(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        _seed(conn)
        svc = _svc(make_brief_provider([], []))
        svc.create_reader(conn, make_reader("r1"))
        fb1 = FeedbackInput(
            feedback_id="f1",
            reader_id="r1",
            idempotency_key="idem-x",
            action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
        )
        r1 = svc.apply_feedback(conn, fb1)
        r2 = svc.apply_feedback(conn, fb1)
        assert r1.id == r2.id
        all_fb = feedback_repository.list_feedback_for_reader(conn, "r1")
        assert len(all_fb) == 1
        conn.close()
