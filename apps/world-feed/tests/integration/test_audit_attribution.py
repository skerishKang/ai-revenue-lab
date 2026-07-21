"""Audit: attribution, token inconsistency, grounding edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.mock import MockProvider
from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import Category, CostClass, FeedbackAction, ProviderErrorCategory
from app.domain.models import FeedbackInput, ProviderResult
from app.repositories import generation_run_repository
from app.service import BriefGenerationError, BriefUnchangedError, WorldFeedService
from tests.conftest import (
    brief_payload,
    event_id_map,
    event_source_ids_map,
    make_brief_provider,
    make_reader,
    make_source,
)

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

def _svc(provider):
    return WorldFeedService(provider=provider, settings=settings)

def _seed(conn):
    svc = _svc(make_brief_provider([], []))
    svc.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
    svc.ingest_source_card(conn, make_source("s2", "ev-2", Category.NEIGHBORHOOD))
    svc.resolve_canonical_events(conn)
    return event_id_map(conn), event_source_ids_map(conn)

def _custom(ev_id, src_ids, *, title="t", provider_name="mock", model="m1"):
    class _P:
        @property
        def provider(self):
            return provider_name

        @property
        def model(self):
            return model

        def generate_structured(self, **kwargs):
            return ProviderResult(
                provider=provider_name,
                advertised_model=model,
                cost_class=CostClass.FREE,
                latency_seconds=0.01,
                payload={
                    "brief_title": title,
                    "deck": "d",
                    "items": [
                        {
                            "event_id": ev_id,
                            "headline": "h",
                            "explanation": "e",
                            "source_ids": src_ids,
                        }
                    ],
                    "uncertainty_notes": [],
                },
                request_id=kwargs.get("request_id"),
                success=True,
            )

    return _P()

class TestFailedRunAttribution:
    def test_failed_provider_records_actual_identity(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, str(MIGRATIONS))
        _seed(conn)
        provider = MockProvider(
            model="ext-model",
            responses=[{
                "kind": "error",
                "category": ProviderErrorCategory.PROVIDER_ERROR,
                "message": "boom",
                "usage": {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1},
            }],
        )
        provider._provider_name = "external-provider"
        svc = _svc(provider)
        svc.create_reader(conn, make_reader("r1"))
        with pytest.raises(BriefGenerationError):
            svc.generate_first_brief(conn, "r1")
        run = generation_run_repository.list_runs_by_task_type(
            conn, "generate_first_microbrief"
        )[0]
        assert run.success == 0
        assert run.provider == "external-provider"
        assert run.advertised_model == "ext-model"
        conn.close()

class TestTokenInconsistency:
    def test_inconsistent_total_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, str(MIGRATIONS))
        mp, sm = _seed(conn)
        payload = brief_payload(list(mp.values()), title="T", source_ids_map=sm)
        provider = MockProvider(
            model="mock-v1",
            responses=[
                {
                    "kind": "payload",
                    "payload": payload,
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 99,
                    },
                }
            ],
        )
        svc = _svc(provider)
        svc.create_reader(conn, make_reader("r1"))
        with pytest.raises(BriefGenerationError, match="inconsistent usage"):
            svc.generate_first_brief(conn, "r1")
        runs = generation_run_repository.list_runs_by_task_type(
            conn, "generate_first_microbrief"
        )
        assert runs[0].success == 0
        assert runs[0].provider != "pending"
        conn.close()

class TestSourceGroundingExtras:
    def test_superseded_source_citation_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, str(MIGRATIONS))
        svc_i = _svc(make_brief_provider([], []))
        svc_i.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
        svc_i.resolve_canonical_events(conn)
        mp = event_id_map(conn)
        svc = _svc(_custom(mp["ev-1"], ["s1"]))
        conn.execute(
            "UPDATE sources SET source_state = 'superseded' WHERE source_id = 's1'"
        )
        svc.create_reader(conn, make_reader("r1"))
        with pytest.raises(BriefGenerationError, match="superseded"):
            svc.generate_first_brief(conn, "r1")
        conn.close()

    def test_orphan_source_id_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, str(MIGRATIONS))
        svc_i = _svc(make_brief_provider([], []))
        svc_i.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
        svc_i.resolve_canonical_events(conn)
        mp = event_id_map(conn)
        ev_id = mp["ev-1"]
        conn.execute(
            "UPDATE canonical_events SET source_ids = ? WHERE id = ?",
            ('["s1","ghost-src"]', ev_id),
        )
        svc = _svc(_custom(ev_id, ["ghost-src"]))
        svc.create_reader(conn, make_reader("r1"))
        with pytest.raises(BriefGenerationError, match="does not exist"):
            svc.generate_first_brief(conn, "r1")
        conn.close()

class TestUnchangedAttribution:
    def test_unchanged_second_brief_records_identity(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, str(MIGRATIONS))
        svc_i = _svc(make_brief_provider([], []))
        svc_i.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
        svc_i.resolve_canonical_events(conn)
        mp = event_id_map(conn)
        sm = event_source_ids_map(conn)
        ev_id = mp["ev-1"]
        p = _custom(
            ev_id, sm[ev_id], title="same",
            provider_name="custom-p", model="custom-m",
        )
        svc = _svc(p)
        svc.create_reader(conn, make_reader("r1"))
        first = svc.generate_first_brief(conn, "r1")
        svc.apply_feedback(
            conn,
            FeedbackInput(
                feedback_id="fb-uc2",
                reader_id="r1",
                prior_brief_id=first.id,
                idempotency_key="idem-uc2",
                action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
            ),
        )
        with pytest.raises(BriefUnchangedError):
            svc.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-uc2")
        runs = generation_run_repository.list_runs_by_task_type(
            conn, "generate_second_microbrief"
        )
        assert runs[0].provider == "custom-p"
        assert runs[0].advertised_model == "custom-m"
        assert runs[0].validation_status == "unchanged"
        conn.close()
