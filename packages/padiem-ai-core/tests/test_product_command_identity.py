"""Focused tests for the product-command idempotency projection (issue #1565).

The projection must answer the promoted semantics against the shared Core
IdempotencyAdapter contract: first reserve, exact-duplicate replay, material
conflict, cross-workspace isolation, terminal non-resurrection, no authority
minting, and fail-closed behavior without any process-local fallback.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from padiem_ai_core.execution_context import IdempotencyConflictError
from padiem_ai_core.product_command_identity import (
    PRODUCT_COMMAND_IDEMPOTENCY_AUTHORITY_MINTING,
    ProductCommandIdempotency,
    ProductCommandIdentity,
    ProductCommandReservation,
    ProductCommandReservationOutcome,
    product_command_material_fingerprint,
    product_command_scoped_key,
)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def identity(**changes):
    values = dict(
        workspace_id="ws_1",
        command_id="command_1",
        idempotency_key="idem_1",
        kind="start_cloud_run",
        subject_ref="run_1",
        subject_version=1,
        payload_sha256="a" * 64,
        session_ref="session_1",
        requested_at=NOW,
    )
    values.update(changes)
    return ProductCommandIdentity(**values)


class ProtocolIdempotencyAdapter:
    """Minimal adapter implementing only the Core IdempotencyAdapter protocol."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict] = {}
        self.inserts = 0

    async def begin(self, *, app_id, idempotency_key, request_fingerprint):
        record = self.records.get((app_id, idempotency_key))
        if record is not None:
            if record["request_fingerprint"] != request_fingerprint:
                raise IdempotencyConflictError("idempotency key is bound to a different request")
            if record["state"] == "completed":
                return dict(record["result"])
            raise IdempotencyConflictError("idempotency key is already reserved")
        self.inserts += 1
        self.records[(app_id, idempotency_key)] = {
            "state": "reserved",
            "request_fingerprint": request_fingerprint,
            "result": None,
        }
        return None

    async def complete(self, *, app_id, idempotency_key, request_fingerprint, result):
        record = self.records.get((app_id, idempotency_key))
        if record is None or record["request_fingerprint"] != request_fingerprint:
            raise IdempotencyConflictError("idempotency completion does not match reservation")
        record["state"] = "completed"
        record["result"] = dict(result)


def test_identity_rejects_unsafe_material_fields():
    with pytest.raises(ValueError):
        identity(payload_sha256="not-a-hash")
    with pytest.raises(ValueError):
        identity(subject_version=0)
    with pytest.raises(ValueError):
        identity(kind="kind with spaces")
    with pytest.raises(ValueError):
        identity(idempotency_key="x" * 257)
    with pytest.raises(ValueError):
        identity(requested_at=datetime(2026, 9, 8, 12, 0))


def test_material_fingerprint_excludes_selector_and_binds_material():
    base = identity()
    assert product_command_material_fingerprint(base) == product_command_material_fingerprint(identity())
    assert product_command_material_fingerprint(base) != product_command_material_fingerprint(
        replace(base, payload_sha256="b" * 64)
    )
    assert product_command_material_fingerprint(base) != product_command_material_fingerprint(
        replace(base, requested_at=NOW.replace(minute=12))
    )


def test_scoped_key_isolates_workspaces_for_same_client_key():
    left = identity(workspace_id="ws_1")
    right = identity(workspace_id="ws_2")
    assert product_command_scoped_key(left) != product_command_scoped_key(right)
    assert product_command_scoped_key(left) == product_command_scoped_key(identity(workspace_id="ws_1"))


def test_first_command_is_accepted_and_reserves_exactly_once():
    adapter = ProtocolIdempotencyAdapter()
    service = ProductCommandIdempotency(adapter=adapter, app_id="b54")
    decision = asyncio.run(service.reserve(identity()))
    assert decision.outcome is ProductCommandReservationOutcome.ACCEPTED
    assert decision.replay_result is None
    assert adapter.inserts == 1
    assert decision.to_public_dict()["outcome"] == "accepted"


def test_exact_duplicate_replays_without_second_dispatch():
    adapter = ProtocolIdempotencyAdapter()
    service = ProductCommandIdempotency(adapter=adapter, app_id="b54")
    first = asyncio.run(service.reserve(identity()))
    asyncio.run(service.complete(first.identity, result={"result_ref": "result_1"}))
    replay = asyncio.run(service.reserve(identity()))
    assert replay.outcome is ProductCommandReservationOutcome.REPLAY
    assert replay.replay_result == {"result_ref": "result_1"}
    assert adapter.inserts == 1


def test_material_change_under_same_identity_conflicts_fail_closed():
    adapter = ProtocolIdempotencyAdapter()
    service = ProductCommandIdempotency(adapter=adapter, app_id="b54")
    asyncio.run(service.reserve(identity()))
    with pytest.raises(IdempotencyConflictError):
        asyncio.run(service.reserve(replace(identity(), payload_sha256="b" * 64)))
    with pytest.raises(IdempotencyConflictError):
        asyncio.run(service.reserve(replace(identity(), command_id="command_2")))


def test_in_flight_duplicate_reservation_conflicts():
    adapter = ProtocolIdempotencyAdapter()
    service = ProductCommandIdempotency(adapter=adapter, app_id="b54")
    asyncio.run(service.reserve(identity()))
    with pytest.raises(IdempotencyConflictError):
        asyncio.run(service.reserve(identity()))
    assert adapter.inserts == 1


def test_cross_workspace_same_client_key_reserves_independently():
    adapter = ProtocolIdempotencyAdapter()
    service = ProductCommandIdempotency(adapter=adapter, app_id="b54")
    left = asyncio.run(service.reserve(identity(workspace_id="ws_1")))
    right = asyncio.run(service.reserve(identity(workspace_id="ws_2")))
    assert left.outcome is ProductCommandReservationOutcome.ACCEPTED
    assert right.outcome is ProductCommandReservationOutcome.ACCEPTED
    assert left.scoped_idempotency_key != right.scoped_idempotency_key
    assert adapter.inserts == 2
    asyncio.run(service.complete(left.identity, result={"result_ref": "result_left"}))
    ws1_replay = asyncio.run(service.reserve(identity(workspace_id="ws_1")))
    assert ws1_replay.outcome is ProductCommandReservationOutcome.REPLAY
    assert ws1_replay.replay_result == {"result_ref": "result_left"}
    with pytest.raises(IdempotencyConflictError):
        asyncio.run(service.reserve(identity(workspace_id="ws_2")))


def test_terminal_replay_never_resurrects_a_completed_command():
    adapter = ProtocolIdempotencyAdapter()
    service = ProductCommandIdempotency(adapter=adapter, app_id="b54")
    first = asyncio.run(service.reserve(identity()))
    asyncio.run(service.complete(first.identity, result={"result_ref": "result_1"}))
    for _ in range(3):
        retry = asyncio.run(service.reserve(identity()))
        assert retry.outcome is ProductCommandReservationOutcome.REPLAY
        assert retry.replay_result == {"result_ref": "result_1"}
    assert adapter.inserts == 1


def test_projection_requires_injected_adapter_and_keeps_no_local_state():
    with pytest.raises(ValueError):
        ProductCommandIdempotency(adapter=None, app_id="b54")
    with pytest.raises(ValueError):
        ProductCommandIdempotency(adapter=object(), app_id="b54")
    with pytest.raises(ValueError):
        ProductCommandIdempotency(adapter=ProtocolIdempotencyAdapter(), app_id="  ")
    service = ProductCommandIdempotency(adapter=ProtocolIdempotencyAdapter(), app_id="b54")
    assert set(vars(service)) == {"_adapter", "_app_id"}


def test_adapter_failure_propagates_without_process_local_fallback():
    class BrokenAdapter(ProtocolIdempotencyAdapter):
        async def begin(self, **kwargs):
            raise RuntimeError("durable store unavailable")

    service = ProductCommandIdempotency(adapter=BrokenAdapter(), app_id="b54")
    with pytest.raises(RuntimeError):
        asyncio.run(service.reserve(identity()))
    assert set(vars(service)) == {"_adapter", "_app_id"}


def test_projection_mints_no_authority():
    adapter = ProtocolIdempotencyAdapter()
    service = ProductCommandIdempotency(adapter=adapter, app_id="b54")
    first = asyncio.run(service.reserve(identity()))
    asyncio.run(service.complete(first.identity, result={"result_ref": "result_1"}))
    replay = asyncio.run(service.reserve(identity()))
    for public in (first.to_public_dict(), replay.to_public_dict()):
        assert public["raw_payload"] is False
        assert public["authorization_granted"] is False
        assert public["approval_minted"] is False
        assert public["execution_authority_granted"] is False
    assert PRODUCT_COMMAND_IDEMPOTENCY_AUTHORITY_MINTING is False


def test_reservation_rejects_inconsistent_replay_material():
    with pytest.raises(ValueError):
        ProductCommandReservation(
            outcome=ProductCommandReservationOutcome.REPLAY,
            identity=identity(),
            scoped_idempotency_key="idem_1",
            request_fingerprint="f" * 64,
        )
    with pytest.raises(ValueError):
        ProductCommandReservation(
            outcome=ProductCommandReservationOutcome.ACCEPTED,
            identity=identity(),
            scoped_idempotency_key="idem_1",
            request_fingerprint="f" * 64,
            replay_result={"result_ref": "result_1"},
        )
