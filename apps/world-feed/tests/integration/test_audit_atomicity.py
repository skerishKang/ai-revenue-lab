"""Audit: prior-brief binding, idempotency conflict, mid-txn atomicity."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import Category, FeedbackAction
from app.domain.models import FeedbackInput
from app.repositories import (
    brief_repository,
    feedback_repository,
    generation_run_repository,
)
from app.service import (
    IdempotencyConflictError,
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

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def _svc(provider):
    return WorldFeedService(provider=provider, settings=settings)


def _seed(conn):
    svc = _svc(make_brief_provider([], []))
    svc.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
    svc.ingest_source_card(conn, make_source("s2", "ev-2", Category.NEIGHBORHOOD))
    svc.resolve_canonical_events(conn)
    return event_id_map(conn), event_source_ids_map(conn)


class TestPriorBriefBinding:
    def test_prior_must_equal_current_first_brief(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, str(MIGRATIONS))
        mp, sm = _seed(conn)
        svc = _svc(
            make_brief_provider(
                [mp["ev-1"]], [mp["ev-2"]], source_ids_map=sm,
                first_title="A", second_title="B",
            )
        )
        svc.create_reader(conn, make_reader("r1"))
        first = svc.generate_first_brief(conn, "r1")
        conn.execute(
            "INSERT INTO briefs (id, brief_number, reader_id, language, "
            "generation_run_id, sequence, status, title, deck, body_json, "
            "selected_event_ids, feedback_id, validation_status, created_at) "
            "VALUES ('stale-first', 'WF-STALE', 'r1', 'ko', 'run-x', 'first', "
            "'pending_review', 'stale', 'd', '{}', '[]', NULL, 'passed', "
            "'2020-01-01T00:00:00Z')"
        )
        svc.apply_feedback(
            conn,
            FeedbackInput(
                feedback_id="fb-stale",
                reader_id="r1",
                prior_brief_id="stale-first",
                idempotency_key="idem-stale",
                action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
            ),
        )
        with pytest.raises(MismatchedPriorBriefError, match="current first brief"):
            svc.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-stale")
        assert (
            brief_repository.get_latest_by_reader_sequence(conn, "r1", "first").id
            == first.id
        )
        conn.close()

    def test_idempotency_key_conflict_on_different_resources(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, str(MIGRATIONS))
        mp, sm = _seed(conn)
        svc = _svc(
            make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm)
        )
        svc.create_reader(conn, make_reader("r1"))
        first = svc.generate_first_brief(conn, "r1")
        svc.apply_feedback(
            conn,
            FeedbackInput(
                feedback_id="fb1",
                reader_id="r1",
                prior_brief_id=first.id,
                idempotency_key="shared-key",
                action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
            ),
        )
        with pytest.raises(IdempotencyConflictError):
            svc.apply_feedback(
                conn,
                FeedbackInput(
                    feedback_id="fb2",
                    reader_id="r1",
                    prior_brief_id=first.id,
                    idempotency_key="shared-key",
                    action=FeedbackAction.REDUCE_PROMOTIONAL_ENTERTAINMENT,
                ),
            )
        conn.close()


class TestAtomicMidTxn:
    def test_mark_applied_failure_rolls_back_second_brief(self, db_path, monkeypatch):
        conn = get_connection(db_path)
        apply_migrations(conn, str(MIGRATIONS))
        mp, sm = _seed(conn)
        svc = _svc(
            make_brief_provider(
                [mp["ev-1"]], [mp["ev-2"]], source_ids_map=sm,
                first_title="First", second_title="Second",
            )
        )
        svc.create_reader(conn, make_reader("r1"))
        first = svc.generate_first_brief(conn, "r1")
        svc.apply_feedback(
            conn,
            FeedbackInput(
                feedback_id="fb-atom",
                reader_id="r1",
                prior_brief_id=first.id,
                idempotency_key="idem-atom",
                action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
            ),
        )

        def boom(*args, **kwargs):
            raise RuntimeError("feedback apply failed mid-txn")

        monkeypatch.setattr(feedback_repository, "mark_applied", boom)
        with pytest.raises(RuntimeError, match="mid-txn"):
            svc.generate_second_brief(conn, "r1", feedback_idempotency_key="idem-atom")
        assert brief_repository.count_briefs(conn) == 1
        assert feedback_repository.get_feedback_by_id(conn, "fb-atom").applied_to_brief_id is None
        assert conn.execute("SELECT 1").fetchone()[0] == 1
        conn.close()
        conn2 = get_connection(db_path)
        assert brief_repository.count_briefs(conn2) == 1
        assert feedback_repository.get_feedback_by_id(conn2, "fb-atom").applied_to_brief_id is None
        conn2.close()

    def test_run_finalize_failure_rolls_back_brief(self, db_path, monkeypatch):
        conn = get_connection(db_path)
        apply_migrations(conn, str(MIGRATIONS))
        mp, sm = _seed(conn)
        svc = _svc(
            make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm)
        )
        svc.create_reader(conn, make_reader("r1"))
        real_update = generation_run_repository.update_generation_run

        def boom(conn_, run_id, **kwargs):
            if kwargs.get("validation_status") == "passed" and kwargs.get("success") == 1:
                raise RuntimeError("finalize failed")
            return real_update(conn_, run_id, **kwargs)

        monkeypatch.setattr(generation_run_repository, "update_generation_run", boom)
        with pytest.raises(RuntimeError, match="finalize failed"):
            svc.generate_first_brief(conn, "r1")
        assert brief_repository.count_briefs(conn) == 0
        runs = generation_run_repository.list_runs_by_task_type(
            conn, "generate_first_microbrief"
        )
        assert runs and all(r.success == 0 for r in runs)
        assert all(r.validation_status != "passed" for r in runs)
        conn.close()
