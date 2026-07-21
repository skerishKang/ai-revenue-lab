"""Provider attribution, fail-closed, token, and evidence integrity repairs."""

import tempfile

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.db import apply_migrations, get_connection
from app.domain.enums import Category, CostClass, PilotEvidenceType
from app.domain.models import PilotEvidenceInput, ProviderResult
from app.factory import UnsupportedProviderError, create_app
from app.repositories import generation_run_repository
from app.service import EvidenceValidationError, WorldFeedService
from tests.conftest import (
    brief_payload,
    event_id_map,
    event_source_ids_map,
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
    return event_id_map(conn), event_source_ids_map(conn)


def _custom(ev_id, src_ids, *, provider_name="mock", model="mock-v1",
            cost_class=CostClass.FREE, title="t"):
    class _P:
        @property
        def provider(self):
            return provider_name

        @property
        def model(self):
            return model

        def generate_structured(self, **kwargs):
            return ProviderResult(
                provider=provider_name, advertised_model=model,
                cost_class=cost_class, latency_seconds=0.0, retry_count=0,
                payload={
                    "brief_title": title, "deck": "d",
                    "items": [{
                        "event_id": ev_id, "headline": "h",
                        "explanation": "e", "source_ids": src_ids,
                    }],
                    "uncertainty_notes": [],
                },
                request_id=kwargs.get("request_id"), success=True,
            )

    return _P()


class TestProviderAttribution:
    def test_actual_provider_model_cost_recorded(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc_i = _svc(make_brief_provider([], []))
        svc_i.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
        svc_i.resolve_canonical_events(conn)
        mp, sm = event_id_map(conn), event_source_ids_map(conn)
        ev_id = mp["ev-1"]
        p = _custom(ev_id, sm.get(ev_id, ["s1"]), provider_name="external-provider",
                    model="external-model-v2", cost_class=CostClass.PAID)
        _svc(p).create_reader(conn, make_reader("r1"))
        _svc(p).generate_first_brief(conn, "r1")
        run = generation_run_repository.list_runs_by_task_type(
            conn, "generate_first_microbrief"
        )[0]
        assert run.provider == "external-provider"
        assert run.advertised_model == "external-model-v2"
        assert run.cost_class == "paid"
        conn.close()


class TestFailClosed:
    def test_unsupported_provider_raises(self):
        with pytest.raises(UnsupportedProviderError):
            create_app(
                db_path="/tmp/test-fail.db",
                app_settings=Settings(ai_provider="openai", ai_model="gpt-4"),
            )

    def test_health_reports_actual_identity(self):
        p = tempfile.mktemp(suffix=".db")
        app = create_app(
            db_path=p,
            provider=_custom("x", ["s"], model="custom-v3", provider_name="custom"),
        )
        with TestClient(app) as c:
            h = c.get("/health").json()
            assert h["ai_provider"] == "custom"
            assert h["ai_model"] == "custom-v3"


class TestTokenNormalization:
    def test_missing_total_normalized(self, db_path):
        from app.ai.mock import MockProvider

        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        payload = brief_payload(list(mp.values()), title="T", source_ids_map=sm)
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
        run = generation_run_repository.list_runs_by_task_type(
            conn, "generate_first_microbrief"
        )[0]
        assert run.total_tokens == 12
        conn.close()


class TestEvidenceIntegrity:
    def test_evidence_nonexistent_reader_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        with pytest.raises(EvidenceValidationError, match="reader not found"):
            _svc(make_brief_provider([], [])).record_pilot_evidence(
                conn,
                PilotEvidenceInput(
                    reader_id="ghost", brief_id="x",
                    evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
                    anonymous_token="anon-g",
                ),
            )
        conn.close()

    def test_evidence_ownership_mismatch_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm))
        svc.create_reader(conn, make_reader("r1"))
        svc.create_reader(conn, make_reader("r2"))
        brief = svc.generate_first_brief(conn, "r1")
        with pytest.raises(EvidenceValidationError, match="does not belong"):
            svc.record_pilot_evidence(
                conn,
                PilotEvidenceInput(
                    reader_id="r2", brief_id=brief.id,
                    evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
                    anonymous_token="anon-m",
                ),
            )
        conn.close()

    def test_sensitive_detail_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp, sm = _seed(conn)
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm))
        svc.create_reader(conn, make_reader("r1"))
        brief = svc.generate_first_brief(conn, "r1")
        rec = svc.record_pilot_evidence(
            conn,
            PilotEvidenceInput(
                reader_id="r1", brief_id=brief.id,
                evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
                anonymous_token="anon-s",
                detail="email me at user@secret.com or +82-10-1234-5678",
            ),
        )
        assert "user@secret.com" not in rec.detail
        assert "+82-10-1234-5678" not in rec.detail
        assert "[redacted]" in rec.detail
        conn.close()
