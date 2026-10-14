"""#3933 S1 — B54 first-turn trusted coding-context authority tests.

Network-free. Proves the S1 invariants at the store contract level (real
SQLite + additive migration 043 through D1-style prepared bindings) and at
the route level (real Starlette app, hermetic doubles only):

* the gate is a no-op under the OFF default — existing behavior unchanged;
* missing canonical subject OR tenant fails closed pre-quota on first turn;
* exactly one atomic claim may win per grant; losers get status-only 409;
* replay after an uncertain dispatch never re-dispatches;
* proven non-dispatch terminally fails the grant; revocation/expiry are
  honored; orphan cleanup is owner-scoped and bounded;
* live SSE and completed paths share the same gate.

Reuses #4538 (test_3936_b54_p01_conversation_authority_seam) for the
already-satisfied seam assertions; nothing here duplicates them.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.claw_first_turn_authority import (
    B54_PRODUCT_ID,
    B54VerifiedCodingContextV1,
    D1FirstTurnGrantStore,
    FIRST_TURN_ROUTE_SCOPES,
    FirstTurnAuthorityError,
    GRANT_TTL_SECONDS,
    InMemoryFirstTurnGrantStore,
    STATE_ACTIVE,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_RESERVED,
    STATE_REVOKED,
    claim_first_turn_grant,
    correlation_for,
    reserve_first_turn_grant,
)
from app.history import validate_conversation_id

import test_b54_claw_general_p01_routing as base

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
GRANT_SQL = (MIGRATIONS / "043_claw_coding_conversation_grant.sql").read_text(
    encoding="utf-8"
)

OWNER = base.SIGNED_IN_USER_ID
FOREIGN = "usr_" + "b" * 32
SUBJECT = "sub_" + "c" * 32
FOREIGN_SUBJECT = "sub_" + "d" * 32
TENANT = "tenant_test_3933_s1"
OTHER_TENANT = "tenant_other_3933_s1"
SCOPE = "claw_general_execute"

FIXED_NOW = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)


class D1Statement:
    def __init__(self, connection, sql, values=()):
        self.conn, self.sql, self.values = connection, sql, values

    def bind(self, *values):
        return D1Statement(self.conn, self.sql, values)

    async def first(self):
        row = self.conn.execute(self.sql, self.values).fetchone()
        # D1 auto-commits every request; the double must too, otherwise
        # cross-connection reads (the genuine concurrency proof) see nothing
        # and close() rolls the write back.
        self.conn.commit()
        return dict(row) if row is not None else None

    async def run(self):
        cursor = self.conn.execute(self.sql, self.values)
        rows = cursor.fetchall()
        self.conn.commit()

        class _Meta:
            pass

        result = SimpleNamespace(results=[dict(row) for row in rows], meta=None)
        return result


class D1Sqlite:
    def __init__(self, connection):
        self.connection = connection

    def prepare(self, sql):
        return D1Statement(self.connection, sql)


def _grant_db():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(GRANT_SQL)
    db.commit()
    return db


def _grant_file_db_path():
    # Shared on-disk DB so racing threads can hold *independent* connections
    # the way independent D1 requests do. Sharing one sqlite3 connection
    # across threads is not thread-safe (CI flakes with InterfaceError) and
    # proves nothing about DB-side arbitration.
    fd, path = tempfile.mkstemp(prefix="grant_3933_", suffix=".sqlite3")
    os.close(fd)
    db = sqlite3.connect(path, check_same_thread=False, timeout=30)
    try:
        db.row_factory = sqlite3.Row
        db.executescript(GRANT_SQL)
        db.execute("PRAGMA journal_mode=WAL")
        db.commit()
    finally:
        db.close()
    return path


def _open_grant_db(path):
    db = sqlite3.connect(path, check_same_thread=False, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def _count_file_rows(path):
    db = _open_grant_db(path)
    try:
        return db.execute(
            "SELECT COUNT(*) AS n FROM claw_coding_conversation_grant"
        ).fetchone()["n"]
    finally:
        db.close()


def _inputs(**over):
    values = {
        "user_id": OWNER,
        "subject_id": SUBJECT,
        "tenant_id": TENANT,
        "route_scope": SCOPE,
    }
    values.update(over)
    return values


def _request(*, enabled=True, store=None):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                claw_first_turn_grant_enabled=enabled,
                claw_first_turn_grant_store=store,
            )
        )
    )


def _reserve_now(store, _now=FIXED_NOW, **over):
    with patch("app.claw_first_turn_authority._utcnow", return_value=_now):
        return asyncio.run(
            reserve_first_turn_grant(_request(store=store), **_inputs(**over))
        )


class TestGrantContractShape(unittest.TestCase):
    def test_migration_043_is_additive_only(self):
        lowered = GRANT_SQL.lower()
        assert "create table if not exists claw_coding_conversation_grant" in lowered
        assert "where state in ('reserved', 'active')" in lowered
        assert "check (product_id = 'b54-padiem-claw')" in lowered
        for forbidden in (
            "alter table",
            "drop table",
            "delete from",
            "create index claw_run_history",
            "references",
        ):
            assert forbidden not in lowered, forbidden

    def test_context_rejects_any_untrusted_shape(self):
        good = {
            "version": "b54-verified-coding-context.v1",
            "issuer": "b54-first-turn-authority",
            "product_id": B54_PRODUCT_ID,
            "user_id": OWNER,
            "subject_id": SUBJECT,
            "tenant_id": TENANT,
            "conversation_ref": "chat_" + "e" * 32,
            "route_scope": SCOPE,
            "issued_at": "2026-10-13T12:00:00.000Z",
            "expires_at": "2026-10-13T12:10:00.000Z",
            "correlation_key": "k" * 64,
            "grant_id": "cg_" + "f" * 32,
        }
        B54VerifiedCodingContextV1(**good)
        import pytest

        bad_variants = [
            {"issuer": "browser"},
            {"product_id": "b62-padiem-chat"},
            {"subject_id": "usr_forged"},
            {"tenant_id": ""},
            {"conversation_ref": "chat_evil"},
            {"route_scope": "claw_general_execute_wide"},
            {"expires_at": "2026-10-13T12:00:00.000Z"},
            {"correlation_key": ""},
            {"grant_id": ""},
        ]
        for variant in bad_variants:
            mutated = dict(good)
            mutated.update(variant)
            with pytest.raises(ValueError):
                B54VerifiedCodingContextV1(**mutated)

    def test_correlation_is_deterministic_and_server_derived(self):
        first = correlation_for(OWNER, SUBJECT, TENANT, B54_PRODUCT_ID, SCOPE)
        second = correlation_for(OWNER, SUBJECT, TENANT, B54_PRODUCT_ID, SCOPE)
        assert first == second and len(first) == 64
        assert correlation_for(OWNER, SUBJECT, OTHER_TENANT, B54_PRODUCT_ID, SCOPE) != first
        assert correlation_for(FOREIGN, SUBJECT, TENANT, B54_PRODUCT_ID, SCOPE) != first


class TestD1GrantStore(unittest.TestCase):
    def setUp(self):
        self.db = _grant_db()
        self.addCleanup(self.db.close)
        self.store = D1FirstTurnGrantStore(D1Sqlite(self.db))

    def _count_rows(self):
        return self.db.execute(
            "SELECT COUNT(*) AS n FROM claw_coding_conversation_grant"
        ).fetchone()["n"]

    def _row(self, grant_id):
        return self.db.execute(
            "SELECT * FROM claw_coding_conversation_grant WHERE id=?", (grant_id,)
        ).fetchone()

    def test_reserve_claim_complete_lifecycle(self):
        context = _reserve_now(self.store)
        assert isinstance(context, B54VerifiedCodingContextV1)
        assert validate_conversation_id(context.conversation_ref) is not None
        assert context.conversation_ref != context.grant_id
        assert self._row(context.grant_id)["state"] == STATE_RESERVED

        assert asyncio.run(claim_first_turn_grant(self.store, context)) is True
        assert self._row(context.grant_id)["state"] == STATE_ACTIVE

        settled = asyncio.run(
            self.store.settle(
                context.grant_id,
                OWNER,
                STATE_COMPLETED,
                "2026-10-13T12:01:00.000Z",
                run_ref="run_" + "1" * 24,
                saved_conversation_id=context.conversation_ref,
            )
        )
        assert settled is not None
        row = self._row(context.grant_id)
        assert row["state"] == STATE_COMPLETED
        assert row["run_ref"] == "run_" + "1" * 24
        assert row["saved_conversation_id"] == context.conversation_ref

    def test_double_reserve_same_correlation_elects_single_row(self):
        first = _reserve_now(self.store)
        second = _reserve_now(self.store)
        assert self._count_rows() == 1
        assert first.grant_id == second.grant_id
        assert first.conversation_ref == second.conversation_ref

    def test_attach_with_mismatched_bindings_is_denied(self):
        # A live row under the same (user, correlation) but foreign bindings
        # can only exist via out-of-band writes; the attach path must deny it
        # instead of inheriting its conversation reference.
        correlation = correlation_for(OWNER, SUBJECT, TENANT, B54_PRODUCT_ID, SCOPE)
        self.db.execute(
            "INSERT INTO claw_coding_conversation_grant "
            "(id,user_id,subject_id,tenant_id,product_id,route_scope,"
            "conversation_ref,correlation_key,state,issued_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "cg_planted", OWNER, FOREIGN_SUBJECT, TENANT, B54_PRODUCT_ID,
                SCOPE, "chat_" + "4" * 32, correlation, STATE_RESERVED,
                "2026-10-13T12:00:00.000Z", "2026-10-13T12:10:00.000Z",
            ),
        )
        self.db.commit()
        with patch(
            "app.claw_first_turn_authority._utcnow", return_value=FIXED_NOW
        ):
            with self.assertRaises(FirstTurnAuthorityError) as denied:
                asyncio.run(
                    reserve_first_turn_grant(
                        _request(store=self.store), **_inputs()
                    )
                )
        assert denied.exception.status_code == 403
        assert denied.exception.code == "first_turn_grant_unavailable"
        assert self._count_rows() == 1

    def test_second_claim_loses_and_terminal_claims_fail(self):
        context = _reserve_now(self.store)
        assert asyncio.run(claim_first_turn_grant(self.store, context)) is True
        assert asyncio.run(claim_first_turn_grant(self.store, context)) is False
        assert (
            asyncio.run(
                self.store.settle(
                    context.grant_id, FOREIGN, STATE_COMPLETED, "2026-10-13T12:01:00Z"
                )
            )
            is None
        )
        assert (
            asyncio.run(
                self.store.settle(
                    context.grant_id, OWNER, STATE_COMPLETED, "2026-10-13T12:01:00Z"
                )
            )
            is not None
        )
        assert asyncio.run(claim_first_turn_grant(self.store, context)) is False

    def test_claim_revalidates_bindings_and_expiry(self):
        import dataclasses

        context = _reserve_now(self.store)
        forged = dataclasses.replace(context, tenant_id=OTHER_TENANT)
        assert asyncio.run(claim_first_turn_grant(self.store, forged)) is False
        late = (FIXED_NOW + timedelta(seconds=GRANT_TTL_SECONDS + 1)).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        assert (
            asyncio.run(
                self.store.claim(
                    context.grant_id, OWNER, SUBJECT, TENANT, late
                )
            )
            is None
        )

    def test_replay_after_terminal_mints_fresh(self):
        context = _reserve_now(self.store)
        assert asyncio.run(claim_first_turn_grant(self.store, context)) is True
        asyncio.run(
            self.store.settle(
                context.grant_id, OWNER, STATE_COMPLETED, "2026-10-13T12:01:00Z"
            )
        )
        replayed = _reserve_now(self.store)
        assert replayed.grant_id != context.grant_id
        assert replayed.conversation_ref != context.conversation_ref
        assert self._count_rows() == 2

    def test_status_reads_are_mutation_free(self):
        context = _reserve_now(self.store)
        first = asyncio.run(
            self.store.status_by_correlation(OWNER, context.correlation_key)
        )
        second = asyncio.run(
            self.store.status_by_correlation(OWNER, context.correlation_key)
        )
        assert first == second
        assert first["state"] == STATE_RESERVED
        assert self._row(context.grant_id)["state"] == STATE_RESERVED
        assert (
            asyncio.run(self.store.status_by_correlation(FOREIGN, context.correlation_key))
            is None
        )

    def test_cleanup_is_owner_scoped_bounded_and_reserved_only(self):
        live = _reserve_now(self.store)
        asyncio.run(claim_first_turn_grant(self.store, live))
        stale_iso = (FIXED_NOW - timedelta(seconds=1)).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        self.db.execute(
            "INSERT INTO claw_coding_conversation_grant "
            "(id,user_id,subject_id,tenant_id,product_id,route_scope,"
            "conversation_ref,correlation_key,state,issued_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "cg_stale1", OWNER, SUBJECT, TENANT, B54_PRODUCT_ID, SCOPE,
                "chat_" + "1" * 32, "corr-stale-1", STATE_RESERVED,
                "2026-10-13T11:00:00.000Z", stale_iso,
            ),
        )
        self.db.execute(
            "INSERT INTO claw_coding_conversation_grant "
            "(id,user_id,subject_id,tenant_id,product_id,route_scope,"
            "conversation_ref,correlation_key,state,issued_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "cg_stale2", OWNER, SUBJECT, TENANT, B54_PRODUCT_ID, SCOPE,
                "chat_" + "2" * 32, "corr-stale-2", STATE_RESERVED,
                "2026-10-13T11:00:00.000Z", stale_iso,
            ),
        )
        self.db.execute(
            "INSERT INTO claw_coding_conversation_grant "
            "(id,user_id,subject_id,tenant_id,product_id,route_scope,"
            "conversation_ref,correlation_key,state,issued_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "cg_foreign", FOREIGN, SUBJECT, TENANT, B54_PRODUCT_ID, SCOPE,
                "chat_" + "3" * 32, "corr-foreign", STATE_RESERVED,
                "2026-10-13T11:00:00.000Z", stale_iso,
            ),
        )
        self.db.commit()
        removed = asyncio.run(
            self.store.cleanup_abandoned(OWNER, _iso_now(), 1)
        )
        assert removed == 1
        remaining = {
            row["id"]
            for row in self.db.execute(
                "SELECT id FROM claw_coding_conversation_grant"
            ).fetchall()
        }
        assert live.grant_id in remaining
        assert "cg_foreign" in remaining
        assert len(remaining) == 3

    def test_concurrent_reserve_elects_exactly_one_row(self):
        path = _grant_file_db_path()
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        barrier = threading.Barrier(2)
        outcomes: list = []
        errors: list = []

        def attempt():
            db = _open_grant_db(path)
            try:
                store = D1FirstTurnGrantStore(D1Sqlite(db))
                barrier.wait(timeout=10)
                outcomes.append(_reserve_now(store))
            except Exception as exc:  # fail loudly, never as a count mismatch
                errors.append(exc)
            finally:
                db.close()

        workers = [threading.Thread(target=attempt) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        assert all(not worker.is_alive() for worker in workers)
        assert not errors, errors
        assert len(outcomes) == 2
        assert _count_file_rows(path) == 1
        assert outcomes[0].grant_id == outcomes[1].grant_id

    def test_expired_active_grant_releases_key_for_next_turn(self):
        from unittest.mock import patch as _patch

        from datetime import timedelta as _timedelta

        with _patch(
            "app.claw_first_turn_authority._utcnow", return_value=FIXED_NOW
        ):
            first = _reserve_now(self.store)
            assert asyncio.run(claim_first_turn_grant(self.store, first)) is True
        later = FIXED_NOW + _timedelta(seconds=GRANT_TTL_SECONDS + 600)
        second = _reserve_now(self.store, _now=later)
        assert second.grant_id != first.grant_id
        assert self._row(first.grant_id)["state"] == STATE_FAILED
        assert self._row(second.grant_id)["state"] == STATE_RESERVED

    def test_concurrent_claim_elects_exactly_one_winner(self):
        path = _grant_file_db_path()
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        seed = _open_grant_db(path)
        try:
            context = _reserve_now(D1FirstTurnGrantStore(D1Sqlite(seed)))
        finally:
            seed.close()
        barrier = threading.Barrier(2)
        outcomes: list = []
        errors: list = []

        def attempt():
            db = _open_grant_db(path)
            try:
                store = D1FirstTurnGrantStore(D1Sqlite(db))
                barrier.wait(timeout=10)
                outcomes.append(
                    asyncio.run(claim_first_turn_grant(store, context))
                )
            except Exception as exc:  # fail loudly, never as a count mismatch
                errors.append(exc)
            finally:
                db.close()

        workers = [threading.Thread(target=attempt) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        assert all(not worker.is_alive() for worker in workers)
        assert not errors, errors
        assert sorted(outcomes) == [False, True]


def _iso_now():
    return FIXED_NOW.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class TestInMemoryGrantStoreParity(unittest.TestCase):
    def test_parity_on_winner_attach_and_guarded_transitions(self):
        store = InMemoryFirstTurnGrantStore()
        first = _reserve_now(store)
        second = _reserve_now(store)
        assert first.grant_id == second.grant_id
        assert asyncio.run(claim_first_turn_grant(store, first)) is True
        assert asyncio.run(claim_first_turn_grant(store, second)) is False
        view = asyncio.run(store.status_by_correlation(OWNER, first.correlation_key))
        assert view is not None and view["state"] == STATE_ACTIVE
        assert asyncio.run(store.cleanup_abandoned(OWNER, _iso_now(), 10)) == 0

    def test_revoke_and_expiry_close_the_grant(self):
        store = InMemoryFirstTurnGrantStore()
        context = _reserve_now(store)
        assert (
            asyncio.run(
                store.settle(
                    context.grant_id, OWNER, STATE_REVOKED, _iso_now(),
                    from_states=(STATE_RESERVED, STATE_ACTIVE),
                )
            )
            is not None
        )
        assert asyncio.run(claim_first_turn_grant(store, context)) is False
        fresh = _reserve_now(store)
        assert fresh.grant_id != context.grant_id


class _S1History:
    """Minimal owner history double: first-turn save mints a server id."""

    def __init__(self):
        self.saved = []
        self.threads = {}

    async def get_user(self, user_id):
        return None

    async def get_conversation(self, user_id, conversation_id):
        return self.threads.get(conversation_id)

    async def append_exchange(
        self, user_id, conversation_id, user_text, answer, project_id=None
    ):
        self.saved.append((user_id, conversation_id, user_text, answer))
        if conversation_id is not None:
            return conversation_id
        return "chat_" + "9" * 32


_DEFAULT_BRIDGE = object()


def _bridge(*, subject=SUBJECT, tenant=TENANT):
    return SimpleNamespace(
        auth_session=SimpleNamespace(
            subject=SimpleNamespace(subject_id=subject),
            tenant_id=tenant,
        )
    )


@contextmanager
def _s1_client(*, store, adapter, bridge=_DEFAULT_BRIDGE, flag=True, history=None):
    settings = base._settings()
    app = create_app(
        settings=settings,
        history_store=history if history is not None else _S1History(),
        claw_p01_adapter=adapter,
    )
    with TestClient(app, base_url="https://chat.example.test") as client:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, base.SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        client.app.state.claw_first_turn_grant_enabled = flag
        if store is not None:
            client.app.state.claw_first_turn_grant_store = store
        resolved = _bridge() if bridge is _DEFAULT_BRIDGE else bridge
        with patch(
            "app.b54_canonical_session.resolve_current_b54_canonical_session",
            new=AsyncMock(return_value=resolved),
        ):
            yield client


def _first_turn_post(client):
    return client.post(
        base.GENERAL_ROUTE_PATH,
        json=base._payload(messages=[{"role": "user", "content": "첫 턴입니다."}]),
    )


class TestFirstTurnGateRoute(unittest.TestCase):
    def test_flag_off_keeps_historical_first_turn_byte_identical(self):
        store = InMemoryFirstTurnGrantStore()
        adapter = base._make_adapter(subject_lane=True)
        with _s1_client(store=store, adapter=adapter, flag=False) as client:
            response = _first_turn_post(client)
        assert response.status_code == 200, response.text
        adapter.execute.assert_awaited_once()
        assert store._rows == {}

    def test_flag_on_without_subject_lane_fails_closed(self):
        store = InMemoryFirstTurnGrantStore()
        adapter = base._make_adapter(subject_lane=False)
        with _s1_client(store=store, adapter=adapter, flag=True) as client:
            response = _first_turn_post(client)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "canonical_b54_session_unavailable"
        adapter.execute.assert_not_awaited()
        assert store._rows == {}

    def test_flag_on_first_turn_without_tenant_fails_closed_pre_quota(self):
        store = InMemoryFirstTurnGrantStore()
        adapter = base._make_adapter(subject_lane=True)
        with _s1_client(
            store=store, adapter=adapter, flag=True,
            bridge=_bridge(tenant=None),
        ) as client:
            response = _first_turn_post(client)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "workspace_scope_unavailable"
        adapter.execute.assert_not_awaited()
        assert store._rows == {}

    def test_flag_on_without_store_fails_closed(self):
        adapter = base._make_adapter(subject_lane=True)
        with _s1_client(store=None, adapter=adapter, flag=True) as client:
            response = _first_turn_post(client)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "first_turn_grant_unavailable"
        adapter.execute.assert_not_awaited()

    def test_flag_on_first_turn_reserves_claims_and_completes(self):
        store = InMemoryFirstTurnGrantStore()
        adapter = base._make_adapter(subject_lane=True)
        with _s1_client(store=store, adapter=adapter, flag=True) as client:
            response = _first_turn_post(client)
        assert response.status_code == 200, response.text
        adapter.execute.assert_awaited_once()
        assert len(store._rows) == 1
        row = next(iter(store._rows.values()))
        assert row["state"] == STATE_COMPLETED
        assert row["user_id"] == OWNER
        assert row["subject_id"] == SUBJECT
        assert row["tenant_id"] == TENANT
        assert row["run_ref"].startswith("run_")
        assert row["saved_conversation_id"] == "chat_" + "9" * 32
        # Reserved ref is the server-minted candidate; the stored id is the
        # history-confirmed authority the client always sees.
        assert validate_conversation_id(row["conversation_ref"]) is not None
        assert row["conversation_ref"] != row["saved_conversation_id"]
        assert '"conversation_id":"chat_' in response.text

    def test_preclaimed_grant_yields_status_only_409_without_redispatch(self):
        store = InMemoryFirstTurnGrantStore()
        adapter = base._make_adapter(subject_lane=True)
        correlation = correlation_for(OWNER, SUBJECT, TENANT, B54_PRODUCT_ID, SCOPE)
        with patch(
            "app.claw_first_turn_authority._utcnow", return_value=FIXED_NOW
        ):
            preseed = asyncio.run(
                reserve_first_turn_grant(
                    _request(store=store), **_inputs()
                )
            )
            assert asyncio.run(claim_first_turn_grant(store, preseed)) is True
            with _s1_client(store=store, adapter=adapter, flag=True) as client:
                response = _first_turn_post(client)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "first_turn_dispatch_in_progress"
        adapter.execute.assert_not_awaited()

    def test_ambiguous_dispatch_stays_active_and_replay_gets_409(self):
        from kagent.p01_adapter import P01AdapterError

        store = InMemoryFirstTurnGrantStore()
        adapter = base._make_adapter(subject_lane=True)
        adapter.execute = AsyncMock(
            side_effect=P01AdapterError("probe_transport_timeout", "…")
        )
        with patch(
            "app.claw_first_turn_authority._utcnow", return_value=FIXED_NOW
        ):
            with _s1_client(store=store, adapter=adapter, flag=True) as client:
                first = _first_turn_post(client)
                assert first.status_code == 502
                replay = _first_turn_post(client)
                assert replay.status_code == 409
                assert replay.json()["error"]["code"] == "first_turn_dispatch_in_progress"
        assert adapter.execute.await_count == 1
        rows = list(store._rows.values())
        assert len(rows) == 1 and rows[0]["state"] == STATE_ACTIVE

    def test_proven_nondispatch_fails_grant_and_next_turn_proceeds(self):
        from kagent.p01_adapter import P01AdapterError, P01DispatchClass

        store = InMemoryFirstTurnGrantStore()
        adapter = base._make_adapter(subject_lane=True)
        adapter.execute = AsyncMock(
            side_effect=P01AdapterError(
                "probe_not_dispatched", "…",
                dispatch_class=P01DispatchClass.NOT_DISPATCHED,
            )
        )
        with patch(
            "app.claw_first_turn_authority._utcnow", return_value=FIXED_NOW
        ):
            with _s1_client(store=store, adapter=adapter, flag=True) as client:
                first = _first_turn_post(client)
                assert first.status_code == 502
                adapter.execute = AsyncMock(
                    return_value=base._make_outcome()
                )
                client.app.state.claw_p01_adapter = adapter
                second = _first_turn_post(client)
                assert second.status_code == 200, second.text
        assert adapter.execute.await_count == 1
        states = sorted(row["state"] for row in store._rows.values())
        assert states == [STATE_COMPLETED, STATE_FAILED]

    def test_revoked_grant_frees_the_key_for_a_fresh_turn(self):
        store = InMemoryFirstTurnGrantStore()
        adapter = base._make_adapter(subject_lane=True)
        with patch(
            "app.claw_first_turn_authority._utcnow", return_value=FIXED_NOW
        ):
            seeded = asyncio.run(
                reserve_first_turn_grant(_request(store=store), **_inputs())
            )
            assert (
                asyncio.run(
                    store.settle(
                        seeded.grant_id, OWNER, STATE_REVOKED, _iso_now(),
                        from_states=(STATE_RESERVED, STATE_ACTIVE),
                    )
                )
                is not None
            )
            with _s1_client(store=store, adapter=adapter, flag=True) as client:
                response = _first_turn_post(client)
        assert response.status_code == 200, response.text
        assert len(store._rows) == 2

    def test_forged_conversation_id_never_reaches_the_gate(self):
        store = InMemoryFirstTurnGrantStore()
        adapter = base._make_adapter(subject_lane=True)
        with _s1_client(store=store, adapter=adapter, flag=True) as client:
            response = client.post(
                base.GENERAL_ROUTE_PATH,
                json=base._payload(
                    conversation_id="chat_" + "f" * 32,
                    messages=[{"role": "user", "content": "위조"}],
                ),
            )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "conversation_not_found"
        adapter.execute.assert_not_awaited()
        assert store._rows == {}

    def test_guest_creates_no_grant_and_never_dispatches(self):
        store = InMemoryFirstTurnGrantStore()
        adapter = base._make_adapter(subject_lane=True)
        settings = base._settings()
        app = create_app(
            settings=settings, history_store=_S1History(), claw_p01_adapter=adapter
        )
        with TestClient(app, base_url="https://chat.example.test") as client:
            client.app.state.claw_first_turn_grant_enabled = True
            client.app.state.claw_first_turn_grant_store = store
            response = _first_turn_post(client)
        assert response.status_code == 403
        adapter.execute.assert_not_awaited()
        assert store._rows == {}

    def test_continuation_path_is_untouched_by_the_flag(self):
        history = _S1History()
        thread = "chat_" + "5" * 32
        history.threads[thread] = {
            "id": thread,
            "project_id": None,
            "messages": [{"role": "user", "content": "이전"}],
        }
        store = InMemoryFirstTurnGrantStore()
        adapter = base._make_adapter(subject_lane=True)
        with _s1_client(
            store=store, adapter=adapter, flag=True, history=history
        ) as client:
            response = client.post(
                base.GENERAL_ROUTE_PATH,
                json=base._payload(
                    conversation_id=thread,
                    messages=[{"role": "user", "content": "이어서"}],
                ),
            )
        assert response.status_code == 200, response.text
        adapter.execute.assert_awaited_once()
        assert store._rows == {}

    def test_evidence_422_after_claim_fails_grant_and_next_turn_proceeds(self):
        from test_3930_b54_live_sse_relay import HEADERS as LIVE_HEADERS
        from test_3930_b54_live_sse_relay import _streaming_adapter

        store = InMemoryFirstTurnGrantStore()
        adapter = _streaming_adapter()
        with patch(
            "app.claw_first_turn_authority._utcnow", return_value=FIXED_NOW
        ):
            with _s1_client(store=store, adapter=adapter, flag=True) as client:
                client.app.state.claw_live_sse_enabled = True
                denied = client.post(
                    base.GENERAL_ROUTE_PATH,
                    json=base._payload(
                        messages=[{"role": "user", "content": "증거모드"}]
                    ),
                    headers={
                        **LIVE_HEADERS,
                        "X-Padiem-Claw-Evidence": "one-shot",
                    },
                )
                assert denied.status_code == 422, denied.text
                rows = list(store._rows.values())
                assert len(rows) == 1 and rows[0]["state"] == STATE_FAILED
                adapter.execute = AsyncMock(return_value=base._make_outcome())
                client.app.state.claw_p01_adapter = adapter
                retried = _first_turn_post(client)
                assert retried.status_code == 200, retried.text
        states = sorted(row["state"] for row in store._rows.values())
        assert states == [STATE_COMPLETED, STATE_FAILED]

    def test_expired_active_grant_unblocks_next_turn_after_ttl(self):
        from datetime import timedelta as _timedelta

        from kagent.p01_adapter import P01AdapterError

        store = InMemoryFirstTurnGrantStore()
        adapter = base._make_adapter(subject_lane=True)
        adapter.execute = AsyncMock(
            side_effect=P01AdapterError("probe_transport_timeout", "…")
        )
        with patch(
            "app.claw_first_turn_authority._utcnow", return_value=FIXED_NOW
        ):
            with _s1_client(store=store, adapter=adapter, flag=True) as client:
                first = _first_turn_post(client)
                assert first.status_code == 502
        later = FIXED_NOW + _timedelta(seconds=GRANT_TTL_SECONDS + 600)
        adapter.execute = AsyncMock(return_value=base._make_outcome())
        with patch("app.claw_first_turn_authority._utcnow", return_value=later):
            with _s1_client(store=store, adapter=adapter, flag=True) as client:
                second = _first_turn_post(client)
                assert second.status_code == 200, second.text
        states = sorted(row["state"] for row in store._rows.values())
        assert states == [STATE_COMPLETED, STATE_FAILED]

    def test_complete_with_forged_saved_id_fails_grant_instead(self):
        from app.claw_first_turn_authority import complete_first_turn_grant

        store = InMemoryFirstTurnGrantStore()
        with patch(
            "app.claw_first_turn_authority._utcnow", return_value=FIXED_NOW
        ):
            context = _reserve_now(store)
            assert asyncio.run(claim_first_turn_grant(store, context)) is True
            asyncio.run(
                complete_first_turn_grant(
                    _request(store=store),
                    context,
                    run_ref="run_" + "1" * 24,
                    saved_conversation_id="garbage-not-a-chat-id",
                )
            )
        rows = list(store._rows.values())
        assert len(rows) == 1
        assert rows[0]["state"] == STATE_FAILED
        assert rows[0]["saved_conversation_id"] is None

    def test_live_sse_and_completed_share_the_same_gate(self):
        from test_3930_b54_live_sse_relay import HEADERS as LIVE_HEADERS
        from test_3930_b54_live_sse_relay import _streaming_adapter

        store = InMemoryFirstTurnGrantStore()
        adapter = _streaming_adapter()
        with _s1_client(store=store, adapter=adapter, flag=True) as client:
            client.app.state.claw_live_sse_enabled = True
            response = client.post(
                base.GENERAL_ROUTE_PATH,
                json=base._payload(
                    messages=[{"role": "user", "content": "실시간 첫 턴"}]
                ),
                headers=LIVE_HEADERS,
            )
        assert response.status_code == 200, response.text
        assert "event: p01_event" in response.text
        rows = list(store._rows.values())
        assert len(rows) == 1 and rows[0]["state"] == STATE_COMPLETED


class TestFirstTurnAuthorityBoundaries(unittest.TestCase):
    def test_flag_and_store_default_off_in_factory(self):
        source = (
            Path(__file__).resolve().parents[1] / "app" / "app_factory.py"
        ).read_text(encoding="utf-8")
        assert "app.state.claw_first_turn_grant_enabled = False" in source
        assert "app.state.claw_first_turn_grant_store = None" in source

    def test_migration_source_is_never_applied_by_app_code(self):
        app_dir = Path(__file__).resolve().parents[1] / "app"
        hits = [
            path.name
            for path in app_dir.glob("*.py")
            if "043_claw_coding_conversation_grant" in path.read_text(encoding="utf-8")
        ]
        assert hits == []

    def test_authority_module_stays_out_of_downstream_contracts(self):
        repo = Path(__file__).resolve().parents[3]
        engine_identity = (
            repo / "apps" / "padiem-ai-engine" / "app" / "orchestration_identity_service.py"
        ).read_text(encoding="utf-8")
        kagent_adapter = (
            repo / "apps" / "korean-ai-code-agent" / "src" / "kagent" / "p01_adapter.py"
        ).read_text(encoding="utf-8")
        assert "claw_first_turn" not in engine_identity
        assert "claw_first_turn" not in kagent_adapter

    def test_route_imports_only_the_b54_private_surface(self):
        app_dir = Path(__file__).resolve().parents[1] / "app"
        importers = [
            path.name
            for path in app_dir.glob("*.py")
            if path.name != "claw_first_turn_authority.py"
            and "claw_first_turn_authority" in path.read_text(encoding="utf-8")
        ]
        assert sorted(importers) == ["claw_general_routes.py"]
