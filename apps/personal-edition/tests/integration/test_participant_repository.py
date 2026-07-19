import hmac
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app import participant_repository as repo
from app import security
from app.db import apply_migrations, get_connection


class TestMigration:
    def test_migrations_applied_in_order(self):
        conn = get_connection(":memory:")
        versions = apply_migrations(conn, "migrations")
        assert "001_initial.sql" in versions
        assert "002_participant_token_hash_unique.sql" in versions
        order = [
            v
            for v in versions
            if v in ("001_initial.sql", "002_participant_token_hash_unique.sql")
        ]
        assert order == [
            "001_initial.sql",
            "002_participant_token_hash_unique.sql",
        ]
        conn.close()

    def test_unique_token_hash_index_details(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        indices = conn.execute(
            "PRAGMA index_list(participants)"
        ).fetchall()
        target = [
            r
            for r in indices
            if r["name"] == "idx_participants_access_token_hash"
        ]
        assert len(target) == 1
        assert target[0]["unique"] == 1

        info = conn.execute(
            "PRAGMA index_info(idx_participants_access_token_hash)"
        ).fetchall()
        cols = [r["name"] for r in info]
        assert "access_token_hash" in cols
        conn.close()


class TestCreateParticipant:
    def test_create_stores_hash_only(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        result = repo.create_participant(
            conn,
            participant_id="p1",
            display_name="Test User",
            preferred_language="ko",
        )

        assert not hasattr(result.participant, "access_token_hash")
        assert result.one_time_token
        assert len(result.one_time_token) > 0

        row = conn.execute(
            "SELECT access_token_hash FROM participants WHERE id = ?",
            ("p1",),
        ).fetchone()
        assert row is not None
        assert len(row["access_token_hash"]) == 64
        conn.close()

    def test_no_raw_token_in_db_columns(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        cols = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(participants)"
            ).fetchall()
        }
        assert "access_token_hash" in cols
        assert "access_token" not in cols
        assert "raw_token" not in cols
        conn.close()

    def test_sentinel_raw_token_never_persists(self, monkeypatch):
        SENTINEL = "SENTINEL_RAW_TOKEN_DO_NOT_STORE"
        monkeypatch.setattr(security, "generate_token", lambda: SENTINEL)

        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        result = repo.create_participant(
            conn,
            participant_id="p-sentinel",
            display_name="Sentinel Test",
            preferred_language="ko",
        )

        col_row = conn.execute(
            "SELECT * FROM participants WHERE id = ?", ("p-sentinel",)
        ).fetchone()
        for key in col_row.keys():
            val = col_row[key]
            if isinstance(val, str):
                assert SENTINEL not in val, f"sentinel leaked in column {key}"

        for field_name in (
            "id",
            "display_name",
            "preferred_language",
            "status",
            "created_at",
            "updated_at",
        ):
            val = getattr(result.participant, field_name)
            if isinstance(val, str):
                assert (
                    SENTINEL not in val
                ), f"sentinel leaked in record.{field_name}"
        assert result.participant.deleted_at is None

        found_id = repo.get_participant_by_id(conn, "p-sentinel")
        for field_name in (
            "id",
            "display_name",
            "preferred_language",
            "status",
            "created_at",
            "updated_at",
        ):
            val = getattr(found_id, field_name)
            if isinstance(val, str):
                assert (
                    SENTINEL not in val
                ), f"sentinel leaked in id-lookup.{field_name}"

        found_tok = repo.get_active_participant_by_token(conn, SENTINEL)
        assert found_tok is not None
        for field_name in (
            "id",
            "display_name",
            "preferred_language",
            "status",
            "created_at",
            "updated_at",
        ):
            val = getattr(found_tok, field_name)
            if isinstance(val, str):
                assert (
                    SENTINEL not in val
                ), f"sentinel leaked in token-lookup.{field_name}"

        hash_row = conn.execute(
            "SELECT access_token_hash FROM participants WHERE id = ?",
            ("p-sentinel",),
        ).fetchone()
        assert hash_row[0] != SENTINEL
        assert len(hash_row[0]) == 64
        assert all(c in "0123456789abcdef" for c in hash_row[0])
        conn.close()

    def test_rejects_invalid_language(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        with pytest.raises(ValueError):
            repo.create_participant(
                conn,
                participant_id="p1",
                display_name="Test",
                preferred_language="fr",
            )
        conn.close()

    def test_rejects_blank_display_name(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        with pytest.raises(ValueError):
            repo.create_participant(
                conn,
                participant_id="p1",
                display_name="",
                preferred_language="ko",
            )
        with pytest.raises(ValueError):
            repo.create_participant(
                conn,
                participant_id="p2",
                display_name="   ",
                preferred_language="ko",
            )
        conn.close()

    def test_rejects_blank_participant_id(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        with pytest.raises(ValueError):
            repo.create_participant(
                conn,
                participant_id="",
                display_name="Test",
                preferred_language="ko",
            )
        with pytest.raises(ValueError):
            repo.create_participant(
                conn,
                participant_id="   ",
                display_name="Test",
                preferred_language="ko",
            )
        conn.close()

    def test_rejects_non_string_participant_id(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        with pytest.raises(TypeError):
            repo.create_participant(
                conn,
                participant_id=123,
                display_name="Test",
                preferred_language="ko",
            )
        conn.close()

    def test_rejects_whitespace_surrounded_participant_id(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        with pytest.raises(ValueError):
            repo.create_participant(
                conn,
                participant_id=" participant-1 ",
                display_name="Test",
                preferred_language="ko",
            )
        conn.close()

    def test_timestamps_are_utc_iso8601(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        result = repo.create_participant(
            conn,
            participant_id="p-ts",
            display_name="Test User",
            preferred_language="ko",
        )
        for field in ("created_at", "updated_at"):
            val = getattr(result.participant, field)
            assert "T" in val, f"{field} missing T"
            assert val.endswith("Z"), f"{field} missing trailing Z"
        conn.close()


class TestLookup:
    def test_lookup_by_correct_token_succeeds(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        result = repo.create_participant(
            conn,
            participant_id="p-lookup",
            display_name="Test User",
            preferred_language="ko",
        )
        found = repo.get_active_participant_by_token(
            conn, result.one_time_token
        )
        assert found is not None
        assert found.id == "p-lookup"
        assert found.display_name == "Test User"
        conn.close()

    def test_lookup_by_wrong_token_returns_none(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="p1",
            display_name="Test User",
            preferred_language="ko",
        )
        found = repo.get_active_participant_by_token(
            conn, "definitely-wrong-token"
        )
        assert found is None
        conn.close()

    def test_lookup_by_id_succeeds(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="p-byid",
            display_name="Test User",
            preferred_language="ko",
        )
        found = repo.get_participant_by_id(conn, "p-byid")
        assert found is not None
        assert found.id == "p-byid"
        assert found.display_name == "Test User"
        conn.close()

    def test_deleted_participant_not_returned_by_token(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        result = repo.create_participant(
            conn,
            participant_id="p-del",
            display_name="Test User",
            preferred_language="ko",
        )
        repo.delete_participant(conn, "p-del")

        found = repo.get_active_participant_by_token(
            conn, result.one_time_token
        )
        assert found is None
        conn.close()

    def test_constant_time_lookup_uses_hmac(self, monkeypatch):
        spy_calls = []
        original = hmac.compare_digest

        def spy(a, b):
            spy_calls.append((a, b))
            return original(a, b)

        monkeypatch.setattr(hmac, "compare_digest", spy)

        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        result = repo.create_participant(
            conn,
            participant_id="p-ct",
            display_name="Const Time",
            preferred_language="ko",
        )

        spy_calls.clear()
        found = repo.get_active_participant_by_token(
            conn, result.one_time_token
        )
        assert found is not None
        assert found.id == "p-ct"
        assert len(spy_calls) >= 1

        spy_calls.clear()
        wrong = repo.get_active_participant_by_token(
            conn, "wrong-token-value"
        )
        assert wrong is None
        assert len(spy_calls) == 0

        spy_calls.clear()
        found_again = repo.get_active_participant_by_token(
            conn, result.one_time_token
        )
        assert found_again is not None
        assert len(spy_calls) >= 1

        row = conn.execute(
            "SELECT access_token_hash FROM participants WHERE id = ?",
            ("p-ct",),
        ).fetchone()
        assert row["access_token_hash"] != result.one_time_token
        conn.close()


class TestDelete:
    def test_delete_sets_deleted_status_and_timestamp(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="p-delts",
            display_name="Test User",
            preferred_language="ko",
        )
        repo.delete_participant(conn, "p-delts")

        row = conn.execute(
            "SELECT status, deleted_at FROM participants WHERE id = ?",
            ("p-delts",),
        ).fetchone()
        assert row["status"] == "deleted"
        assert row["deleted_at"] is not None
        assert "T" in row["deleted_at"]
        assert row["deleted_at"].endswith("Z")
        conn.close()

    def test_delete_persists_after_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "test.db")
            conn = get_connection(db_path)
            apply_migrations(conn, "migrations")

            repo.create_participant(
                conn,
                participant_id="p-persists",
                display_name="Persist Test",
                preferred_language="ko",
            )
            result = repo.delete_participant(conn, "p-persists")
            assert result is True
            conn.close()

            conn2 = get_connection(db_path)
            row = conn2.execute(
                "SELECT status, deleted_at FROM participants "
                "WHERE id = ?",
                ("p-persists",),
            ).fetchone()
            assert row["status"] == "deleted"
            assert row["deleted_at"] is not None
            assert "T" in row["deleted_at"]
            assert row["deleted_at"].endswith("Z")

            found = repo.get_active_participant_by_token(
                conn2, "any-token"
            )
            assert found is None
            conn2.close()


class TestExistingTransaction:
    def test_create_rejects_existing_transaction(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        conn.execute("BEGIN")

        with pytest.raises(repo.RepositoryTransactionError):
            repo.create_participant(
                conn,
                participant_id="p1",
                display_name="Test",
                preferred_language="ko",
            )

        assert conn.in_transaction is True
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM participants"
        ).fetchone()["c"]
        assert cnt == 0
        conn.close()

    def test_create_does_not_generate_token_on_existing_tx(self, monkeypatch):
        call_count = [0]
        monkeypatch.setattr(
            security,
            "generate_token",
            lambda: (call_count.__setitem__(0, call_count[0] + 1) or "tok"),
        )

        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        conn.execute("BEGIN")

        with pytest.raises(repo.RepositoryTransactionError):
            repo.create_participant(
                conn,
                participant_id="p1",
                display_name="Test",
                preferred_language="ko",
            )

        assert call_count[0] == 0
        assert conn.in_transaction is True
        conn.close()

    def test_create_does_not_modify_caller_transaction(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        conn.execute("BEGIN")

        with pytest.raises(repo.RepositoryTransactionError):
            repo.create_participant(
                conn,
                participant_id="p1",
                display_name="Test",
                preferred_language="ko",
            )

        conn.execute(
            "INSERT INTO participants "
            "(id, display_name, access_token_hash, preferred_language, "
            "status, created_at, updated_at) "
            "VALUES (?, 'CallerRow', 'hash', 'ko', 'active', "
            "'2026-01-01', '2026-01-01')",
            ("caller-p1",),
        )
        conn.commit()
        assert conn.in_transaction is False
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM participants"
        ).fetchone()["c"]
        assert cnt == 1
        conn.close()

    def test_delete_rejects_existing_transaction(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="p1",
            display_name="First",
            preferred_language="ko",
        )

        conn.execute("BEGIN")
        with pytest.raises(repo.RepositoryTransactionError):
            repo.delete_participant(conn, "p1")

        assert conn.in_transaction is True
        row = conn.execute(
            "SELECT status FROM participants WHERE id = ?", ("p1",)
        ).fetchone()
        assert row["status"] == "active"
        conn.close()


class TestCollision:
    def test_token_collision_then_success(self, monkeypatch):
        tokens = iter(["collide", "collide", "unique"])
        monkeypatch.setattr(security, "generate_token", lambda: next(tokens))

        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="existing",
            display_name="First",
            preferred_language="ko",
        )

        result = repo.create_participant(
            conn,
            participant_id="new-one",
            display_name="Second",
            preferred_language="ko",
        )
        assert result.participant.id == "new-one"
        assert result.one_time_token == "unique"
        conn.close()

    def test_collision_retry_exhaustion(self, monkeypatch):
        monkeypatch.setattr(
            security, "generate_token", lambda: "always_same"
        )

        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="existing",
            display_name="First",
            preferred_language="ko",
        )

        with pytest.raises(repo.TokenProvisioningError) as excinfo:
            repo.create_participant(
                conn,
                participant_id="another",
                display_name="Second",
                preferred_language="ko",
            )
        assert "token" in str(excinfo.value).lower()
        conn.close()

    def test_collision_exhaustion_no_new_row(self, monkeypatch):
        monkeypatch.setattr(
            security, "generate_token", lambda: "always_same"
        )

        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="existing",
            display_name="First",
            preferred_language="ko",
        )

        count_before = conn.execute(
            "SELECT COUNT(*) AS c FROM participants"
        ).fetchone()["c"]

        with pytest.raises(repo.TokenProvisioningError):
            repo.create_participant(
                conn,
                participant_id="another",
                display_name="Second",
                preferred_language="ko",
            )

        count_after = conn.execute(
            "SELECT COUNT(*) AS c FROM participants"
        ).fetchone()["c"]
        assert count_after == count_before
        assert conn.in_transaction is False
        conn.close()

    def test_collision_exhaustion_connection_reusable(self, monkeypatch):
        monkeypatch.setattr(
            security, "generate_token", lambda: "always_same"
        )

        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="existing",
            display_name="First",
            preferred_language="ko",
        )

        with pytest.raises(repo.TokenProvisioningError):
            repo.create_participant(
                conn,
                participant_id="another",
                display_name="Second",
                preferred_language="ko",
            )

        assert conn.in_transaction is False
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM participants"
        ).fetchone()["c"]
        assert cnt == 1
        conn.close()

    def test_collision_exception_no_raw_token(self, monkeypatch):
        monkeypatch.setattr(
            security, "generate_token", lambda: "always_same"
        )

        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="existing",
            display_name="First",
            preferred_language="ko",
        )

        with pytest.raises(repo.TokenProvisioningError) as excinfo:
            repo.create_participant(
                conn,
                participant_id="another",
                display_name="Second",
                preferred_language="ko",
            )
        assert "always_same" not in str(excinfo.value)
        conn.close()

    def test_collision_does_not_change_participant_id(self, monkeypatch):
        tokens = iter(["collide", "collide", "final"])
        monkeypatch.setattr(security, "generate_token", lambda: next(tokens))

        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="existing",
            display_name="First",
            preferred_language="ko",
        )

        result = repo.create_participant(
            conn,
            participant_id="caller-provided-id",
            display_name="Second",
            preferred_language="ko",
        )
        assert result.participant.id == "caller-provided-id"
        conn.close()


class TestDuplicateId:
    def test_duplicate_id_raises_error(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="dup",
            display_name="First",
            preferred_language="ko",
        )

        with pytest.raises(repo.DuplicateParticipantError):
            repo.create_participant(
                conn,
                participant_id="dup",
                display_name="Second",
                preferred_language="ko",
            )
        conn.close()

    def test_duplicate_id_does_not_generate_token(self, monkeypatch):
        call_count = [0]
        monkeypatch.setattr(
            security,
            "generate_token",
            lambda: (
                call_count.__setitem__(0, call_count[0] + 1) or "tok"
            ),
        )

        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="dup",
            display_name="First",
            preferred_language="ko",
        )

        before = call_count[0]
        with pytest.raises(repo.DuplicateParticipantError):
            repo.create_participant(
                conn,
                participant_id="dup",
                display_name="Second",
                preferred_language="ko",
            )
        assert call_count[0] == before
        conn.close()

    def test_duplicate_id_does_not_change_existing(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        result = repo.create_participant(
            conn,
            participant_id="p1",
            display_name="Original",
            preferred_language="ko",
        )
        original_ts = result.participant.updated_at

        with pytest.raises(repo.DuplicateParticipantError):
            repo.create_participant(
                conn,
                participant_id="p1",
                display_name="Changed",
                preferred_language="en",
            )

        row = conn.execute(
            "SELECT display_name, preferred_language, "
            "access_token_hash, updated_at FROM participants WHERE id = ?",
            ("p1",),
        ).fetchone()
        assert row["display_name"] == "Original"
        assert row["preferred_language"] == "ko"
        assert row["updated_at"] == original_ts
        conn.close()

    def test_duplicate_id_row_count_unchanged(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="p1",
            display_name="First",
            preferred_language="ko",
        )

        with pytest.raises(repo.DuplicateParticipantError):
            repo.create_participant(
                conn,
                participant_id="p1",
                display_name="Second",
                preferred_language="ko",
            )

        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM participants"
        ).fetchone()["c"]
        assert cnt == 1
        conn.close()

    def test_duplicate_id_transaction_closed(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="p1",
            display_name="First",
            preferred_language="ko",
        )

        with pytest.raises(repo.DuplicateParticipantError):
            repo.create_participant(
                conn,
                participant_id="p1",
                display_name="Second",
                preferred_language="ko",
            )

        assert conn.in_transaction is False
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM participants"
        ).fetchone()["c"]
        assert cnt == 1
        conn.close()

    def test_duplicate_id_connection_reusable(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        repo.create_participant(
            conn,
            participant_id="p1",
            display_name="First",
            preferred_language="ko",
        )

        with pytest.raises(repo.DuplicateParticipantError):
            repo.create_participant(
                conn,
                participant_id="p1",
                display_name="Second",
                preferred_language="ko",
            )

        assert conn.in_transaction is False
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM participants"
        ).fetchone()["c"]
        assert cnt == 1
        conn.close()


class TestNoNetwork:
    def test_no_network_calls(self, monkeypatch):
        import socket

        monkeypatch.setattr(
            socket,
            "create_connection",
            lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("network call detected")
            ),
        )

        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        result = repo.create_participant(
            conn,
            participant_id="p-net",
            display_name="No Network",
            preferred_language="ko",
        )
        found = repo.get_active_participant_by_token(
            conn, result.one_time_token
        )
        assert found is not None
        repo.delete_participant(conn, "p-net")
        assert (
            repo.get_active_participant_by_token(
                conn, result.one_time_token
            )
            is None
        )
        conn.close()
