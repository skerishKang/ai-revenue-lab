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
        assert second.claim_token is None
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


class TestFinalizeEditionForRequest:
    def test_finalize_creates_edition_and_completes_request(self):
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
        edition = ed_repo.finalize_edition_for_request(
            rt,
            participant_id="p1",
            idempotency_key="k1",
            claim_token=claim.claim_token,
            structured_content='{"sections": []}',
            rendered_title="Finalized",
            input_id=input_id,
        )
        assert edition.id
        assert edition.generation_status == "pending_review"
        assert edition.publication_state == "pending"

        record = gen_req_repo.get_generation_request_by_key(rt, "k1")
        assert record is not None
        assert record.status == "completed"
        assert record.edition_id == edition.id
        assert record.completed_at is not None
        conn.close()

    def test_finalize_with_wrong_token_raises(self):
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
        with pytest.raises(ed_repo.EditionStateConflict):
            ed_repo.finalize_edition_for_request(
                rt,
                participant_id="p1",
                idempotency_key="k1",
                claim_token="token-wrong",
                structured_content='{"sections": []}',
                rendered_title="Bad",
                input_id=input_id,
            )
        conn.close()

    def test_finalize_unclaimed_key_raises(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        with pytest.raises(ed_repo.EditionStateConflict):
            ed_repo.finalize_edition_for_request(
                rt,
                participant_id="p1",
                idempotency_key="never-claimed",
                claim_token="any-token",
                structured_content='{"sections": []}',
                rendered_title="Bad",
            )
        conn.close()

    def test_finalize_replay_returns_existing_edition(self):
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
        edition = ed_repo.finalize_edition_for_request(
            rt,
            participant_id="p1",
            idempotency_key="k1",
            claim_token=claim.claim_token,
            structured_content='{"sections": []}',
            rendered_title="First",
            input_id=input_id,
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

        editions = ed_repo.get_editions_by_participant(rt, "p1")
        assert len(editions) == 1
        conn.close()


class TestFinalizerOwnership:
    def test_wrong_participant_raises_ownership_error(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn, pid="p1")
        _setup(conn, pid="p2")
        rt = SqliteRuntimeConnection(conn)

        claim = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
        )
        with pytest.raises(ed_repo.GenerationRequestOwnershipError):
            ed_repo.finalize_edition_for_request(
                rt,
                participant_id="p2",
                idempotency_key="k1",
                claim_token=claim.claim_token,
                structured_content='{"sections": []}',
                rendered_title="Bad",
                input_id=input_id,
            )
        editions = ed_repo.get_editions_by_participant(rt, "p1")
        assert len(editions) == 0
        conn.close()

    def test_wrong_input_raises_ownership_error(self):
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
        with pytest.raises(ed_repo.GenerationRequestOwnershipError):
            ed_repo.finalize_edition_for_request(
                rt,
                participant_id="p1",
                idempotency_key="k1",
                claim_token=claim.claim_token,
                structured_content='{"sections": []}',
                rendered_title="Bad",
                input_id=input_id_p2,
            )
        editions = ed_repo.get_editions_by_participant(rt, "p1")
        assert len(editions) == 0
        conn.close()

    def test_stale_token_after_completion_raises(self):
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
        ed_repo.finalize_edition_for_request(
            rt,
            participant_id="p1",
            idempotency_key="k1",
            claim_token=claim.claim_token,
            structured_content='{"sections": []}',
            rendered_title="First",
            input_id=input_id,
        )
        with pytest.raises(ed_repo.EditionStateConflict):
            ed_repo.finalize_edition_for_request(
                rt,
                participant_id="p1",
                idempotency_key="k1",
                claim_token=claim.claim_token,
                structured_content='{"sections": []}',
                rendered_title="Second",
                input_id=input_id,
            )
        editions = ed_repo.get_editions_by_participant(rt, "p1")
        assert len(editions) == 1
        conn.close()

    def test_expired_lease_with_valid_token_succeeds(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        claim = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
            lease_duration_seconds=1,
            now="2026-01-01T00:00:00.000Z",
        )
        edition = ed_repo.finalize_edition_for_request(
            rt,
            participant_id="p1",
            idempotency_key="k1",
            claim_token=claim.claim_token,
            structured_content='{"sections": []}',
            rendered_title="Late",
            input_id=input_id,
        )
        assert edition.id is not None
        record = gen_req_repo.get_generation_request_by_key(rt, "k1")
        assert record is not None
        assert record.status == "completed"
        conn.close()

    def test_failure_leaves_no_partial_rows(self):
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
        with pytest.raises(ed_repo.GenerationRequestOwnershipError):
            ed_repo.finalize_edition_for_request(
                rt,
                participant_id="wrong-owner",
                idempotency_key="k1",
                claim_token=claim.claim_token,
                structured_content='{"sections": []}',
                rendered_title="Bad",
                input_id=input_id,
            )
        editions = ed_repo.get_editions_by_participant(rt, "p1")
        assert len(editions) == 0
        record = gen_req_repo.get_generation_request_by_key(rt, "k1")
        assert record is not None
        assert record.status == "claimed"
        conn.close()


class TestClaimTokenCapability:
    def test_duplicate_claim_returns_no_token(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        first = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
        )
        assert first.claim_token is not None

        dup = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
        )
        assert dup.already_claimed is True
        assert dup.claim_token is None
        conn.close()

    def test_completed_replay_returns_no_token(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        edition = ed_repo.create_edition(
            rt,
            participant_id="p1",
            structured_content='{"sections": []}',
            rendered_title="T",
        )
        claim = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
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
        assert replay.claim_token is None
        conn.close()

    def test_terminal_row_has_null_token_and_lease(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        input_id = _setup(conn)
        rt = SqliteRuntimeConnection(conn)

        edition = ed_repo.create_edition(
            rt,
            participant_id="p1",
            structured_content='{"sections": []}',
            rendered_title="T",
        )
        claim = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k1",
            participant_id="p1",
            input_id=input_id,
        )
        gen_req_repo.complete_generation_request(
            rt,
            idempotency_key="k1",
            edition_id=edition.id,
            claim_token=claim.claim_token,
        )
        row = conn.execute(
            "SELECT claim_token, lease_expires_at FROM generation_requests "
            "WHERE idempotency_key = 'k1'"
        ).fetchone()
        assert row["claim_token"] is None
        assert row["lease_expires_at"] is None

        claim2 = gen_req_repo.claim_generation_request(
            rt,
            idempotency_key="k2",
            participant_id="p1",
            input_id=input_id,
        )
        gen_req_repo.fail_generation_request(
            rt,
            idempotency_key="k2",
            claim_token=claim2.claim_token,
            failure_category="provider",
        )
        row2 = conn.execute(
            "SELECT claim_token, lease_expires_at FROM generation_requests "
            "WHERE idempotency_key = 'k2'"
        ).fetchone()
        assert row2["claim_token"] is None
        assert row2["lease_expires_at"] is None
        conn.close()


class TestSchemaStateConstraints:
    def _raw_insert(self, conn, **overrides):
        defaults = dict(
            id="r1",
            idempotency_key="k1",
            participant_id="p1",
            input_id="i1",
            edition_id=None,
            status="claimed",
            claim_token="tok",
            lease_expires_at="2026-01-01T01:00:00.000Z",
            failed_at=None,
            failure_category=None,
            created_at="2026-01-01T00:00:00.000Z",
            completed_at=None,
            updated_at="2026-01-01T00:00:00.000Z",
        )
        defaults.update(overrides)
        conn.execute(
            "INSERT INTO generation_requests "
            "(id, idempotency_key, participant_id, input_id, edition_id, "
            "status, claim_token, lease_expires_at, failed_at, "
            "failure_category, created_at, completed_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                defaults["id"],
                defaults["idempotency_key"],
                defaults["participant_id"],
                defaults["input_id"],
                defaults["edition_id"],
                defaults["status"],
                defaults["claim_token"],
                defaults["lease_expires_at"],
                defaults["failed_at"],
                defaults["failure_category"],
                defaults["created_at"],
                defaults["completed_at"],
                defaults["updated_at"],
            ),
        )

    def _make_db(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        rt = SqliteRuntimeConnection(conn)
        repo.create_participant(
            rt, participant_id="p1", display_name="T", preferred_language="ko"
        )
        conn.execute(
            "INSERT INTO inputs (id, participant_id, sequence_number, raw_text, "
            "consent_confirmed, submitted_at) VALUES ('i1', 'p1', 1, 'text', 1, "
            "'2026-01-01T00:00:00.000Z')"
        )
        conn.commit()
        return conn

    def test_valid_claimed_insert_succeeds(self):
        conn = self._make_db()
        self._raw_insert(conn)
        conn.commit()
        conn.close()

    def test_valid_completed_insert_succeeds(self):
        conn = self._make_db()
        conn.execute(
            "INSERT INTO editions (id, participant_id, edition_number, "
            "generation_status, structured_content, rendered_title, "
            "publication_state, drafted_at) VALUES "
            "('e1', 'p1', 1, 'pending_review', '{}', 'T', 'pending', "
            "'2026-01-01T00:00:00.000Z')"
        )
        self._raw_insert(
            conn,
            status="completed",
            edition_id="e1",
            completed_at="2026-01-01T00:01:00.000Z",
            claim_token=None,
            lease_expires_at=None,
        )
        conn.commit()
        conn.close()

    def test_valid_failed_insert_succeeds(self):
        conn = self._make_db()
        self._raw_insert(
            conn,
            status="failed",
            failed_at="2026-01-01T00:01:00.000Z",
            failure_category="provider",
            claim_token=None,
            lease_expires_at=None,
        )
        conn.commit()
        conn.close()

    def test_claimed_without_lease_fails(self):
        conn = self._make_db()
        with pytest.raises(Exception):
            self._raw_insert(conn, lease_expires_at=None)
            conn.commit()
        conn.close()

    def test_claimed_with_failed_at_fails(self):
        conn = self._make_db()
        with pytest.raises(Exception):
            self._raw_insert(conn, failed_at="2026-01-01T00:01:00.000Z")
            conn.commit()
        conn.close()

    def test_completed_without_edition_fails(self):
        conn = self._make_db()
        with pytest.raises(Exception):
            self._raw_insert(
                conn,
                status="completed",
                edition_id=None,
                completed_at="2026-01-01T00:01:00.000Z",
                claim_token=None,
                lease_expires_at=None,
            )
            conn.commit()
        conn.close()

    def test_completed_with_claim_token_fails(self):
        conn = self._make_db()
        conn.execute(
            "INSERT INTO editions (id, participant_id, edition_number, "
            "generation_status, structured_content, rendered_title, "
            "publication_state, drafted_at) VALUES "
            "('e1', 'p1', 1, 'pending_review', '{}', 'T', 'pending', "
            "'2026-01-01T00:00:00.000Z')"
        )
        with pytest.raises(Exception):
            self._raw_insert(
                conn,
                status="completed",
                edition_id="e1",
                completed_at="2026-01-01T00:01:00.000Z",
                claim_token="should-be-null",
                lease_expires_at=None,
            )
            conn.commit()
        conn.close()

    def test_failed_without_category_fails(self):
        conn = self._make_db()
        with pytest.raises(Exception):
            self._raw_insert(
                conn,
                status="failed",
                failed_at="2026-01-01T00:01:00.000Z",
                failure_category=None,
                claim_token=None,
                lease_expires_at=None,
            )
            conn.commit()
        conn.close()

    def test_failed_with_completed_at_fails(self):
        conn = self._make_db()
        with pytest.raises(Exception):
            self._raw_insert(
                conn,
                status="failed",
                failed_at="2026-01-01T00:01:00.000Z",
                failure_category="provider",
                completed_at="2026-01-01T00:02:00.000Z",
                claim_token=None,
                lease_expires_at=None,
            )
            conn.commit()
        conn.close()
