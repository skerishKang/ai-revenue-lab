"""#5015: what a missing PC target does — and does not — prove about replay identity.

The target-bound digest may only ever *extend* the canonical logical-execution
identity. Three properties are load-bearing for the durable replay lane and for
approval continuations, so they are pinned against the real Chat PC wire record:

* a request without a target keeps the exact pre-#5015 digest, byte for byte;
* two different PCs never share a digest, and a malformed target produces no
  digest at all rather than the weaker target-free one;
* nothing on a continuation carries a target field, so ``None == None`` can never
  be read as "same PC". The only resumed-target authority is the server-issued
  pause invocation digest.

Recorder-only: no provider, PC, Chat transport or network call happens.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from padiem_ai_core import IdempotencyConflictError
from padiem_ai_core.execution_context import ExecutionContext

from app.continuation_identity import (
    ContinuationExecutionIdentity,
    execution_request_identity_payload,
)
from app.idempotency_identity import canonical_logical_execution_fingerprint
from app.orchestration_idempotency_service import (
    _initial_execution_fingerprint,
    pc_tool_target_fingerprint,
)
from app.orchestration_service import _parse_orchestration_options
from app.service import build_execution_request

FIXTURE = Path(__file__).with_name("fixtures") / "5015_chat_pc_engine_payloads.json"
FILES_PAYLOAD = json.loads(FIXTURE.read_text(encoding="utf-8"))["files"]
DEVICE_A = "dev_" + "c" * 32
DEVICE_B = "dev_" + "7" * 32

_EXEC_KEYS = (
    "app_id",
    "agent",
    "messages",
    "session_id",
    "additional_system_context",
    "trace_id",
    "execution_context",
)


def _mapping_keys(value) -> set[str]:
    """Every mapping key reachable in a nested payload, without serializing it."""
    keys: set[str] = set()
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, item in current.items():
                keys.add(key)
                stack.append(item)
        elif isinstance(current, (list, tuple)):
            stack.extend(current)
    return keys


def _logical_digest(payload: dict) -> str:
    """The pre-#5015 digest: logical material fields only, nothing else."""
    _, exec_req, ctx = build_execution_request({k: payload[k] for k in _EXEC_KEYS if k in payload})
    if ctx is None:
        ctx = ExecutionContext(trace_id=exec_req.trace_id or "orch_trace")
    plan, recovery_policy, max_retries, subject_id, require_evidence, require_verification = (
        _parse_orchestration_options(payload)
    )
    return canonical_logical_execution_fingerprint(
        app_id=payload["app_id"],
        request=exec_req,
        context=ctx,
        subject_id=subject_id,
        plan=plan,
        recovery_policy=recovery_policy,
        max_retries=max_retries,
        require_evidence=require_evidence,
        require_verification=require_verification,
    )


def _without_target(payload: dict, *, drop_plan: bool) -> dict:
    rest = deepcopy(payload)
    rest.pop("tool_arguments", None)
    if drop_plan:
        rest.pop("agent_plan", None)
    rest["execution_context"] = {
        "trace_id": payload["trace_id"],
        "idempotency_key": "idem_5015_policy",
    }
    rest["trace_id"] = payload["trace_id"]
    return rest


def _with_device(payload: dict, device_id: str) -> dict:
    rest = deepcopy(payload)
    rest["tool_arguments"] = {"files": {"device_id": device_id}}
    rest["execution_context"] = {
        "trace_id": payload["trace_id"],
        "idempotency_key": "idem_5015_policy",
    }
    return rest


def test_a_non_pc_request_keeps_the_pre_5015_logical_digest_byte_for_byte():
    payload = _without_target(FILES_PAYLOAD, drop_plan=True)

    assert _initial_execution_fingerprint(payload) == _logical_digest(payload)


def test_a_pc_plan_without_a_target_keeps_that_same_digest():
    """The absence of a target shortens nothing: the digest is still the logical one."""
    payload = _without_target(FILES_PAYLOAD, drop_plan=False)

    assert _initial_execution_fingerprint(payload) == _logical_digest(payload)


def test_the_validated_target_extends_the_digest_and_is_deterministic():
    target_free = _without_target(FILES_PAYLOAD, drop_plan=False)
    bound = _with_device(FILES_PAYLOAD, DEVICE_A)
    logical = _logical_digest(target_free)

    first = _initial_execution_fingerprint(bound)
    assert first is not None
    assert first == _initial_execution_fingerprint(deepcopy(bound))
    assert first != logical
    assert first != _initial_execution_fingerprint(target_free)


def test_two_different_pcs_never_share_a_replay_digest():
    left = _initial_execution_fingerprint(_with_device(FILES_PAYLOAD, DEVICE_A))
    right = _initial_execution_fingerprint(_with_device(FILES_PAYLOAD, DEVICE_B))

    assert left is not None and right is not None
    assert left != right
    assert pc_tool_target_fingerprint({"files": {"device_id": DEVICE_A}}) != (
        pc_tool_target_fingerprint({"files": {"device_id": DEVICE_B}})
    )


def test_a_malformed_target_yields_no_digest_instead_of_a_target_free_one():
    """A rejected target must not fall back to the digest a target-less sibling uses."""
    broken = _with_device(FILES_PAYLOAD, "bad/device")

    assert _initial_execution_fingerprint(broken) is None
    assert _initial_execution_fingerprint(_without_target(FILES_PAYLOAD, drop_plan=False)) is not None


def test_no_target_is_never_a_match_between_two_executions():
    assert pc_tool_target_fingerprint(None) is None
    assert pc_tool_target_fingerprint({}) is None
    target_free = _without_target(FILES_PAYLOAD, drop_plan=False)
    bound = _with_device(FILES_PAYLOAD, DEVICE_A)
    # Absence and presence produce different identities, so a stored target-less
    # record cannot be replayed by a target-bearing request (or the other way
    # round) under one idempotency key.
    assert _initial_execution_fingerprint(target_free) != _initial_execution_fingerprint(bound)


def test_no_continuation_identity_field_can_carry_a_pc_target():
    """Introspected, not grepped: the paused-execution binding has no target slot."""
    assert set(ContinuationExecutionIdentity.__slots__) == {
        "request_fingerprint",
        "plan_fingerprint",
        "subject_id",
        "recovery_policy_fingerprint",
        "max_retries",
        "require_evidence",
        "require_verification",
    }

    _, exec_req, ctx = build_execution_request(
        {k: FILES_PAYLOAD[k] for k in _EXEC_KEYS if k in FILES_PAYLOAD}
    )
    projected = execution_request_identity_payload(
        app_id=FILES_PAYLOAD["app_id"], request=exec_req, context=ctx
    )
    assert "tool_arguments" not in projected
    assert "pc_tool_target" not in projected
    # The projection is a closed set of identity fields, so no target slot can
    # hide in a nested value either.
    assert set(projected) == {
        "app_id",
        "agent",
        "messages",
        "session_id",
        "additional_system_context",
        "trace_id",
        "execution_context",
    }
    assert _mapping_keys(projected).isdisjoint(
        {"tool_arguments", "pc_tool_target", "device_id"}
    )


def test_a_conflicting_target_under_one_key_raises_before_any_rerun():
    """The durable adapter's own conflict rule, exercised without a service stack."""

    class DurableStore:
        def __init__(self) -> None:
            self.rows: dict[tuple[str, str], str] = {}
            self.begin_count = 0

        async def begin(self, *, app_id, idempotency_key, request_fingerprint):
            self.begin_count += 1
            key = (app_id, idempotency_key)
            stored = self.rows.get(key)
            if stored is None:
                self.rows[key] = request_fingerprint
                return None
            if stored != request_fingerprint:
                raise IdempotencyConflictError("conflicting logical execution")
            return SimpleNamespace(response={"answer": "replayed"})

    import asyncio

    store = DurableStore()
    bound = _with_device(FILES_PAYLOAD, DEVICE_A)
    other_pc = _with_device(FILES_PAYLOAD, DEVICE_B)

    async def exercise():
        await store.begin(
            app_id=bound["app_id"],
            idempotency_key="idem_5015_policy",
            request_fingerprint=_initial_execution_fingerprint(bound),
        )
        replay = await store.begin(
            app_id=bound["app_id"],
            idempotency_key="idem_5015_policy",
            request_fingerprint=_initial_execution_fingerprint(deepcopy(bound)),
        )
        assert replay is not None and replay.response == {"answer": "replayed"}
        try:
            await store.begin(
                app_id=other_pc["app_id"],
                idempotency_key="idem_5015_policy",
                request_fingerprint=_initial_execution_fingerprint(other_pc),
            )
        except IdempotencyConflictError:
            return "conflicted"
        return "not-conflicted"

    assert asyncio.run(exercise()) == "conflicted"
    assert store.begin_count == 3


def test_a_target_free_run_digest_does_not_collide_with_the_target_bound_record():
    """A legacy/no-target sibling under the same key is a conflict, not a replay."""

    class DurableStore:
        def __init__(self) -> None:
            self.stored: str | None = None

        async def begin(self, *, app_id, idempotency_key, request_fingerprint):
            if self.stored is None:
                self.stored = request_fingerprint
                return None
            if self.stored != request_fingerprint:
                raise IdempotencyConflictError("conflicting logical execution")
            return SimpleNamespace(response={"answer": "replayed"})

    import asyncio

    store = DurableStore()
    bound = _with_device(FILES_PAYLOAD, DEVICE_A)
    target_free = _without_target(FILES_PAYLOAD, drop_plan=False)

    async def exercise():
        await store.begin(
            app_id=bound["app_id"],
            idempotency_key="idem_5015_policy",
            request_fingerprint=_initial_execution_fingerprint(bound),
        )
        try:
            await store.begin(
                app_id=target_free["app_id"],
                idempotency_key="idem_5015_policy",
                request_fingerprint=_initial_execution_fingerprint(target_free),
            )
        except IdempotencyConflictError:
            return "conflicted"
        return "replayed"

    assert asyncio.run(exercise()) == "conflicted"
