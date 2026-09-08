"""Durable product-command idempotency conformance over the shared Engine adapter.

Proves the #1565 promoted semantics execute against the exact
``CloudflareD1IdempotencyAdapter`` used by the canonical Worker: first command
reserves once, exact duplicates replay from durable state, material changes
conflict fail closed, workspaces never share a record, terminal replays never
resurrect, and a broken durable binding never falls back to process-local state.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.idempotency_binding import CloudflareD1IdempotencyAdapter
from padiem_ai_core.execution_context import IdempotencyConflictError
from padiem_ai_core.product_command_identity import (
    ProductCommandIdempotency,
    ProductCommandIdentity,
    ProductCommandReservationOutcome,
)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def identity(**changes):
    values = dict(
        workspace_id="ws_1",
        command_id="command_1",
        idempotency_key="idem_1",
        kind="create_rfq_draft",
        subject_ref="rfq/quote-1",
        subject_version=1,
        payload_sha256="a" * 64,
        session_ref="session_1",
        requested_at=NOW,
    )
    values.update(changes)
    return ProductCommandIdentity(**values)


class FakeD1Statement:
    def __init__(self, db: "FakeD1", sql: str) -> None:
        self._db = db
        self._sql = sql
        self._params = ()

    def bind(self, *params):
        self._params = params
        return self

    async def first(self):
        app_id, key = self._params
        row = self._db.records.get((app_id, key))
        return dict(row) if row is not None else None

    async def run(self):
        sql = self._sql
        params = self._params
        if sql.startswith("INSERT INTO"):
            self._db.inserts += 1
            app_id, key, fp, state, result_json, created_at, updated_at, expires_at = params
            self._db.records[(app_id, key)] = {
                "app_id": app_id,
                "idempotency_key": key,
                "request_fingerprint": fp,
                "state": state,
                "result_json": result_json,
                "created_at": created_at,
                "updated_at": updated_at,
                "expires_at": expires_at,
            }
            return {"success": True}
        if sql.startswith("UPDATE") and params[0] == "completed":
            state, result_json, updated_at, app_id, key, fp = params
            record = self._db.records[(app_id, key)]
            assert record["request_fingerprint"] == fp
            record["state"] = state
            record["result_json"] = result_json
            record["updated_at"] = updated_at
            return {"success": True}
        raise AssertionError(f"unexpected run sql: {sql}")


class FakeD1:
    def __init__(self) -> None:
        self.records = {}
        self.inserts = 0

    def prepare(self, sql: str) -> FakeD1Statement:
        return FakeD1Statement(self, sql)


class BrokenD1:
    def prepare(self, sql: str):
        raise RuntimeError("D1 binding unavailable")


def _service(db: FakeD1) -> ProductCommandIdempotency:
    return ProductCommandIdempotency(
        adapter=CloudflareD1IdempotencyAdapter(db),
        app_id="b54",
    )


def test_first_product_command_reserves_durable_record_once():
    db = FakeD1()
    service = _service(db)
    decision = asyncio.run(service.reserve(identity()))
    assert decision.outcome is ProductCommandReservationOutcome.ACCEPTED
    assert db.inserts == 1
    record = db.records[("b54", decision.scoped_idempotency_key)]
    assert record["state"] == "reserved"
    assert record["request_fingerprint"] == decision.request_fingerprint


def test_exact_duplicate_replays_from_durable_record_without_redispatch():
    db = FakeD1()
    service = _service(db)
    first = asyncio.run(service.reserve(identity()))
    asyncio.run(service.complete(first.identity, result={"result_ref": "result_1", "status": "completed"}))
    replay = asyncio.run(service.reserve(identity()))
    assert replay.outcome is ProductCommandReservationOutcome.REPLAY
    assert replay.replay_result == {"result_ref": "result_1", "status": "completed"}
    assert db.inserts == 1


def test_material_change_under_same_key_conflicts_fail_closed():
    db = FakeD1()
    service = _service(db)
    asyncio.run(service.reserve(identity()))
    with pytest.raises(IdempotencyConflictError):
        asyncio.run(service.reserve(identity(payload_sha256="b" * 64)))
    assert db.inserts == 1


def test_in_flight_duplicate_cannot_double_dispatch():
    db = FakeD1()
    service = _service(db)
    asyncio.run(service.reserve(identity()))
    with pytest.raises(IdempotencyConflictError):
        asyncio.run(service.reserve(identity()))
    assert db.inserts == 1


def test_same_client_key_in_other_workspace_is_durable_isolated():
    db = FakeD1()
    service = _service(db)
    left = asyncio.run(service.reserve(identity(workspace_id="ws_1")))
    right = asyncio.run(service.reserve(identity(workspace_id="ws_2")))
    assert left.scoped_idempotency_key != right.scoped_idempotency_key
    assert db.inserts == 2
    asyncio.run(service.complete(left.identity, result={"result_ref": "result_left"}))
    with pytest.raises(IdempotencyConflictError):
        asyncio.run(service.reserve(identity(workspace_id="ws_2", payload_sha256="c" * 64)))
    leaked = asyncio.run(service.reserve(identity(workspace_id="ws_3")))
    assert leaked.outcome is ProductCommandReservationOutcome.ACCEPTED
    assert leaked.replay_result is None


def test_terminal_completed_command_replays_forever_without_resurrection():
    db = FakeD1()
    service = _service(db)
    first = asyncio.run(service.reserve(identity()))
    asyncio.run(service.complete(first.identity, result={"result_ref": "result_1"}))
    for _ in range(3):
        retry = asyncio.run(service.reserve(identity()))
        assert retry.outcome is ProductCommandReservationOutcome.REPLAY
        assert retry.replay_result == {"result_ref": "result_1"}
    assert db.inserts == 1
    record = db.records[("b54", first.scoped_idempotency_key)]
    assert record["state"] == "completed"


def test_durable_binding_failure_never_falls_back_to_local_state():
    service = ProductCommandIdempotency(
        adapter=CloudflareD1IdempotencyAdapter(BrokenD1()),
        app_id="b54",
    )
    with pytest.raises(RuntimeError):
        asyncio.run(service.reserve(identity()))
    assert set(vars(service)) == {"_adapter", "_app_id"}
