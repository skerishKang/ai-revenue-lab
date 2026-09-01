"""Tests for durable Engine idempotency binding adapter."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from padiem_ai_core import (
    B14RouteMetadata,
    ExecutionResult,
    IdempotencyConflictError,
    RunMetadata,
    RunStatus,
)

from app.idempotency_binding import CloudflareD1IdempotencyAdapter


class FakeD1Statement:
    def __init__(self, db: "FakeD1", sql: str) -> None:
        self._db = db
        self._sql = sql
        self._params = ()

    def bind(self, *params):
        self._params = params
        return self

    async def first(self):
        if not self._sql.startswith("SELECT"):
            raise AssertionError(f"unexpected first sql: {self._sql}")
        app_id, key = self._params
        row = self._db.records.get((app_id, key))
        return dict(row) if row is not None else None

    async def run(self):
        sql = self._sql
        params = self._params
        if sql.startswith("INSERT INTO"):
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
        if sql.startswith("UPDATE") and params[0] == "aborted":
            state, result_json, updated_at, app_id, key, not_state = params
            record = self._db.records[(app_id, key)]
            if record["state"] != not_state:
                record["state"] = state
                record["result_json"] = result_json
                record["updated_at"] = updated_at
            return {"success": True}
        if sql.startswith("DELETE"):
            if len(params) == 3:
                app_id, key, not_state = params
                expected_expires_at = None
            else:
                app_id, key, not_state, expected_expires_at = params
            record = self._db.records.get((app_id, key))
            if record is not None and record["state"] != not_state:
                if expected_expires_at is None or record["expires_at"] == expected_expires_at:
                    del self._db.records[(app_id, key)]
            return {"success": True}
        raise AssertionError(f"unexpected run sql: {sql}")


class FakeD1:
    def __init__(self) -> None:
        self.records = {}
        self.sql = []

    def prepare(self, sql: str) -> FakeD1Statement:
        self.sql.append(sql)
        return FakeD1Statement(self, sql)


def _result(answer: str = "cached answer") -> ExecutionResult:
    return ExecutionResult(
        answer=answer,
        route=B14RouteMetadata(selected_provider="mock_provider", selected_model="mock_model"),
        metadata=RunMetadata(
            trace_id="tr_idem",
            app_id="b62",
            agent_id="agent:padiem:orchestrator_1",
            status=RunStatus.COMPLETED,
        ),
    )


def test_durable_idempotency_binding_reserves_completes_and_replays() -> None:
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)

    first = asyncio.run(adapter.begin(app_id="b62", idempotency_key="idem_1", request_fingerprint="f" * 64))
    assert first is None
    assert db.records[("b62", "idem_1")]["state"] == "reserved"

    asyncio.run(
        adapter.complete(
            app_id="b62",
            idempotency_key="idem_1",
            request_fingerprint="f" * 64,
            result=_result(),
        )
    )

    replay = asyncio.run(adapter.begin(app_id="b62", idempotency_key="idem_1", request_fingerprint="f" * 64))
    assert isinstance(replay, ExecutionResult)
    assert replay.answer == "cached answer"
    assert replay.metadata.app_id == "b62"
    assert replay.metadata.status is RunStatus.COMPLETED


def test_durable_idempotency_binding_rejects_same_key_different_fingerprint() -> None:
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)

    asyncio.run(adapter.begin(app_id="b62", idempotency_key="idem_2", request_fingerprint="a" * 64))

    with pytest.raises(IdempotencyConflictError):
        asyncio.run(adapter.begin(app_id="b62", idempotency_key="idem_2", request_fingerprint="b" * 64))


def test_durable_idempotency_binding_is_app_scoped() -> None:
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)

    asyncio.run(adapter.begin(app_id="b62", idempotency_key="shared", request_fingerprint="a" * 64))
    second_app = asyncio.run(adapter.begin(app_id="b61", idempotency_key="shared", request_fingerprint="b" * 64))

    assert second_app is None
    assert ("b62", "shared") in db.records
    assert ("b61", "shared") in db.records


def test_expired_reserved_idempotency_key_is_recovered_without_replay_or_conflict() -> None:
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    db.records[("b62", "stale")] = {
        "app_id": "b62",
        "idempotency_key": "stale",
        "request_fingerprint": "a" * 64,
        "state": "reserved",
        "result_json": None,
        "created_at": expired,
        "updated_at": expired,
        "expires_at": expired,
    }

    recovered = asyncio.run(adapter.begin(app_id="b62", idempotency_key="stale", request_fingerprint="b" * 64))

    assert recovered is None
    record = db.records[("b62", "stale")]
    assert record["state"] == "reserved"
    assert record["request_fingerprint"] == "b" * 64
    assert any("expires_at=?" in sql for sql in db.sql)


def test_completed_idempotency_record_replays_even_after_reservation_recovery_window() -> None:
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    db.records[("b62", "done")] = {
        "app_id": "b62",
        "idempotency_key": "done",
        "request_fingerprint": "c" * 64,
        "state": "completed",
        "result_json": json.dumps(_result("old cached answer").to_public_dict()),
        "created_at": expired,
        "updated_at": expired,
        "expires_at": expired,
    }

    replay = asyncio.run(adapter.begin(app_id="b62", idempotency_key="done", request_fingerprint="c" * 64))

    assert isinstance(replay, ExecutionResult)
    assert replay.answer == "old cached answer"
    assert db.records[("b62", "done")]["state"] == "completed"


def test_worker_injects_idempotency_binding_without_process_local_fake_store() -> None:
    source = (Path(__file__).resolve().parents[1] / "worker.py").read_text(encoding="utf-8")

    assert "ENGINE_IDEMPOTENCY" in source
    assert "CloudflareD1IdempotencyAdapter" in source
    assert "idempotency_adapter=idempotency_adapter" in source
    assert "InMemory" not in source
    assert "process-local fake" in source


def test_adapter_does_not_create_runtime_schema_or_mutate_production_config() -> None:
    adapter_source = (Path(__file__).resolve().parents[1] / "app" / "idempotency_binding.py").read_text(
        encoding="utf-8"
    )
    wrangler_source = (Path(__file__).resolve().parents[1] / "wrangler.toml").read_text(encoding="utf-8")

    assert "CREATE TABLE" not in adapter_source.upper()
    assert "ENGINE_IDEMPOTENCY" not in wrangler_source
