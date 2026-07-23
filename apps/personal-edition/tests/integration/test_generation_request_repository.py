import pytest

from app import edition_repository as ed_repo
from app import generation_request_repository as gen_req_repo
from app import input_repository as input_repo
from app import participant_repository as repo
from app.db import apply_migrations, get_connection
from app.db_runtime import SqliteRuntimeConnection


def _setup(conn, pid="p1"):
    rt = SqliteRuntimeConnection(conn)
    repo.create_participant(
        rt,
        participant_id=pid,
        display_name="Test User",
        preferred_language="ko",
    )
    inp = input_repo.create_input(
        rt,
        participant_id=pid,
        raw_text="test input for generation",
        consent_confirmed=1,
    )
    return inp.id


class TestClaimGenerationRequest:
    def test_first_claim_owns_the_key(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)

        claim = gen_req_repo.claim_generation_request(
            SqliteRuntimeConnection(conn),
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
        )
        assert claim.already_claimed is False
        assert claim.edition_id is None
        assert claim.status == "claimed"
        assert claim.id
        assert claim.claim_token
        assert claim.lease_expires_at is not None
        conn.close()

    def test_second_claim_same_owner_valid_lease_is_duplicate(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        first = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
            now="2026-01-01T00:00:00.000Z",
            lease_duration_seconds=600,
        )
        second = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
            now="2026-01-01T00:05:00.000Z",
        )
        assert first.already_claimed is False
        assert second.already_claimed is True
        assert second.id == first.id
        assert second.claim_token == first.claim_token
        conn.close()

    def test_different_participant_raises_ownership_error(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id_p1 = _setup(conn, pid="p1")
        input_id_p2 = _setup(conn, pid="p2")
        rt = SqliteRuntimeConnection(conn)

        gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id_p1,
        )
        with pytest.raises(gen_req_repo.GenerationRequestOwnershipError):
            gen_req_repo.claim_generation_request(
                rt,
                idempotency_key="k1",
                participant_id="p2",
                input_id=input_id_p2,
            )
        conn.close()

    def test_different_input_raises_ownership_error(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn, pid="p1")
        rt = SqliteRuntimeConnection(conn)
        inp2 = input_repo.create_input(
            rt,
            participant_id="p1",
            raw_text="second input",
            consent_confirmed=1,
        )

        gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
        )
        with pytest.raises(gen_req_repo.GenerationRequestOwnershipError):
            gen_req_repo.claim_generation_request(
                rt,
                idempotency_key="k1",
                participant_id="p1",
                input_id=inp2.id,
            )
        conn.close()

    def test_expired_lease_allows_reclaim(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        first = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
            claim_token="token-1",
            now="2026-01-01T00:00:00.000Z",
            lease_duration_seconds=60,
        )
        assert first.lease_expires_at == "2026-01-01T00:01:00.000Z"

        second = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
            claim_token="token-2",
            now="2026-01-01T00:02:00.000Z",
        )
        assert second.already_claimed is False
        assert second.claim_token == "token-2"
        assert second.id == first.id
        conn.close()

    def test_distinct_keys_are_independent(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        a = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
        )
        b = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k2",
            participant_id="p1",
            input_id=input_id,
        )
        assert a.already_claimed is False
        assert b.already_claimed is False
        assert a.id != b.id
        conn.close()

    def test_complete_records_edition_and_replays(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        claim = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
        )
        edition = ed_repo.create_edition(
            rt,
            participant_id="p1",
            structured_content='{"sections": []}',
            rendered_title="Test",
        )
        gen_req_repo.complete_generation_request(
            rt,
            idempotency_key="k1",
            edition_id=edition.id,
            claim_token=claim.claim_token,
        )
        replay = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
        )
        assert replay.already_claimed is True
        assert replay.edition_id == edition.id
        assert replay.status == "completed"
        conn.close()

    def test_complete_with_wrong_token_raises(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
            claim_token="token-a",
        )
        with pytest.raises(gen_req_repo.GenerationRequestError):
            gen_req_repo.complete_generation_request(
                rt,
                idempotency_key="k1",
                edition_id="e-1",
                claim_token="token-wrong",
            )
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
                claim_token="any-token",
            )
        conn.close()

    def test_fail_transitions_to_failed(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        claim = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
        )
        gen_req_repo.fail_generation_request(
            rt,
            idempotency_key="k1",
            claim_token=claim.claim_token,
            failure_category="provider",
        )
        record = gen_req_repo.get_generation_request_by_key(rt, "k1")
        assert record is not None
        assert record.status == "failed"
        assert record.failed_at is not None
        assert record.failure_category == "provider"
        assert record.edition_id is None
        conn.close()

    def test_fail_with_wrong_token_raises(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
            claim_token="token-a",
        )
        with pytest.raises(gen_req_repo.GenerationRequestError):
            gen_req_repo.fail_generation_request(
                rt,
                idempotency_key="k1",
                claim_token="token-wrong",
                failure_category="provider",
            )
        conn.close()

    def test_failed_request_can_be_reclaimed_by_same_owner(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        claim = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
        )
        gen_req_repo.fail_generation_request(
            rt,
            idempotency_key="k1",
            claim_token=claim.claim_token,
            failure_category="provider",
        )
        reclaimed = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
        )
        assert reclaimed.already_claimed is False
        assert reclaimed.status == "claimed"
        assert reclaimed.failed_at is None
        assert reclaimed.failure_category is None
        conn.close()

    def test_failed_request_reclaim_by_different_owner_raises(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id_p1 = _setup(conn, pid="p1")
        input_id_p2 = _setup(conn, pid="p2")
        rt = SqliteRuntimeConnection(conn)

        claim = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id_p1,
        )
        gen_req_repo.fail_generation_request(
            rt,
            idempotency_key="k1",
            claim_token=claim.claim_token,
            failure_category="provider",
        )
        with pytest.raises(gen_req_repo.GenerationRequestOwnershipError):
            gen_req_repo.claim_generation_request(
                rt,
                idempotency_key="k1",
                participant_id="p2",
                input_id=input_id_p2,
            )
        conn.close()

    def test_claim_rejects_empty_key(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)

        with pytest.raises(gen_req_repo.GenerationRequestError):
            gen_req_repo.claim_generation_request(
                SqliteRuntimeConnection(conn),
                idempotency_key="   ",
                participant_id="p1",
                input_id=input_id,
            )
        conn.close()

    def test_claim_rejects_empty_input_id(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup(conn)

        with pytest.raises(gen_req_repo.GenerationRequestError):
            gen_req_repo.claim_generation_request(
                SqliteRuntimeConnection(conn),
                idempotency_key="k1",
                participant_id="p1",
                input_id="  ",
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
