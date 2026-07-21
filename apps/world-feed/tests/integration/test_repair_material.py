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


class TestMaterialChange:
    def test_unchanged_second_brief_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc_i = _svc(make_brief_provider([], []))
        svc_i.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
        svc_i.resolve_canonical_events(conn)
        mp = event_id_map(conn)
        sm = event_source_ids_map(conn)
        ev_id = mp["ev-1"]
        src_ids = sm.get(ev_id, ["s1"])

        p = _make_custom_provider(ev_id, src_ids, title="same")
        svc = _svc(p)
        svc.create_reader(conn, make_reader("r1"))
        first = svc.generate_first_brief(conn, "r1")
        fb = FeedbackInput(
            feedback_id="fb-uc", reader_id="r1", prior_brief_id=first.id,
            idempotency_key="idem-uc",
            action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
        )
        svc.apply_feedback(conn, fb)
        with pytest.raises(BriefUnchangedError):
            svc.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-uc")
        assert brief_repository.count_briefs(conn) == 1
        fb_rec = feedback_repository.get_feedback_by_id(conn, "fb-uc")
        assert fb_rec.applied_to_brief_id is None
        conn.close()

    def test_material_change_accepted(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        svc = _svc(make_brief_provider(
            [mp["ev-1"]], [mp["ev-2"]], source_ids_map=sm,
            first_title="First Edition", second_title="Second Edition",
        ))
        svc.create_reader(conn, make_reader("r1"))
        first = svc.generate_first_brief(conn, "r1")
        fb = FeedbackInput(
            feedback_id="fb-mc", reader_id="r1", prior_brief_id=first.id,
            idempotency_key="idem-mc",
            action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
        )
        svc.apply_feedback(conn, fb)
        second = svc.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-mc")
        assert second.id != first.id
        assert second.title == "Second Edition"
        conn.close()
