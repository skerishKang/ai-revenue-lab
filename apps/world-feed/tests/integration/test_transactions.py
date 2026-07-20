import pytest

from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import Category
from app.repositories import brief_repository, generation_run_repository
from app.service import BriefGenerationError, WorldFeedService
from tests.conftest import (
    event_id_map,
    make_brief_provider,
    make_reader,
    make_source,
)
from app.ai.mock import MockProvider


def _svc(provider):
    return WorldFeedService(provider=provider, settings=settings)


def _seed(conn, svc):
    svc.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
    svc.ingest_source_card(conn, make_source("s2", "ev-2", Category.NEIGHBORHOOD))
    svc.resolve_canonical_events(conn)


class TestTransactions:
    def test_failed_generation_rolls_back_and_keeps_last_valid(self, db_path):
        from app.domain.enums import FeedbackAction
        from app.domain.models import FeedbackInput

        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        _seed(conn, _svc(make_brief_provider([], [])))
        mp = event_id_map(conn)
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values())))
        svc.create_reader(conn, make_reader("r1"))
        first = svc.generate_first_brief(conn, "r1")

        # Persist feedback, then fail second generation; first is untouched.
        feedback = FeedbackInput(
            feedback_id="fx",
            reader_id="r1",
            prior_brief_id=first.id,
            idempotency_key="idem-rollback",
            action=FeedbackAction.REDUCE_PROMOTIONAL_ENTERTAINMENT,
        )
        svc.apply_feedback(conn, feedback)
        failing = _svc(MockProvider())
        with pytest.raises(BriefGenerationError):
            failing.generate_second_brief(
                conn, "r1", feedback_idempotency_key="idem-rollback"
            )
        # No second brief; first still present and unchanged.
        assert brief_repository.count_briefs(conn) == 1
        still = brief_repository.get_brief_by_id(conn, first.id)
        assert still.status == "pending_review"
        conn.close()

    def test_atomic_rollback_on_brief_insert_failure(self, db_path, monkeypatch):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        _seed(conn, _svc(make_brief_provider([], [])))
        mp = event_id_map(conn)
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values())))
        svc.create_reader(conn, make_reader("r1"))

        real_create = brief_repository.create_brief

        def boom(*args, **kwargs):
            raise RuntimeError("simulated DB failure during brief insert")

        monkeypatch.setattr(brief_repository, "create_brief", boom)
        with pytest.raises(RuntimeError):
            svc.generate_first_brief(conn, "r1")

        # No brief row, and the generation run was not finalized as success.
        assert brief_repository.count_briefs(conn) == 0
        runs = generation_run_repository.list_runs_by_task_type(
            conn, "generate_first_microbrief"
        )
        assert len(runs) >= 1
        assert all(r.success == 0 for r in runs)
        conn.close()

    def test_generation_run_recorded_on_success(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        _seed(conn, _svc(make_brief_provider([], [])))
        mp = event_id_map(conn)
        svc = _svc(make_brief_provider(list(mp.values()), list(mp.values())))
        svc.create_reader(conn, make_reader("r1"))
        svc.generate_first_brief(conn, "r1")
        runs = generation_run_repository.list_runs_by_task_type(
            conn, "generate_first_microbrief"
        )
        assert len(runs) == 1
        assert runs[0].success == 1
        assert runs[0].provider == "mock"
        assert runs[0].advertised_model == "mock-world-feed-v1"
        assert runs[0].validation_status == "passed"
        conn.close()
