from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import Category, ProviderErrorCategory
from app.ai.mock import MockProvider
from app.repositories import generation_run_repository
from app.service import WorldFeedService
from tests.conftest import (
    brief_payload,
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


class TestAccounting:
    def test_retry_aggregates_latency_and_tokens(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        mp = _seed(conn)
        payload = brief_payload(list(mp.values()), title="First")
        provider = MockProvider(
            model=settings.ai_model,
            responses=[
                {
                    "kind": "error",
                    "category": ProviderErrorCategory.PROVIDER_ERROR,
                    "message": "transient boom",
                    "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
                },
                {
                    "kind": "payload",
                    "payload": payload,
                    "usage": {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19},
                },
            ],
        )
        svc = _svc(provider)
        svc.create_reader(conn, make_reader("r1"))
        svc.generate_first_brief(conn, "r1")

        runs = generation_run_repository.list_runs_by_task_type(
            conn, "generate_first_microbrief"
        )
        assert len(runs) == 1
        run = runs[0]
        # One retry (attempt 1 failed, attempt 2 succeeded).
        assert run.retry_count == 1
        assert run.success == 1
        assert run.error_category is None
        assert run.input_tokens == 15  # 3 + 12 aggregated
        assert run.output_tokens == 8  # 1 + 7 aggregated
        assert run.total_tokens == 23  # 4 + 19 aggregated
        assert run.latency_seconds is not None
        assert run.latency_seconds >= 0.0
        conn.close()

    def test_failed_run_records_error_category(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        _seed(conn)
        provider = MockProvider(model=settings.ai_model)
        provider._fixture_payload = None  # forces schema_mismatch failure
        svc = _svc(provider)
        svc.create_reader(conn, make_reader("r1"))
        from app.service import BriefGenerationError

        try:
            svc.generate_first_brief(conn, "r1")
        except BriefGenerationError:
            pass
        runs = generation_run_repository.list_runs_by_task_type(
            conn, "generate_first_microbrief"
        )
        assert len(runs) == 1
        assert runs[0].success == 0
        conn.close()
