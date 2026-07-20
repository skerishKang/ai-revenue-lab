from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import Category
from app.service import WorldFeedService
from tests.conftest import (
    event_id_map,
    make_brief_provider,
    make_reader,
    make_source,
)


def test_source_persists_across_reopen(db_path):
    conn = get_connection(db_path)
    apply_migrations(conn, "migrations")
    svc = WorldFeedService(provider=make_brief_provider([], []), settings=settings)
    svc.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
    conn.close()

    reopened = get_connection(db_path)
    try:
        row = reopened.execute(
            "SELECT source_id FROM sources WHERE source_id='s1'"
        ).fetchone()
        assert row is not None
    finally:
        reopened.close()


def test_brief_persists_across_reopen(db_path):
    conn = get_connection(db_path)
    apply_migrations(conn, "migrations")
    svc = WorldFeedService(provider=make_brief_provider([], []), settings=settings)
    svc.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
    svc.resolve_canonical_events(conn)
    mp = event_id_map(conn)
    provider = make_brief_provider([mp["ev-1"]], [mp["ev-1"]])
    svc = WorldFeedService(provider=provider, settings=settings)
    svc.create_reader(conn, make_reader("r1"))
    brief = svc.generate_first_brief(conn, "r1")
    conn.close()

    reopened = get_connection(db_path)
    try:
        row = reopened.execute(
            "SELECT brief_number, status FROM briefs WHERE id=?", (brief.id,)
        ).fetchone()
        assert row is not None
        assert row["status"] == "pending_review"
    finally:
        reopened.close()
