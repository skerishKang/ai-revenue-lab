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
        svc.apply_feedback(conn, fb)
        with pytest.raises(MismatchedPriorBriefError, match="does not exist"):
            svc.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-np")
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


class TestSourceGrounding:
    def test_invented_source_id_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc_i = _svc(make_brief_provider([], []))
        svc_i.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
        svc_i.resolve_canonical_events(conn)
        mp = event_id_map(conn)
        sm = event_source_ids_map(conn)
        ev_id = mp["ev-1"]

        p = _make_custom_provider(ev_id, ["invented-src"])
        svc = _svc(p)
        svc.create_reader(conn, make_reader("r1"))
        with pytest.raises(BriefGenerationError, match="not part of"):
            svc.generate_first_brief(conn, "r1")
        conn.close()

    def test_source_id_from_another_event_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc_i = _svc(make_brief_provider([], []))
        svc_i.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
        svc_i.ingest_source_card(conn, make_source("s2", "ev-2", Category.NEIGHBORHOOD))
        svc_i.resolve_canonical_events(conn)
        mp = event_id_map(conn)
        sm = event_source_ids_map(conn)
        ev_id = mp["ev-1"]

        p = _make_custom_provider(ev_id, ["s2"])
        svc = _svc(p)
        svc.create_reader(conn, make_reader("r1"))
        with pytest.raises(BriefGenerationError, match="not part of"):
            svc.generate_first_brief(conn, "r1")
        conn.close()

    def test_withdrawn_source_citation_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc_i = _svc(make_brief_provider([], []))
        svc_i.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
        svc_i.resolve_canonical_events(conn)
        mp = event_id_map(conn)
        sm = event_source_ids_map(conn)
        ev_id = mp["ev-1"]
        assert sm.get(ev_id) == ["s1"]

        conn.execute("UPDATE sources SET source_state = 'withdrawn' WHERE source_id = 's1'")

        p = _make_custom_provider(ev_id, ["s1"])
        svc = _svc(p)
        svc.create_reader(conn, make_reader("r1"))
        with pytest.raises(BriefGenerationError, match="withdrawn"):
            svc.generate_first_brief(conn, "r1")
        conn.close()


class TestProviderAttribution:
    def test_actual_provider_model_cost_recorded(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc_i = _svc(make_brief_provider([], []))
        svc_i.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
        svc_i.resolve_canonical_events(conn)
        mp = event_id_map(conn)
        sm = event_source_ids_map(conn)
        ev_id = mp["ev-1"]
        src_ids = sm.get(ev_id, ["s1"])

        p = _make_custom_provider(ev_id, src_ids, provider_name="external-provider",
                                  model="external-model-v2", cost_class=CostClass.PAID)
        svc = _svc(p)
        svc.create_reader(conn, make_reader("r1"))
        svc.generate_first_brief(conn, "r1")
        runs = generation_run_repository.list_runs_by_task_type(
            conn, "generate_first_microbrief"
        )
        assert len(runs) == 1
        assert runs[0].provider == "external-provider"
        assert runs[0].advertised_model == "external-model-v2"
        assert runs[0].cost_class == "paid"
        conn.close()


class TestFailClosed:
    def test_unsupported_provider_raises(self):
        from app.factory import create_app, UnsupportedProviderError
        bad_settings = Settings(ai_provider="openai", ai_model="gpt-4")
        with pytest.raises(UnsupportedProviderError):
            create_app(db_path="/tmp/test-fail.db", app_settings=bad_settings)

    def test_health_reports_actual_identity(self):
        from app.factory import create_app
        from fastapi.testclient import TestClient
        import tempfile

        p = tempfile.mktemp(suffix=".db")
        app = create_app(db_path=p, provider=_make_custom_provider("x", ["s"], model="custom-v3", provider_name="custom"))
        with TestClient(app) as c:
            h = c.get("/health").json()
            assert h["ai_provider"] == "custom"
            assert h["ai_model"] == "custom-v3"


class TestTokenNormalization:
    def test_missing_total_normalized(self, db_path):
        from tests.conftest import brief_payload
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        payload = brief_payload(list(mp.values()), title="T", source_ids_map=sm)
        from app.ai.mock import MockProvider
        provider = MockProvider(
            model="mock-v1",
            responses=[{
                "kind": "payload", "payload": payload,
                "usage": {"input_tokens": 8, "output_tokens": 4},
            }],
        )
        svc = _svc(provider)
        svc.create_reader(conn, make_reader("r1"))
        svc.generate_first_brief(conn, "r1")
        runs = generation_run_repository.list_runs_by_task_type(
            conn, "generate_first_microbrief"
        )
        assert runs[0].total_tokens == 12
        conn.close()


class TestEvidenceIntegrity:
    def test_evidence_nonexistent_reader_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc = _svc(make_brief_provider([], []))
        with pytest.raises(EvidenceValidationError, match="reader not found"):
            svc.record_pilot_evidence(conn, PilotEvidenceInput(
                reader_id="ghost", brief_id="x",
                evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
                anonymous_token="anon-g",
            ))
        conn.close()

    def test_evidence_ownership_mismatch_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc_i = _svc(make_brief_provider([], []))
        svc_i.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
        svc_i.resolve_canonical_events(conn)
        mp = event_id_map(conn)
        sm = event_source_ids_map(conn)
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm))
        svc.create_reader(conn, make_reader("r1"))
        svc.create_reader(conn, make_reader("r2"))
        brief = svc.generate_first_brief(conn, "r1")
        with pytest.raises(EvidenceValidationError, match="does not belong"):
            svc.record_pilot_evidence(conn, PilotEvidenceInput(
                reader_id="r2", brief_id=brief.id,
                evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
                anonymous_token="anon-m",
            ))
        conn.close()

    def test_sensitive_detail_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc_i = _svc(make_brief_provider([], []))
        svc_i.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
        svc_i.resolve_canonical_events(conn)
        mp = event_id_map(conn)
        sm = event_source_ids_map(conn)
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm))
        svc.create_reader(conn, make_reader("r1"))
        brief = svc.generate_first_brief(conn, "r1")
        rec = svc.record_pilot_evidence(conn, PilotEvidenceInput(
            reader_id="r1", brief_id=brief.id,
            evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
            anonymous_token="anon-s",
            detail="email me at user@secret.com or +82-10-1234-5678",
        ))
        assert "user@secret.com" not in rec.detail
        assert "+82-10-1234-5678" not in rec.detail
        assert "[redacted]" in rec.detail
        conn.close()
