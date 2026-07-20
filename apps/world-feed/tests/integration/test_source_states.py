import pytest

from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import Category, SourceState
from app.repositories import canonical_event_repository
from app.service import WorldFeedService, BriefGenerationError
from tests.conftest import event_id_map, make_brief_provider, make_reader, make_source


def _svc(provider):
    return WorldFeedService(provider=provider, settings=settings)


class TestSourceStates:
    def test_withdrawn_and_superseded_never_selected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc = _svc(make_brief_provider([], []))
        svc.ingest_source_card(conn, make_source("s1", "ev-ok", Category.PLACE_CULTURE))
        svc.ingest_source_card(
            conn, make_source("s2", "ev-wd", Category.NEIGHBORHOOD,
                              source_state=SourceState.WITHDRAWN)
        )
        svc.ingest_source_card(
            conn, make_source("s3", "ev-sp", Category.OFFICIAL_EVENT,
                              source_state=SourceState.SUPERSEDED)
        )
        svc.resolve_canonical_events(conn)
        eligible = canonical_event_repository.list_eligible_events(conn)
        states = {e.status for e in eligible}
        assert SourceState.WITHDRAWN not in states
        assert SourceState.SUPERSEDED not in states
        assert any(e.status == SourceState.SINGLE_SOURCE for e in eligible)
        conn.close()

    def test_duplicate_canonical_key_occupies_one_slot(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc = _svc(make_brief_provider([], []))
        svc.ingest_source_card(
            conn, make_source("s1", "ev-dup", Category.OFFICIAL_EVENT,
                              source_state=SourceState.SINGLE_SOURCE)
        )
        svc.ingest_source_card(
            conn, make_source("s2", "ev-dup", Category.OFFICIAL_EVENT,
                              source_state=SourceState.CONFLICTING)
        )
        count = svc.resolve_canonical_events(conn)
        assert count == 1
        events = canonical_event_repository.list_events(conn)
        assert len(events) == 1
        assert events[0].status == SourceState.CONFLICTING.value
        assert set(events[0].source_ids) == {"s1", "s2"}
        conn.close()

    def test_conflicting_event_requires_uncertainty_note(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc = _svc(make_brief_provider([], []))
        svc.ingest_source_card(
            conn, make_source("s1", "ev-conf", Category.OFFICIAL_EVENT,
                              source_state=SourceState.CONFLICTING)
        )
        svc.resolve_canonical_events(conn)
        mp = event_id_map(conn)
        conf_id = mp["ev-conf"]
        svc.create_reader(conn, make_reader("r1"))

        # Missing uncertainty note -> validation fails, no brief.
        bad = make_brief_provider([conf_id], [conf_id])
        bad._task_payloads = {
            "generate_first_microbrief": {
                "brief_title": "t", "deck": "d",
                "items": [{"event_id": conf_id, "headline": "h",
                           "explanation": "x", "source_ids": ["s1"]}],
                "uncertainty_notes": [], "feedback_note": None,
            }
        }
        svc_bad = _svc(bad)
        with pytest.raises(BriefGenerationError):
            svc_bad.generate_first_brief(conn, "r1")

        # With uncertainty note -> success.
        good = make_brief_provider([conf_id], [conf_id])
        good._task_payloads = {
            "generate_first_microbrief": {
                "brief_title": "t", "deck": "d",
                "items": [{"event_id": conf_id, "headline": "h",
                           "explanation": "x", "source_ids": ["s1"]}],
                "uncertainty_notes": [conf_id], "feedback_note": None,
            }
        }
        svc_good = _svc(good)
        brief = svc_good.generate_first_brief(conn, "r1")
        assert brief.status == "pending_review"
        conn.close()
