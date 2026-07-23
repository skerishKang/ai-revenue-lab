"""Blocker A: atomic idempotency claim under real concurrency.

The same operation key, claimed concurrently from multiple connections, must
yield exactly one owner. Losers get a conflict (or a completed replay if the
owner finished first) — never a second owned claim.
"""

from __future__ import annotations

import sqlite3
import threading

from app.domain.operation import OperationIdentity, TASK_FIRST_LESSON
from app.pipeline.errors import ConcurrentOperationError, OperationTerminalError
from app.repositories import claim_operation, complete_operation

from tests.contracts.conftest import make_pipeline


def test_concurrent_claim_has_exactly_one_owner(file_db):
    barrier = threading.Barrier(8)
    results: list[str] = []
    lock = threading.Lock()

    identity = OperationIdentity(
        task_type=TASK_FIRST_LESSON,
        learner_id="learner_x",
        client_idempotency_key="same-key",
        prior_lesson_id="concept_x",
    )

    def worker():
        pipeline = make_pipeline(file_db)
        try:
            barrier.wait()
            pipeline._begin_immediate()
            try:
                outcome = claim_operation(pipeline.conn, identity)
                pipeline.conn.commit()
            except Exception:
                pipeline.conn.rollback()
                raise
            if outcome.acquired:
                # Simulate doing the guarded work, then completing.
                pipeline._begin_immediate()
                complete_operation(
                    pipeline.conn, identity.operation_key, result_json='{"ok": true}'
                )
                pipeline.conn.commit()
                verdict = "owner"
            elif outcome.replay:
                verdict = "replay"
            elif outcome.terminal:
                verdict = "terminal"
            else:
                verdict = "conflict"
            with lock:
                results.append(verdict)
        finally:
            pipeline.conn.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    owners = results.count("owner")
    assert owners == 1, f"expected exactly one owner, got {owners}: {results}"
    # Every other caller saw either a conflict (active claim) or a completed replay.
    assert set(results) <= {"owner", "conflict", "replay"}


def test_distinct_keys_each_get_an_owner(file_db):
    """Different operation keys do not contend with each other."""
    acquired = 0
    for i in range(5):
        pipeline = make_pipeline(file_db)
        try:
            identity = OperationIdentity(
                task_type=TASK_FIRST_LESSON,
                learner_id="learner_y",
                client_idempotency_key=f"key-{i}",
                prior_lesson_id="concept_y",
            )
            pipeline._begin_immediate()
            outcome = claim_operation(pipeline.conn, identity)
            pipeline.conn.commit()
            if outcome.acquired:
                acquired += 1
        finally:
            pipeline.conn.close()
    assert acquired == 5


def test_operation_key_binds_structure_not_just_client_key(file_db):
    """The same client key on different resources yields different operation keys."""
    id_a = OperationIdentity(
        task_type=TASK_FIRST_LESSON,
        learner_id="L1",
        client_idempotency_key="k",
        prior_lesson_id="concept_A",
    )
    id_b = OperationIdentity(
        task_type=TASK_FIRST_LESSON,
        learner_id="L1",
        client_idempotency_key="k",
        prior_lesson_id="concept_B",
    )
    assert id_a.operation_key != id_b.operation_key
