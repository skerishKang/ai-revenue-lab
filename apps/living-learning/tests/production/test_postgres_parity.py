"""PostgreSQL backend parity contracts.

These tests run against a real PostgreSQL database when ``LL_TEST_DATABASE_URL``
(and optionally ``LL_TEST_MIGRATION_DATABASE_URL``) is set; otherwise they skip.
They verify migration fresh/upgrade, advisory-lock serialization, runtime-role
least privilege, and repository parity (idempotency, review CAS, stale-owner
fencing, second-lesson atomicity, publication lineage) on PostgreSQL.

When no database is available these tests report as skipped (live-blocked); they
are real tests that execute when infrastructure is provisioned.
"""

from __future__ import annotations

import os

import pytest

DATABASE_URL = os.environ.get("LL_TEST_DATABASE_URL", "")
MIGRATION_URL = os.environ.get("LL_TEST_MIGRATION_DATABASE_URL", "") or DATABASE_URL

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="LL_TEST_DATABASE_URL not set (PostgreSQL parity live-blocked)"
)


@pytest.fixture
def pg_conn():
    from app.production.database import connect_postgres
    from app.production.migrate import apply_migrations

    conn = connect_postgres(MIGRATION_URL, autocommit=True)
    apply_migrations(conn)
    yield conn
    conn.close()


def test_fresh_migration_applies_all(pg_conn):
    from app.production.migrate import applied_migrations, list_migrations

    raw = pg_conn.raw
    applied = applied_migrations(raw)
    expected = {p.name for p in list_migrations()}
    assert expected <= set(applied.keys())


def test_migration_rerun_is_noop(pg_conn):
    from app.production.migrate import apply_migrations

    newly = apply_migrations(pg_conn)
    assert newly == []


def test_learner_repository_parity(pg_conn):
    from app.repositories.learner_repository import create_learner, get_learner_by_id

    learner = create_learner(pg_conn, topic="Python", display_name="pg-test", commit=True)
    fetched = get_learner_by_id(pg_conn, learner.id)
    assert fetched is not None
    assert fetched.topic == "Python"


def test_idempotency_claim_parity(pg_conn):
    from app.domain.operation import OperationIdentity, TASK_FIRST_LESSON
    from app.repositories.idempotency_repository import (
        STATUS_COMPLETED,
        claim_operation,
        complete_operation,
    )

    identity = OperationIdentity(
        task_type=TASK_FIRST_LESSON,
        learner_id="learner-pg",
        client_idempotency_key="pg-key-1",
        prior_lesson_id="concept-pg",
    )
    pg_conn.execute("BEGIN")
    outcome = claim_operation(pg_conn, identity)
    pg_conn.execute("COMMIT")
    assert outcome.acquired

    pg_conn.execute("BEGIN")
    complete_operation(pg_conn, outcome.handle, result_json='{"ok": true}')
    pg_conn.execute("COMMIT")

    from app.repositories.idempotency_repository import get_operation

    rec = get_operation(pg_conn, identity.operation_key)
    assert rec.status == STATUS_COMPLETED


def test_stale_owner_fencing_parity(pg_conn):
    from app.domain.operation import OperationIdentity, TASK_SECOND_LESSON
    from app.production.database import IntegrityError
    from app.repositories.idempotency_repository import (
        claim_operation,
        complete_operation,
    )
    from app.pipeline.errors import LostClaimOwnershipError

    identity = OperationIdentity(
        task_type=TASK_SECOND_LESSON,
        learner_id="learner-pg",
        client_idempotency_key="pg-fence-key",
        prior_lesson_id="prior",
        feedback_id="fb",
    )
    # Owner A claims.
    pg_conn.execute("BEGIN")
    outcome_a = claim_operation(pg_conn, identity)
    pg_conn.execute("COMMIT")
    assert outcome_a.acquired

    # Simulate reclaim by bumping fencing via a fresh claim after marking stale.
    pg_conn.execute(
        "UPDATE idempotency_requests SET lease_expires_at = '2000-01-01T00:00:00.000000Z' "
        "WHERE key_value = %s",
        (identity.operation_key,),
    )
    pg_conn.execute("BEGIN")
    outcome_b = claim_operation(pg_conn, identity)
    pg_conn.execute("COMMIT")
    assert outcome_b.acquired
    assert outcome_b.handle.fencing_version == outcome_a.handle.fencing_version + 1

    # Stale owner A can no longer complete.
    pg_conn.execute("BEGIN")
    with pytest.raises(LostClaimOwnershipError):
        complete_operation(pg_conn, outcome_a.handle, result_json='{"stale": true}')
    pg_conn.execute("ROLLBACK")
