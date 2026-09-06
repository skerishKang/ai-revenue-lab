"""Tests for the #1964 completed-execution idempotency replay source slice.

These tests lock the governance boundary: the replay service reuses the exact
trusted durable adapter records that Core's contextual execution writes, never
re-executes, never fabricates results, and fails closed without the adapter.

CTO review conditions locked here:

- R1: replay is NOT lookup. The caller must present the original request's
  ``request_fingerprint``; a mismatched (or merely different) fingerprint is
  indistinguishable from "not found" and never discloses the cached result.
- R2: the service consumes only the adapter's public ``read_completed`` read
  surface (never private adapter methods).
- R4: the wire field is the Core-native ``idempotency_key``.

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

_FP = "f" * 64


def _replay_payload(
    idempotency_key: str = "exec_1",
    app_id: str = "b62",
    request_fingerprint: str | None = _FP,
) -> bytes:
    payload: dict[str, str] = {"app_id": app_id, "idempotency_key": idempotency_key}
    if request_fingerprint is not None:
        payload["request_fingerprint"] = request_fingerprint
    return json.dumps(payload).encode("utf-8")


async def _complete_via_adapter(
    adapter: CloudflareD1IdempotencyAdapter,
    *,
    app_id: str = "b62",
    idempotency_key: str = "exec_1",
    request_fingerprint: str = _FP,
    answer: str = "cached answer",
) -> None:
    reservation = await adapter.begin(
        app_id=app_id, idempotency_key=idempotency_key, request_fingerprint=request_fingerprint
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
        request_fingerprint=request_fingerprint,
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
async def test_replay_validates_body_and_idempotency_key() -> None:
    service = IdempotencyReplayEngineService(idempotency_adapter=None)

    invalid_json = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=b"{not-json",
    )
    assert invalid_json.status_code == 400
    assert invalid_json.body["error"]["code"] == "invalid_json"

    missing_key = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=json.dumps({"app_id": "b62", "request_fingerprint": _FP}).encode("utf-8"),
    )
    assert missing_key.status_code == 400

    unsafe_key = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(idempotency_key="../escape"),
    )
    assert unsafe_key.status_code == 400


@pytest.mark.asyncio
async def test_replay_requires_matching_request_fingerprint() -> None:
    """R1: replay is not lookup — the fingerprint is mandatory wire input."""
    service = IdempotencyReplayEngineService(idempotency_adapter=None)

    missing_fingerprint = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=json.dumps({"app_id": "b62", "idempotency_key": "exec_1"}).encode("utf-8"),
    )
    assert missing_fingerprint.status_code == 400

    for malformed in ("", "abc", "F" * 64, "g" * 64, _FP + "0", "a" * 63 + "G"):
        response = await service.handle(
            method="POST",
            path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
            content_type="application/json",
            body=_replay_payload(request_fingerprint=malformed),
        )
        assert response.status_code == 400, malformed


@pytest.mark.asyncio
async def test_replay_fingerprint_mismatch_never_discloses_result() -> None:
    """R1: a different fingerprint is indistinguishable from 'not found'."""
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)
    await _complete_via_adapter(adapter, request_fingerprint=_FP)
    service = IdempotencyReplayEngineService(idempotency_adapter=adapter)

    mismatched = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(request_fingerprint="a" * 64),
    )
    assert mismatched.status_code == 200
    assert mismatched.body["replayed"] is False
    assert mismatched.body["reason"] == "completed_execution_not_found"
    assert "result" not in mismatched.body


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
    assert response.body["idempotency_key"] == "exec_1"
    assert response.body["result"]["answer"] == "cached answer"
    assert response.body["result"]["metadata"]["status"] == "completed"


@pytest.mark.asyncio
async def test_unknown_idempotency_key_reports_not_replayed_without_error() -> None:
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)
    service = IdempotencyReplayEngineService(idempotency_adapter=adapter)

    response = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(idempotency_key="exec_missing"),
    )
    assert response.status_code == 200
    assert response.body["replayed"] is False
    assert response.body["reason"] == "completed_execution_not_found"


@pytest.mark.asyncio
async def test_reserved_or_aborted_records_are_never_replayed() -> None:
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)
    await adapter.begin(app_id="b62", idempotency_key="exec_reserved", request_fingerprint=_FP)
    await adapter.begin(app_id="b62", idempotency_key="exec_abort_me", request_fingerprint=_FP)
    await adapter.abort(app_id="b62", idempotency_key="exec_abort_me", reason="test")
    service = IdempotencyReplayEngineService(idempotency_adapter=adapter)

    reserved = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(idempotency_key="exec_reserved"),
    )
    assert reserved.status_code == 200
    assert reserved.body["replayed"] is False

    aborted = await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(idempotency_key="exec_abort_me"),
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
        body=_replay_payload(idempotency_key="exec_scope", app_id="b63"),
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


@pytest.mark.asyncio
async def test_replay_uses_only_public_read_surface() -> None:
    """R2: the service must go through the public read_completed method."""
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)
    await _complete_via_adapter(adapter)
    service = IdempotencyReplayEngineService(idempotency_adapter=adapter)
    assert hasattr(type(service._idempotency_adapter), "read_completed")

    # The replay probe itself must never attempt a write (INSERT/UPDATE/DELETE).
    # Statements issued by the begin/complete SETUP are excluded from the check.
    setup_statement_count = len(db.sql)
    await service.handle(
        method="POST",
        path=IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        content_type="application/json",
        body=_replay_payload(),
    )
    assert all(
        sql.startswith("SELECT") for sql in db.sql[setup_statement_count:]
    )


@pytest.mark.asyncio
async def test_adapter_read_completed_mirrors_begin_authority_semantics() -> None:
    """R2 direct: the public read surface is fingerprint-bound and read-only."""
    db = FakeD1()
    adapter = CloudflareD1IdempotencyAdapter(db)

    # A reservation still in flight is never replayable.
    await adapter.begin(app_id="b62", idempotency_key="exec_reserved", request_fingerprint=_FP)
    assert (
        await adapter.read_completed(
            app_id="b62", idempotency_key="exec_reserved", request_fingerprint=_FP
        )
        is None
    )

    # No record yet for the completed key.
    assert (
        await adapter.read_completed(
            app_id="b62", idempotency_key="exec_1", request_fingerprint=_FP
        )
        is None
    )

    await _complete_via_adapter(adapter)

    # Matching fingerprint reads the completed public result.
    completed = await adapter.read_completed(
        app_id="b62", idempotency_key="exec_1", request_fingerprint=_FP
    )
    assert isinstance(completed, dict)
    assert completed["answer"] == "cached answer"

    # Wrong fingerprint reads as None — never discloses the cached result.
    assert (
        await adapter.read_completed(
            app_id="b62", idempotency_key="exec_1", request_fingerprint="a" * 64
        )
        is None
    )
    # Cross-app scope reads as None.
    assert (
        await adapter.read_completed(
            app_id="b63", idempotency_key="exec_1", request_fingerprint=_FP
        )
        is None
    )
    # Read-only: the begin/complete setup wrote, but read_completed itself
    # must have issued only SELECT statements.
    completed_setup = next(
        i for i, sql in enumerate(db.sql) if sql.startswith("UPDATE")
    )
    assert all(
        sql.startswith("SELECT") for sql in db.sql[completed_setup + 1 :]
    )


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
