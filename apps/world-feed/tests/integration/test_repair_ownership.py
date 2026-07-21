"""Comprehensive CTO-review repair regression tests for Issue #36."""

import pytest

from app.config import Settings, settings
from app.db import apply_migrations, get_connection
from app.domain.enums import (
    Category,
    CostClass,
    FeedbackAction,
    PilotEvidenceType,
)
from app.domain.models import (
    FeedbackInput,
    PilotEvidenceInput,
    ProviderResult,
)
from app.repositories import (
    brief_repository,
    feedback_repository,
    generation_run_repository,
)
from app.service import (
    AlreadyAppliedFeedbackError,
    BriefGenerationError,
    BriefUnchangedError,
    EvidenceValidationError,
    FirstBriefMissingError,
    ForeignFeedbackError,
    MismatchedPriorBriefError,
    WorldFeedService,
)
from tests.conftest import (
    event_id_map,
    event_source_ids_map,
    make_brief_provider,
    make_reader,
    make_source,
)


def _svc(provider, **overrides):
    kw = {"provider": provider, "settings": settings}
    kw.update(overrides)
    return WorldFeedService(**kw)


def _seed(conn):
    svc = _svc(make_brief_provider([], []))
    svc.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
    svc.ingest_source_card(conn, make_source("s2", "ev-2", Category.NEIGHBORHOOD))
    svc.resolve_canonical_events(conn)
    return event_id_map(conn), event_source_ids_map(conn)


def _make_custom_provider(ev_id, src_ids, *, provider_name="mock", model="mock-v1",
                          cost_class=CostClass.FREE, title="t", latency=0.0,
                          extra_items=None):
    items = [{"event_id": ev_id, "headline": "h", "explanation": "e",
              "source_ids": src_ids}]
    if extra_items:
        items.extend(extra_items)

    class _P:
        def __init__(self):
            self._model = model
        @property
        def provider(self):
            return provider_name
        @property
        def model(self):
            return self._model
        def generate_structured(self, **kwargs):
            return ProviderResult(
                provider=provider_name, advertised_model=model,
                cost_class=cost_class, latency_seconds=latency, retry_count=0,
                payload={"brief_title": title, "deck": "d", "items": items,
                         "uncertainty_notes": []},
                request_id=kwargs.get("request_id"), success=True,
            )
    return _P()


class TestFeedbackOwnership:
    def test_foreign_reader_feedback_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm))
        svc.create_reader(conn, make_reader("r-a"))
        svc.create_reader(conn, make_reader("r-b"))
        svc.generate_first_brief(conn, "r-a")
        fb = FeedbackInput(
            feedback_id="fb-a", reader_id="r-a", idempotency_key="idem-fa",
            action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
        )
        svc.apply_feedback(conn, fb)
        with pytest.raises(ForeignFeedbackError):
            svc.generate_second_brief(conn, "r-b", feedback_idempotency_key="idem-fa")
        conn.close()

    def test_nonexistent_prior_brief_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm))
        svc.create_reader(conn, make_reader("r1"))
        svc.generate_first_brief(conn, "r1")
        fb = FeedbackInput(
            feedback_id="fb-np", reader_id="r1", idempotency_key="idem-np",
            prior_brief_id="nonexistent-brief-id",
            action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
        )
        with pytest.raises(MismatchedPriorBriefError, match="does not exist"):
            svc.apply_feedback(conn, fb)
        conn.close()

    def test_mismatched_prior_brief_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm))
        svc.create_reader(conn, make_reader("r-a"))
        svc.create_reader(conn, make_reader("r-b"))
        svc.generate_first_brief(conn, "r-a")
        svc.generate_first_brief(conn, "r-b")
        a_briefs = brief_repository.list_briefs_for_reader(conn, "r-a")
        a_first = [b for b in a_briefs if b.sequence == "first"][0]
        fb = FeedbackInput(
            feedback_id="fb-mm", reader_id="r-a", idempotency_key="idem-mm",
            prior_brief_id=a_first.id,
            action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
        )
        svc.apply_feedback(conn, fb)
        with pytest.raises(ForeignFeedbackError):
            svc.generate_second_brief(conn, "r-b", feedback_idempotency_key="idem-mm")
        conn.close()

    def test_second_brief_before_first_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm))
        svc.create_reader(conn, make_reader("r1"))
        fb = FeedbackInput(
            feedback_id="fb-ns", reader_id="r1", idempotency_key="idem-ns",
            action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
        )
        svc.apply_feedback(conn, fb)
        with pytest.raises(FirstBriefMissingError):
            svc.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-ns")
        conn.close()

    def test_already_applied_feedback_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        svc = _svc(make_brief_provider(
            [mp["ev-1"]], [mp["ev-2"]], source_ids_map=sm,
            first_title="First", second_title="Second",
        ))
        svc.create_reader(conn, make_reader("r1"))
        first = svc.generate_first_brief(conn, "r1")
        fb = FeedbackInput(
            feedback_id="fb-aa", reader_id="r1", prior_brief_id=first.id,
            idempotency_key="idem-aa",
            action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
        )
        svc.apply_feedback(conn, fb)
        svc.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-aa")
        with pytest.raises(AlreadyAppliedFeedbackError):
            svc.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-aa")
        conn.close()
