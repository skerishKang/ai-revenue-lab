import pytest

from app import generation_request_repository as gen_req_repo
from app import participant_repository as repo
from app.db import apply_migrations, get_connection
from app.db_runtime import SqliteRuntimeConnection


def _setup(conn, pid="p1"):
    repo.create_participant(
        SqliteRuntimeConnection(conn),
        participant_id=pid,
        display_name="Test User",
        preferred_language="ko",
    )


class TestClaimGenerationRequest:
    def test_first_claim_owns_the_key(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup(conn)

        claim = gen_req_repo.claim_generation_request(
            SqliteRuntimeConnection(conn),
            idempotency_key="k1",
            participant_id="p1",
            input_id="i1",
        )
        assert claim.already_claimed is False
        assert claim.edition_id is None
        assert claim.status == "claimed"
        assert claim.id
        conn.close()

    def test_second_claim_is_duplicate(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup(conn)

        first = gen_req_repo.claim_generation_request(
            SqliteRuntimeConnection(conn),
            idempotency_key="k1",
            participant_id="p1",
            input_id="i1",
        )
        second = gen_req_repo.claim_generation_request(
            SqliteRuntimeConnection(conn),
            idempotency_key="k1",
            participant_id="p1",
            input_id="i1",
        )
        assert first.already_claimed is False
        assert second.already_claimed is True
        assert second.id == first.id
        conn.close()

    def test_distinct_keys_are_independent(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup(conn)

        a = gen_req_repo.claim_generation_request(
            SqliteRuntimeConnection(conn),
            idempotency_key="k1",
            participant_id="p1",
        )
        b = gen_req_repo.claim_generation_request(
            SqliteRuntimeConnection(conn),
            idempotency_key="k2",
            participant_id="p1",
        )
        assert a.already_claimed is False
        assert b.already_claimed is False
        assert a.id != b.id
        conn.close()

    def test_complete_records_edition_and_replays(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup(conn)

        gen_req_repo.claim_generation_request(
            SqliteRuntimeConnection(conn),
            idempotency_key="k1",
            participant_id="p1",
        )
        gen_req_repo.complete_generation_request(
            SqliteRuntimeConnection(conn),
            idempotency_key="k1",
            edition_id="e-123",
        )
        replay = gen_req_repo.claim_generation_request(
            SqliteRuntimeConnection(conn),
            idempotency_key="k1",
            participant_id="p1",
        )
        assert replay.already_claimed is True
        assert replay.edition_id == "e-123"
        assert replay.status == "completed"
        conn.close()

    def test_complete_unclaimed_key_raises(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup(conn)

        with pytest.raises(gen_req_repo.GenerationRequestError):
            gen_req_repo.complete_generation_request(
                SqliteRuntimeConnection(conn),
                idempotency_key="never-claimed",
                edition_id="e-1",
            )
        conn.close()

    def test_claim_rejects_empty_key(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup(conn)

        with pytest.raises(gen_req_repo.GenerationRequestError):
            gen_req_repo.claim_generation_request(
                SqliteRuntimeConnection(conn),
                idempotency_key="   ",
                participant_id="p1",
            )
        conn.close()

    def test_get_by_key_returns_none_when_absent(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup(conn)

        assert gen_req_repo.get_generation_request_by_key(
            SqliteRuntimeConnection(conn), "missing"
        ) is None
        conn.close()
