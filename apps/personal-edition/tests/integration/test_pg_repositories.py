"""PostgreSQL acceptance tests: real repositories over the PG runtime.

These tests exercise the actual repository signatures against a real
PostgreSQL runtime connection (``autocommit=True``, ``dict_row``) opened
through the proper ``opener``/``open()`` lifecycle — never by injecting the
private ``runtime._conn``.

They only run when BOTH:
  - TEST_POSTGRES_URL is set
  - PE_PG_TEST_INTEGRATION=1

Each test gets an isolated temporary schema; the ``public`` schema is never
written to, and a production Neon database is never targeted (the URL is
refused if it resolves to the same identity as PE_DATABASE_URL).

Covered: startup verification, full CRUD, rollback, public preservation,
concurrency (atomic edition numbering + row locking), and generation-request
idempotency.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.config import normalize_pg_url_identity

TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "")
PE_DATABASE_URL = os.environ.get("PE_DATABASE_URL", "")
PE_PG_TEST_INTEGRATION = os.environ.get("PE_PG_TEST_INTEGRATION", "").strip()


def _urls_resolve_to_same_db(a: str, b: str) -> bool:
    if not a or not b:
        return False
    ia = normalize_pg_url_identity(a)
    ib = normalize_pg_url_identity(b)
    if ia is None or ib is None:
        return a == b
    return ia == ib


if TEST_POSTGRES_URL and PE_DATABASE_URL and _urls_resolve_to_same_db(
    TEST_POSTGRES_URL, PE_DATABASE_URL
):
    raise RuntimeError(
        "TEST_POSTGRES_URL resolves to the same database identity as "
        "PE_DATABASE_URL — refusing to run integration tests."
    )

_INTEGRATION_ENABLED = bool(
    TEST_POSTGRES_URL
    and PE_PG_TEST_INTEGRATION in ("1", "true", "yes", "on")
)

pytestmark = pytest.mark.skipif(
    not _INTEGRATION_ENABLED,
    reason=(
        "PostgreSQL acceptance tests require both TEST_POSTGRES_URL and "
        "PE_PG_TEST_INTEGRATION=1."
    ),
)

DOMAIN_TABLES = {
    "participants",
    "inputs",
    "editions",
    "feedback",
    "generation_runs",
    "generation_requests",
    "benchmark_runs",
    "pilot_ops_records",
}


class PgEnv:
    """Isolated PostgreSQL environment for one test.

    ``runtime`` is a real :class:`PostgresRuntimeConnection` opened via the
    ``opener``/``open()`` lifecycle (autocommit=True).  ``raw_conn()`` opens a
    fresh migration-style connection (autocommit=False) with ``search_path``
    pointed at the isolated schema, for startup verification and public-schema
    assertions.
    """

    def __init__(self, runtime, bootstrap, schema_name):
        self.runtime = runtime
        self.bootstrap = bootstrap
        self.schema_name = schema_name

    def raw_conn(self):
        from app.db_postgres import get_pg_connection

        conn = get_pg_connection(TEST_POSTGRES_URL)
        conn.execute(f'SET search_path TO "{self.schema_name}"')
        return conn


@pytest.fixture
def pg_env():
    from app.db_pg_migrations import apply_pg_migrations
    from app.db_postgres import (
        PG_MIGRATIONS_DIR,
        get_pg_connection,
        get_pg_runtime_connection,
    )
    from app.db_runtime import PostgresRuntimeConnection

    schema_name = f"test_repo_{uuid.uuid4().hex}"
    bootstrap = get_pg_connection(TEST_POSTGRES_URL)
    try:
        bootstrap.execute(f'CREATE SCHEMA "{schema_name}"')
        bootstrap.execute(f'SET search_path TO "{schema_name}"')
        bootstrap.commit()
        apply_pg_migrations(bootstrap, PG_MIGRATIONS_DIR)
        bootstrap.commit()
    except Exception:
        try:
            bootstrap.rollback()
            bootstrap.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
            bootstrap.commit()
        except Exception:
            pass
        bootstrap.close()
        raise

    def opener():
        conn = get_pg_runtime_connection(TEST_POSTGRES_URL)
        conn.execute(f'SET search_path TO "{schema_name}"')
        return conn

    runtime = PostgresRuntimeConnection(opener).open()
    env = PgEnv(runtime, bootstrap, schema_name)
    try:
        yield env
    finally:
        try:
            runtime.close()
        except Exception:
            pass
        try:
            bootstrap.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
            bootstrap.commit()
        except Exception:
            try:
                bootstrap.rollback()
            except Exception:
                pass
        bootstrap.close()


def _make_participant(runtime, pid="p1"):
    from app import participant_repository as pt_repo

    provisioned = pt_repo.create_participant(
        runtime,
        participant_id=pid,
        display_name="Test User",
        preferred_language="ko",
    )
    return provisioned.participant


def _make_input(runtime, pid="p1", raw_text="First input"):
    from app import input_repository as input_repo

    return input_repo.create_input(
        runtime,
        participant_id=pid,
        raw_text=raw_text,
        consent_confirmed=1,
    )


def _make_edition(runtime, pid="p1", **kwargs):
    from app import edition_repository as ed_repo

    return ed_repo.create_edition(
        runtime,
        participant_id=pid,
        structured_content='{"sections": []}',
        rendered_title="Test Edition",
        **kwargs,
    )


class TestRuntimeLifecycle:
    def test_runtime_is_open_without_private_injection(self, pg_env):
        # The fixture opens the connection via opener/open(); the adapter is
        # usable immediately and reports the PostgreSQL row-lock clause.
        assert pg_env.runtime.row_lock_suffix == " FOR UPDATE"
        assert pg_env.runtime.in_transaction is False

    def test_runtime_connection_is_autocommit(self, pg_env):
        # A plain SELECT must not leave an open transaction on the runtime
        # connection (autocommit=True contract).
        pg_env.runtime.execute("SELECT 1 AS one").fetchone()
        assert pg_env.runtime.in_transaction is False


class TestStartupVerification:
    def test_verify_pg_schema_passes_on_migrated_schema(self, pg_env):
        from app.db_pg_migrations import verify_pg_schema
        from app.db_postgres import PG_MIGRATIONS_DIR

        conn = pg_env.raw_conn()
        try:
            result = verify_pg_schema(conn, PG_MIGRATIONS_DIR)
        finally:
            conn.close()

        assert result["pending_count"] == 0
        assert result["applied_count"] >= 1
        assert result["schema"] == pg_env.schema_name


class TestFullCrud:
    def test_participant_create_and_get(self, pg_env):
        from app import participant_repository as pt_repo

        participant = _make_participant(pg_env.runtime, "p1")
        assert participant.id == "p1"

        fetched = pt_repo.get_participant_by_id(pg_env.runtime, "p1")
        assert fetched is not None
        assert fetched.display_name == "Test User"

    def test_input_sequence(self, pg_env):
        _make_participant(pg_env.runtime, "p1")
        inp1 = _make_input(pg_env.runtime, "p1", "First")
        inp2 = _make_input(pg_env.runtime, "p1", "Second")
        assert inp1.sequence_number == 1
        assert inp2.sequence_number == 2

    def test_edition_create_and_get(self, pg_env):
        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")
        assert edition.id
        assert edition.publication_state == "pending"
        assert edition.generation_status == "pending_review"

        from app import edition_repository as ed_repo

        fetched = ed_repo.get_edition_by_id(pg_env.runtime, edition.id)
        assert fetched is not None
        assert fetched.rendered_title == "Test Edition"

    def test_edition_update_content(self, pg_env):
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")

        updated = ed_repo.update_edition_content(
            pg_env.runtime,
            edition.id,
            rendered_title="Renamed",
        )
        assert updated is not None
        assert updated.rendered_title == "Renamed"

    def test_edition_publish(self, pg_env):
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")

        published = ed_repo.update_edition_publication(
            pg_env.runtime, edition.id, "published"
        )
        assert published is not None
        assert published.publication_state == "published"
        assert published.published_at is not None

    def test_edition_delete(self, pg_env):
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")

        assert ed_repo.delete_edition(pg_env.runtime, edition.id) is True
        fetched = ed_repo.get_edition_by_id(pg_env.runtime, edition.id)
        assert fetched.generation_status == "deleted"

    def test_feedback_create(self, pg_env):
        from app import feedback_repository as fb_repo

        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")

        feedback = fb_repo.create_feedback(
            pg_env.runtime,
            participant_id="p1",
            edition_id=edition.id,
            direction_choices='["more_practical"]',
        )
        assert feedback.id
        assert feedback.applied_to_next_edition == 0

    def test_generation_run_create_and_update(self, pg_env):
        from app import generation_run_repository as gr_repo

        run = gr_repo.create_generation_run(
            pg_env.runtime,
            task_type="first_edition",
            provider="mock",
            advertised_model="mock-v1",
        )
        assert run.id
        assert run.success == 0

        updated = gr_repo.update_generation_run(
            pg_env.runtime,
            run.id,
            success=1,
            validation_status="passed",
        )
        assert updated is not None
        assert updated.success == 1
        assert updated.validation_status == "passed"


class TestRollback:
    def test_failed_create_edition_leaves_no_partial_row(self, pg_env):
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")

        with pytest.raises(ed_repo.EditionValidationError):
            _make_edition(
                pg_env.runtime,
                "p1",
                prior_edition_id="does-not-exist",
            )

        # The failed transaction must have rolled back: no edition exists and
        # the runtime connection is idle (not stuck in a transaction).
        editions = ed_repo.get_editions_by_participant(pg_env.runtime, "p1")
        assert editions == []
        assert pg_env.runtime.in_transaction is False


class TestPublicPreservation:
    def test_crud_does_not_touch_public_schema(self, pg_env):
        from app.db_pg_migrations import get_pg_schema_tables

        # Perform real writes in the isolated schema.
        _make_participant(pg_env.runtime, "p1")
        _make_input(pg_env.runtime, "p1")
        _make_edition(pg_env.runtime, "p1")

        conn = pg_env.raw_conn()
        try:
            public_tables = get_pg_schema_tables(conn, "public")
            test_tables = get_pg_schema_tables(conn, pg_env.schema_name)
        finally:
            conn.close()

        for table in DOMAIN_TABLES:
            assert table not in public_tables, (
                f"'{table}' leaked into the public schema"
            )
            assert table in test_tables, (
                f"'{table}' missing from the isolated test schema"
            )


class TestConcurrency:
    """Real concurrent acceptance tests.

    Each worker thread opens its own independent ``PostgresRuntimeConnection``
    (autocommit=True) pointed at the isolated test schema.  A
    ``threading.Barrier`` ensures all workers start their critical section
    simultaneously so row-level contention is genuinely exercised.
    """

    def _thread_runtime(self, schema_name: str):
        from app.db_postgres import get_pg_runtime_connection
        from app.db_runtime import PostgresRuntimeConnection

        def opener():
            conn = get_pg_runtime_connection(TEST_POSTGRES_URL)
            conn.execute(f'SET search_path TO "{schema_name}"')
            return conn

        return PostgresRuntimeConnection(opener).open()

    def test_concurrent_edition_numbering_is_unique(self, pg_env):
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")
        n = 5
        barrier = threading.Barrier(n)
        errors: list = []

        def worker():
            rt = self._thread_runtime(pg_env.schema_name)
            try:
                barrier.wait(timeout=10)
                edition = ed_repo.create_edition(
                    rt,
                    participant_id="p1",
                    structured_content='{"sections": []}',
                    rendered_title="E",
                )
                return edition.edition_number
            except Exception as exc:
                errors.append(exc)
                return None
            finally:
                rt.close()

        with ThreadPoolExecutor(max_workers=n) as pool:
            numbers = [f.result() for f in as_completed(
                [pool.submit(worker) for _ in range(n)]
            )]

        assert not errors, f"unexpected errors: {errors}"
        assert sorted(numbers) == list(range(1, n + 1))

    def test_concurrent_input_sequence_is_unique(self, pg_env):
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app import input_repository as input_repo

        _make_participant(pg_env.runtime, "p1")
        n = 5
        barrier = threading.Barrier(n)
        errors: list = []

        def worker(i):
            rt = self._thread_runtime(pg_env.schema_name)
            try:
                barrier.wait(timeout=10)
                inp = input_repo.create_input(
                    rt,
                    participant_id="p1",
                    raw_text=f"input {i}",
                    consent_confirmed=1,
                )
                return inp.sequence_number
            except Exception as exc:
                errors.append(exc)
                return None
            finally:
                rt.close()

        with ThreadPoolExecutor(max_workers=n) as pool:
            seqs = [f.result() for f in as_completed(
                [pool.submit(worker, i) for i in range(n)]
            )]

        assert not errors, f"unexpected errors: {errors}"
        assert sorted(seqs) == list(range(1, n + 1))

    def test_concurrent_publication_only_one_wins(self, pg_env):
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")
        n = 4
        barrier = threading.Barrier(n)

        def worker():
            rt = self._thread_runtime(pg_env.schema_name)
            try:
                barrier.wait(timeout=10)
                ed_repo.update_edition_publication(rt, edition.id, "published")
                return "ok"
            except ed_repo.EditionStateConflict:
                return "conflict"
            finally:
                rt.close()

        with ThreadPoolExecutor(max_workers=n) as pool:
            outcomes = [f.result() for f in as_completed(
                [pool.submit(worker) for _ in range(n)]
            )]

        assert outcomes.count("ok") == 1
        assert outcomes.count("conflict") == n - 1

        final = ed_repo.get_edition_by_id(pg_env.runtime, edition.id)
        assert final is not None
        assert final.publication_state == "published"

    def test_concurrent_publish_vs_reject(self, pg_env):
        import threading
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")
        barrier = threading.Barrier(2)
        outcomes: dict = {}

        def publish_worker():
            rt = self._thread_runtime(pg_env.schema_name)
            try:
                barrier.wait(timeout=10)
                ed_repo.update_edition_publication(rt, edition.id, "published")
                outcomes["publish"] = "ok"
            except ed_repo.EditionStateConflict:
                outcomes["publish"] = "conflict"
            finally:
                rt.close()

        def reject_worker():
            rt = self._thread_runtime(pg_env.schema_name)
            try:
                barrier.wait(timeout=10)
                ed_repo.update_edition_publication(rt, edition.id, "rejected")
                outcomes["reject"] = "ok"
            except ed_repo.EditionStateConflict:
                outcomes["reject"] = "conflict"
            finally:
                rt.close()

        t_pub = threading.Thread(target=publish_worker)
        t_rej = threading.Thread(target=reject_worker)
        t_pub.start()
        t_rej.start()
        t_pub.join(timeout=15)
        t_rej.join(timeout=15)

        assert not t_pub.is_alive()
        assert not t_rej.is_alive()

        ok_count = sum(1 for v in outcomes.values() if v == "ok")
        assert ok_count == 1
        conflict_count = sum(1 for v in outcomes.values() if v == "conflict")
        assert conflict_count == 1

        final = ed_repo.get_edition_by_id(pg_env.runtime, edition.id)
        assert final is not None
        assert final.publication_state in ("published", "rejected")
        if outcomes["publish"] == "ok":
            assert final.publication_state == "published"
        else:
            assert final.publication_state == "rejected"
        assert final.published_at is not None or final.reviewed_at is not None

    def test_concurrent_content_update_vs_publish(self, pg_env):
        """One thread publishes while another updates content concurrently.

        The publish must always succeed (content update does not change
        publication_state).  The content update either succeeds (ran before
        publish committed) or raises EditionStateConflict (ran after).
        The edition must end in a consistent published state either way.
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from app import edition_repository as ed_repo

        _make_participant(pg_env.runtime, "p1")
        edition = _make_edition(pg_env.runtime, "p1")
        original_content = edition.structured_content
        barrier = threading.Barrier(2)
        updated_content = '{"sections": [{"body": "updated"}]}'

        def publish_worker():
            rt = self._thread_runtime(pg_env.schema_name)
            try:
                barrier.wait(timeout=10)
                ed_repo.update_edition_publication(rt, edition.id, "published")
                return "ok"
            finally:
                rt.close()

        def content_worker():
            rt = self._thread_runtime(pg_env.schema_name)
            try:
                barrier.wait(timeout=10)
                ed_repo.update_edition_content(
                    rt,
                    edition.id,
                    structured_content=updated_content,
                )
                return "ok"
            except ed_repo.EditionStateConflict:
                return "conflict"
            finally:
                rt.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            pub_future = pool.submit(publish_worker)
            con_future = pool.submit(content_worker)
            pub_result = pub_future.result(timeout=15)
            con_result = con_future.result(timeout=15)

        final = ed_repo.get_edition_by_id(pg_env.runtime, edition.id)
        assert final is not None
        assert final.publication_state == "published"
        assert pub_result == "ok"
        assert con_result in ("ok", "conflict")
        if con_result == "ok":
            assert final.structured_content == updated_content
        else:
            assert final.structured_content == original_content

    def test_concurrent_claim_same_key_one_wins(self, pg_env):
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app import generation_request_repository as gen_req_repo

        _make_participant(pg_env.runtime, "p1")
        inp = _make_input(pg_env.runtime, "p1")
        n = 4
        barrier = threading.Barrier(n)

        def worker():
            rt = self._thread_runtime(pg_env.schema_name)
            try:
                barrier.wait(timeout=10)
                record = gen_req_repo.claim_generation_request(
                    rt,
                    idempotency_key="concurrent-key",
                    participant_id="p1",
                    input_id=inp.id,
                )
                return record.already_claimed
            finally:
                rt.close()

        with ThreadPoolExecutor(max_workers=n) as pool:
            outcomes = [f.result() for f in as_completed(
                [pool.submit(worker) for _ in range(n)]
            )]

        assert outcomes.count(False) == 1
        assert outcomes.count(True) == n - 1

        row = pg_env.runtime.execute(
            "SELECT COUNT(*) AS cnt FROM generation_requests "
            "WHERE idempotency_key = 'concurrent-key'"
        ).fetchone()
        assert row["cnt"] == 1

    def test_lease_expiry_allows_reclaim(self, pg_env):
        import time
        from app import generation_request_repository as gen_req_repo

        _make_participant(pg_env.runtime, "p1")
        inp = _make_input(pg_env.runtime, "p1")

        first = gen_req_repo.claim_generation_request(
            pg_env.runtime,
            idempotency_key="lease-key",
            participant_id="p1",
            input_id=inp.id,
            lease_duration_seconds=1,
        )
        assert first.already_claimed is False

        dup = gen_req_repo.claim_generation_request(
            pg_env.runtime,
            idempotency_key="lease-key",
            participant_id="p1",
            input_id=inp.id,
        )
        assert dup.already_claimed is True

        time.sleep(1.5)

        reclaimed = gen_req_repo.claim_generation_request(
            pg_env.runtime,
            idempotency_key="lease-key",
            participant_id="p1",
            input_id=inp.id,
        )
        assert reclaimed.already_claimed is False
        assert reclaimed.claim_token != first.claim_token

    def test_concurrent_lease_reclaim_one_wins(self, pg_env):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app import generation_request_repository as gen_req_repo

        _make_participant(pg_env.runtime, "p1")
        inp = _make_input(pg_env.runtime, "p1")

        first = gen_req_repo.claim_generation_request(
            pg_env.runtime,
            idempotency_key="reclaim-key",
            participant_id="p1",
            input_id=inp.id,
            lease_duration_seconds=1,
        )
        assert first.already_claimed is False

        time.sleep(1.5)

        n = 3
        barrier = threading.Barrier(n)

        def worker():
            rt = self._thread_runtime(pg_env.schema_name)
            try:
                barrier.wait(timeout=10)
                record = gen_req_repo.claim_generation_request(
                    rt,
                    idempotency_key="reclaim-key",
                    participant_id="p1",
                    input_id=inp.id,
                )
                return record.already_claimed
            finally:
                rt.close()

        with ThreadPoolExecutor(max_workers=n) as pool:
            outcomes = [f.result() for f in as_completed(
                [pool.submit(worker) for _ in range(n)]
            )]

        assert outcomes.count(False) == 1
        assert outcomes.count(True) == n - 1

        row = pg_env.runtime.execute(
            "SELECT COUNT(*) AS cnt FROM generation_requests "
            "WHERE idempotency_key = 'reclaim-key'"
        ).fetchone()
        assert row["cnt"] == 1

    def test_concurrent_lease_reclaim_exhaustive(self, pg_env):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from app import edition_repository as ed_repo
        from app import generation_request_repository as gen_req_repo

        _make_participant(pg_env.runtime, "p1")
        inp = _make_input(pg_env.runtime, "p1")

        first = gen_req_repo.claim_generation_request(
            pg_env.runtime,
            idempotency_key="exhaustive-key",
            participant_id="p1",
            input_id=inp.id,
            lease_duration_seconds=1,
        )
        assert first.already_claimed is False
        assert first.claim_token is not None
        stale_token = first.claim_token

        time.sleep(1.5)

        n = 3
        barrier = threading.Barrier(n)
        results: dict = {}

        def worker(idx):
            rt = self._thread_runtime(pg_env.schema_name)
            try:
                barrier.wait(timeout=10)
                record = gen_req_repo.claim_generation_request(
                    rt,
                    idempotency_key="exhaustive-key",
                    participant_id="p1",
                    input_id=inp.id,
                )
                results[idx] = {
                    "already_claimed": record.already_claimed,
                    "claim_token": record.claim_token,
                }
            finally:
                rt.close()

        with ThreadPoolExecutor(max_workers=n) as pool:
            list(pool.map(worker, range(n)))

        winners = [v for v in results.values() if not v["already_claimed"]]
        losers = [v for v in results.values() if v["already_claimed"]]
        assert len(winners) == 1
        assert len(losers) == n - 1
        winner_token = winners[0]["claim_token"]
        assert winner_token is not None
        assert winner_token != stale_token
        for loser in losers:
            assert loser["claim_token"] is None

        row = pg_env.runtime.execute(
            "SELECT COUNT(*) AS cnt FROM generation_requests "
            "WHERE idempotency_key = 'exhaustive-key'"
        ).fetchone()
        assert row["cnt"] == 1

        stale_rt = self._thread_runtime(pg_env.schema_name)
        try:
            with pytest.raises(ed_repo.EditionStateConflict):
                ed_repo.finalize_edition_for_request(
                    stale_rt,
                    participant_id="p1",
                    idempotency_key="exhaustive-key",
                    claim_token=stale_token,
                    structured_content='{"sections": []}',
                    rendered_title="Stale",
                    input_id=inp.id,
                )
        finally:
            stale_rt.close()

        stale_rt2 = self._thread_runtime(pg_env.schema_name)
        try:
            with pytest.raises(gen_req_repo.GenerationRequestError):
                gen_req_repo.fail_generation_request(
                    stale_rt2,
                    idempotency_key="exhaustive-key",
                    claim_token=stale_token,
                    failure_category="provider",
                )
        finally:
            stale_rt2.close()

        win_rt = self._thread_runtime(pg_env.schema_name)
        try:
            edition = ed_repo.finalize_edition_for_request(
                win_rt,
                participant_id="p1",
                idempotency_key="exhaustive-key",
                claim_token=winner_token,
                structured_content='{"sections": []}',
                rendered_title="Winner",
                input_id=inp.id,
            )
        finally:
            win_rt.close()

        editions = ed_repo.get_editions_by_participant(pg_env.runtime, "p1")
        assert len(editions) == 1

        final_req = gen_req_repo.get_generation_request_by_key(
            pg_env.runtime, "exhaustive-key"
        )
        assert final_req is not None
        assert final_req.status == "completed"

    def test_concurrent_claim_different_owner_race(self, pg_env):
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app import generation_request_repository as gen_req_repo

        _make_participant(pg_env.runtime, "p1")
        _make_participant(pg_env.runtime, "p2")
        inp1 = _make_input(pg_env.runtime, "p1")
        inp2 = _make_input(pg_env.runtime, "p2")
        n = 2
        barrier = threading.Barrier(n)
        outcomes: dict = {}

        def worker_a():
            rt = self._thread_runtime(pg_env.schema_name)
            try:
                barrier.wait(timeout=10)
                record = gen_req_repo.claim_generation_request(
                    rt,
                    idempotency_key="owner-race-key",
                    participant_id="p1",
                    input_id=inp1.id,
                )
                outcomes["a_already_claimed"] = record.already_claimed
                outcomes["a_token"] = record.claim_token
            except gen_req_repo.GenerationRequestOwnershipError:
                outcomes["a_ownership_error"] = True
            finally:
                rt.close()

        def worker_b():
            rt = self._thread_runtime(pg_env.schema_name)
            try:
                barrier.wait(timeout=10)
                record = gen_req_repo.claim_generation_request(
                    rt,
                    idempotency_key="owner-race-key",
                    participant_id="p2",
                    input_id=inp2.id,
                )
                outcomes["b_already_claimed"] = record.already_claimed
                outcomes["b_token"] = record.claim_token
            except gen_req_repo.GenerationRequestOwnershipError:
                outcomes["b_ownership_error"] = True
            finally:
                rt.close()

        t_a = threading.Thread(target=worker_a)
        t_b = threading.Thread(target=worker_b)
        t_a.start()
        t_b.start()
        t_a.join(timeout=15)
        t_b.join(timeout=15)
        assert not t_a.is_alive()
        assert not t_b.is_alive()

        if "a_already_claimed" in outcomes:
            assert outcomes["a_already_claimed"] is False
            assert outcomes["a_token"] is not None
            assert outcomes.get("b_ownership_error") is True
        else:
            assert outcomes["b_already_claimed"] is False
            assert outcomes["b_token"] is not None
            assert outcomes.get("a_ownership_error") is True

        row = pg_env.runtime.execute(
            "SELECT COUNT(*) AS cnt FROM generation_requests "
            "WHERE idempotency_key = 'owner-race-key'"
        ).fetchone()
        assert row["cnt"] == 1


class TestIdempotency:
    def test_claim_complete_replay(self, pg_env):
        from app import edition_repository as ed_repo
        from app import generation_request_repository as gen_req_repo

        _make_participant(pg_env.runtime, "p1")
        inp = _make_input(pg_env.runtime, "p1")

        first = gen_req_repo.claim_generation_request(
            pg_env.runtime,
            idempotency_key="key-1",
            participant_id="p1",
            input_id=inp.id,
        )
        assert first.already_claimed is False

        duplicate = gen_req_repo.claim_generation_request(
            pg_env.runtime,
            idempotency_key="key-1",
            participant_id="p1",
            input_id=inp.id,
        )
        assert duplicate.already_claimed is True
        assert duplicate.edition_id is None

        edition = ed_repo.finalize_edition_for_request(
            pg_env.runtime,
            participant_id="p1",
            idempotency_key="key-1",
            claim_token=first.claim_token,
            structured_content='{"sections": []}',
            rendered_title="Test Edition",
            input_id=inp.id,
        )

        replay = gen_req_repo.claim_generation_request(
            pg_env.runtime,
            idempotency_key="key-1",
            participant_id="p1",
            input_id=inp.id,
        )
        assert replay.already_claimed is True
        assert replay.edition_id == edition.id
