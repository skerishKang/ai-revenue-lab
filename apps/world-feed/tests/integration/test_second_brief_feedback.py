import pytest

from app.config import Settings, settings
from app.db import apply_migrations, get_connection
from app.domain.enums import Category, FeedbackAction
from app.domain.models import FeedbackInput
from app.repositories import brief_repository, feedback_repository
from app.service import (
    AlreadyAppliedFeedbackError,
    BriefGenerationError,
    BriefUnchangedError,
    WorldFeedService,
)
from tests.conftest import (
    event_id_map,
    event_source_ids_map,
    make_brief_provider,
    make_reader,
    make_source,
)


def _svc(provider, size=3):
    return WorldFeedService(provider=provider, settings=Settings(default_brief_size=size))


def _seed(conn):
    svc = WorldFeedService(provider=make_brief_provider([], []), settings=settings)
    svc.ingest_source_card(conn, make_source("s1", "ev-culture-001", Category.PLACE_CULTURE))
    svc.ingest_source_card(conn, make_source("s2", "ev-neigh-001", Category.NEIGHBORHOOD))
    svc.ingest_source_card(conn, make_source("s3", "ev-aaa-promo-001", Category.PROMOTIONAL_ENTERTAINMENT))
    svc.ingest_source_card(conn, make_source("s4", "ev-zzz-official-001", Category.OFFICIAL_EVENT))
    svc.resolve_canonical_events(conn)
    return event_id_map(conn), event_source_ids_map(conn)


class TestSecondBriefFeedback:
    def test_second_brief_materially_changes(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        svc = _svc(make_brief_provider(
            [mp["ev-culture-001"], mp["ev-neigh-001"], mp["ev-aaa-promo-001"]],
            [mp["ev-culture-001"], mp["ev-neigh-001"], mp["ev-zzz-official-001"]],
            source_ids_map=sm,
        ))
        svc.create_reader(
            conn,
            make_reader("r1", interests=[Category.PLACE_CULTURE, Category.NEIGHBORHOOD]),
        )
        first = svc.generate_first_brief(conn, "r1")

        feedback = FeedbackInput(
            feedback_id="f1",
            reader_id="r1",
            prior_brief_id=first.id,
            idempotency_key="idem-1",
            action=FeedbackAction.REDUCE_PROMOTIONAL_ENTERTAINMENT,
            detail="less promo",
        )
        svc.apply_feedback(conn, feedback)
        second = svc.generate_second_brief(
            conn, "r1", feedback_idempotency_key="idem-1"
        )

        assert second.id != first.id
        assert second.sequence == "second"
        assert second.status == "pending_review"
        assert set(second.selected_event_ids) != set(first.selected_event_ids)
        assert mp["ev-aaa-promo-001"] in first.selected_event_ids
        assert mp["ev-aaa-promo-001"] not in second.selected_event_ids
        assert mp["ev-zzz-official-001"] in second.selected_event_ids
        fb = feedback_repository.get_feedback_by_id(conn, "f1")
        assert fb.applied_to_brief_id == second.id
        conn.close()

    def test_failed_generation_does_not_consume_feedback(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        svc = _svc(make_brief_provider(
            [mp["ev-culture-001"], mp["ev-neigh-001"], mp["ev-aaa-promo-001"]],
            [mp["ev-culture-001"], mp["ev-neigh-001"], mp["ev-zzz-official-001"]],
            source_ids_map=sm,
        ))
        svc.create_reader(
            conn,
            make_reader("r1", interests=[Category.PLACE_CULTURE, Category.NEIGHBORHOOD]),
        )
        first = svc.generate_first_brief(conn, "r1")

        feedback = FeedbackInput(
            feedback_id="f2",
            reader_id="r1",
            prior_brief_id=first.id,
            idempotency_key="idem-2",
            action=FeedbackAction.REDUCE_PROMOTIONAL_ENTERTAINMENT,
        )
        svc.apply_feedback(conn, feedback)

        from app.ai.mock import MockProvider
        failing = _svc(MockProvider())
        with pytest.raises(BriefGenerationError):
            failing.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-2")

        fb = feedback_repository.get_feedback_by_id(conn, "f2")
        assert fb.applied_to_brief_id is None
        assert brief_repository.count_briefs(conn) == 1
        conn.close()

    def test_already_applied_feedback_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        svc = _svc(make_brief_provider(
            [mp["ev-culture-001"], mp["ev-neigh-001"], mp["ev-aaa-promo-001"]],
            [mp["ev-culture-001"], mp["ev-neigh-001"], mp["ev-zzz-official-001"]],
            source_ids_map=sm,
        ))
        svc.create_reader(
            conn,
            make_reader("r1", interests=[Category.PLACE_CULTURE, Category.NEIGHBORHOOD]),
        )
        first = svc.generate_first_brief(conn, "r1")
        feedback = FeedbackInput(
            feedback_id="f3",
            reader_id="r1",
            prior_brief_id=first.id,
            idempotency_key="idem-3",
            action=FeedbackAction.REDUCE_PROMOTIONAL_ENTERTAINMENT,
        )
        svc.apply_feedback(conn, feedback)
        svc.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-3")
        with pytest.raises(AlreadyAppliedFeedbackError):
            svc.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-3")
        conn.close()

    def test_unchanged_second_brief_rejected(self, db_path):
        from app.domain.models import ProviderResult
        from app.domain.enums import CostClass

        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc_ingest = WorldFeedService(provider=make_brief_provider([], []), settings=settings)
        svc_ingest.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
        svc_ingest.resolve_canonical_events(conn)
        mp = event_id_map(conn)
        sm = event_source_ids_map(conn)
        ev_id = mp["ev-1"]
        src_ids = sm.get(ev_id, ["s1"])

        class SamePayloadProvider:
            def __init__(self):
                self._model = "mock-v1"
            @property
            def provider(self):
                return "mock"
            @property
            def model(self):
                return self._model
            def generate_structured(self, **kwargs):
                return ProviderResult(
                    provider="mock", advertised_model=self._model,
                    cost_class=CostClass.FREE, latency_seconds=0.0, retry_count=0,
                    payload={
                        "brief_title": "same title",
                        "deck": "same deck",
                        "items": [{"event_id": ev_id, "headline": "h",
                                   "explanation": "e", "source_ids": src_ids}],
                        "uncertainty_notes": [],
                    },
                    request_id=kwargs.get("request_id"), success=True,
                )

        svc = _svc(SamePayloadProvider())
        svc.create_reader(conn, make_reader("r1"))
        first = svc.generate_first_brief(conn, "r1")

        feedback = FeedbackInput(
            feedback_id="f4", reader_id="r1", prior_brief_id=first.id,
            idempotency_key="idem-4",
            action=FeedbackAction.REDUCE_PROMOTIONAL_ENTERTAINMENT,
        )
        svc.apply_feedback(conn, feedback)
        with pytest.raises(BriefUnchangedError):
            svc.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-4")
        assert brief_repository.count_briefs(conn) == 1
        fb = feedback_repository.get_feedback_by_id(conn, "f4")
        assert fb.applied_to_brief_id is None
        conn.close()
