"""Tests for the #1964 completed-execution idempotency replay source slice.

These tests lock the governance boundary: the replay service reuses the exact
trusted durable adapter records that Core's contextual execution writes, never
re-executes, never fabricates results, and fails closed without the adapter.
The manifest feature stays DEFERRED (blockers document #1235).
"""

from __future__ import annotations

import json

import pytest

from padiem_ai_core import (
    B14RouteMetadata,
    ExecutionResult,
    RunMetadata,
    RunStatus,
)

from app.contract_manifest import EngineFeatureState, current_engine_contract_manifest
from app.idempotency_binding import CloudflareD1IdempotencyAdapter
from app.idempotency_replay_service import (
    IDEMPOTENCY_COMPLETED_REPLAY_PATH,
    IdempotencyReplayEngineService,
)


def _replay_payload(execution_id: str = "exec_1", app_id: str = "b62") -> bytes:
    return json.dumps({"app_id": app_id, "execution_id": execution_id}).encode("utf-8")


async def _complete_via_adapter(
    adapter: CloudflareD1IdempotencyAdapter,
    *,
    app_id: str = "b62",
    idempotency_key: str = "exec_1",
    answer: str = "cached answer",
) -> None:
    reservation = await adapter.begin(
        app_id=app_id, idempotency_key=idempotency_key, request_fingerprint="f" * 64
    )
    assert reservation is None
    result = ExecutionResult(
        answer=answer,
        route=B14RouteMetadata(selected_provider="mock_provider", selected_model="mock_model"),
        metadata=RunMetadata(
            trace_id="tr_replay",
            app_id=app_id,
            agent_id="agent:padiem:replay_1",
            status=RunStatus.COMPLETED,
        ),
    )
    await adapter.complete(
        app_id=app_id,
        idempotency_key=idempotency_key,
        request_fingerprint="f" * 64,
        result=result.to_public_dict(),
    )


def test_service_rejects_non_trusted_adapter() -> None:
    with pytest.raises(ValueError):
        IdempotencyReplayEngineService(idempotency_adapter=object())


@pytest.mark.asyncio
async def test_replay_requires_post_json_and_known_path() -> None:
    service = IdempotencyReplayEngineService(idempotency_adapter=None)

    not_found = await service.handle(
        method="POST", path="/internal/v1/idempotency/completed/other"
    )
    assert not_found.status_code == 404

    method_not_allowed = await service.handle(
        method="GET", path=IDEMPOTENCY_COMPLETED_REPLAY_PATH, content_type="application/json"
    )
    assert method_not_allowed.status_code == 405

    unsupported_media = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="text/plain",
    )
    assert unsupported_media.status_code == 415


@pytest.mark.asyncio
async def test_replay_validates_body_and_execution_id() -> None:
    service = IdempotencyReplayEngineService(idempotency_adapter=None)

    invalid_json = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=b"{not-json",
    )
    assert invalid_json.status_code == 400
    assert invalid_json.body["error"]["code"] == "invalid_json"

    missing_execution_id = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=json.dumps({"app_id": "b62"}).encode("utf-8"),
    )
    assert missing_execution_id.status_code == 400

    unsafe_execution_id = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(execution_id="../escape"),
    )
    assert unsafe_execution_id.status_code == 400


@pytest.mark.asyncio
async def test_replay_fails_closed_without_trusted_adapter() -> None:
    service = IdempotencyReplayEngineService(idempotency_adapter=None)

    response = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(),
    )
    assert response.status_code == 503
    assert response.body["error"]["code"] == "idempotency_unavailable"


@pytest.mark.asyncio
async def test_replay_returns_completed_result_from_durable_record() -> None:
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)
    await _complete_via_adapter(adapter)
    service = IdempotencyReplayEngineService(idempotency_adapter=adapter)

    response = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(),
    )
    assert response.status_code == 200
    assert response.body["ok"] is True
    assert response.body["replayed"] is True
    assert response.body["execution_id"] == "exec_1"
    assert response.body["result"]["answer"] == "cached answer"
    assert response.body["result"]["metadata"]["status"] == "completed"


@pytest.mark.asyncio
async def test_unknown_execution_id_reports_not_replayed_without_error() -> None:
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)
    service = IdempotencyReplayEngineService(idempotency_adapter=adapter)

    response = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(execution_id="exec_missing"),
    )
    assert response.status_code == 200
    assert response.body["replayed"] is False
    assert response.body["reason"] == "completed_execution_not_found"


@pytest.mark.asyncio
async def test_reserved_or_aborted_records_are_never_replayed() -> None:
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)
    await adapter.begin(app_id="b62", idempotency_key="exec_reserved", request_fingerprint="f" * 64)
    await adapter.begin(app_id="b62", idempotency_key="exec_abort_me", request_fingerprint="f" * 64)
    await adapter.abort(app_id="b62", idempotency_key="exec_abort_me", reason="test")
    service = IdempotencyReplayEngineService(idempotency_adapter=adapter)

    reserved = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(execution_id="exec_reserved"),
    )
    assert reserved.status_code == 200
    assert reserved.body["replayed"] is False

    aborted = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(execution_id="exec_abort_me"),
    )
    assert aborted.status_code == 200
    assert aborted.body["replayed"] is False


@pytest.mark.asyncio
async def test_app_scope_is_not_crossed() -> None:
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)
    await _complete_via_adapter(adapter, app_id="b62", idempotency_key="exec_scope")
    service = IdempotencyReplayEngineService(idempotency_adapter=adapter)

    cross_app = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(execution_id="exec_scope", app_id="b63"),
    )
    assert cross_app.status_code == 200
    assert cross_app.body["replayed"] is False


@pytest.mark.asyncio
async def test_replay_never_mutates_durable_records() -> None:
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)
    await _complete_via_adapter(adapter)
    before = dict(db.records[("b62", "exec_1")])
    service = IdempotencyReplayEngineService(idempotency_adapter=adapter)

    await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(),
    )
    assert db.records[("b62", "exec_1")] == before


def test_manifest_endpoint_declared_but_feature_stays_deferred() -> None:
    manifest = current_engine_contract_manifest()
    endpoints = {(item.method, item.path) for item in manifest.endpoints}

    assert ("POST", IDEMPOTENCY_COMPLETED_REPLAY_PATH) in endpoints
    # Governance: #1235 blockers document forbids the AVAILABLE transition
    # before production activation blockers are proven in a separate PR.
    assert (
        manifest.feature_state("execution_idempotency_replay_completed")
        is EngineFeatureState.DEFERRED
    )


# --- Durable fake shared with the adapter test conventions -------------------


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
            app_id, key, not_state = params[-3], params[-2], params[-1]
            record = self._db.records.get((app_id, key))
            if record is not None and record["state"] != not_state:
                del self._db.records[(app_id, key)]
            return {"success": True}
        raise AssertionError(f"unexpected run sql: {sql}")


class FakeD1:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict] = {}
        self.sql: list[str] = []

    def prepare(self, sql: str) -> FakeD1Statement:
        self.sql.append(sql)
        return FakeD1Statement(self, sql)
