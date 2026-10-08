"""#3782 async Engine P01 lookup -> existing Broker durable one-shot CAS.

Hermetic injected P01 fixtures only. No live Worker port, production browser
approval, registered RPC, or actual desktop Input action is activated.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from test_local_agent_broker_browser_authenticated_take_3782 import (
    DEVICE_CREDENTIAL,
    NOW,
    _Env,
)
from test_local_agent_broker_browser_control_take_3782 import taken_count
from test_local_agent_broker_browser_registration_3782 import (
    empty_fixture,
    registered_rows,
)


class _AsyncEngineP01:
    def __init__(self, original, storage):
        self.grant = original.grant
        self.storage = storage
        self.calls = 0
        self.fail = False

    async def resolve_approved_command_async(self, *, scope, now):
        self.calls += 1
        # A network await must run BEFORE entering Broker DO transactionSync.
        assert not self.storage.connection.in_transaction
        await asyncio.sleep(0)
        if self.fail:
            raise ValueError("authenticated Engine receipt revoked")
        return self.grant

    def resolve_approved_command(self, *, scope, now):
        raise AssertionError("must never silently fall back to sync P01")


def _prepared():
    storage, original, scope, wire = empty_fixture()
    source = _AsyncEngineP01(original._p01_approval_source, storage)
    broker = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), p01_approval_source=source,
    )
    return storage, broker, scope, wire, source


def _register(broker, scope, material):
    return asyncio.run(broker._bind_browser_material_to_admitted_command_async(
        scope=scope, credential=DEVICE_CREDENTIAL, material=material, now=NOW,
    ))


def _take(broker, scope):
    return asyncio.run(broker._take_authenticated_browser_control_command_async(
        scope=scope, credential=DEVICE_CREDENTIAL, now=NOW,
    ))


def test_async_original_engine_p01_then_actual_broker_durable_take_across_restart():
    storage, broker, scope, material, source = _prepared()
    result = _register(broker, scope, material)
    assert result["stored"] is True
    assert result["action_executed"] is False
    assert source.calls == 1
    assert registered_rows(storage) == 1
    reopened = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), p01_approval_source=source,
    )
    assert _take(reopened, scope) == material
    assert source.calls == 2
    assert taken_count(storage) == 1
    with pytest.raises(ValueError, match="already taken"):
        _take(broker, scope)
    assert taken_count(storage) == 1


def test_revoked_engine_receipt_after_registration_refuses_one_shot_take():
    storage, broker, scope, material, source = _prepared()
    _register(broker, scope, material)
    source.fail = True
    with pytest.raises(ValueError, match="revoked"):
        _take(broker, scope)
    assert taken_count(storage) == 0


@pytest.mark.parametrize("mode", [
    "wrong_evidence", "wrong_run", "expired", "wrong_digest",
])
def test_async_broker_never_registers_mismatched_engine_p01(mode):
    storage, broker, scope, material, source = _prepared()
    if mode == "wrong_evidence":
        source.grant = replace(source.grant, evidence_ref="wrong.evidence")
    elif mode == "wrong_run":
        source.grant = replace(source.grant, run_ref="wrong.run")
    elif mode == "expired":
        source.grant = replace(source.grant, expires_at=NOW - timedelta(seconds=1))
    else:
        source.grant = replace(source.grant, approval_invocation_sha256="e" * 64)
    with pytest.raises(ValueError):
        _register(broker, scope, material)
    assert registered_rows(storage) == 0
    assert taken_count(storage) == 0


def test_async_lookup_absent_or_nonawaitable_never_grants_browser():
    storage, broker, scope, material, source = _prepared()
    broker._p01_approval_source = None
    with pytest.raises(ValueError, match="not wired"):
        _register(broker, scope, material)
    assert registered_rows(storage) == 0
    broker._p01_approval_source = source
    source.resolve_approved_command_async = lambda **_: source.grant
    with pytest.raises(ValueError, match="awaitable"):
        _register(broker, scope, material)
    assert registered_rows(storage) == 0


def test_sync_broker_path_still_requires_explicit_sync_provenance():
    storage, broker, scope, material, _source = _prepared()

    class OnlyAsync:
        async def resolve_approved_command_async(self, *, scope, now):
            raise AssertionError("sync path must not invoke async source")

    # An async-only producer must not be auto-promoted by any sync caller.
    broker._p01_approval_source = OnlyAsync()
    with pytest.raises((ValueError, AttributeError)):
        broker._bind_browser_material_to_admitted_command(
            scope=scope, credential=DEVICE_CREDENTIAL, material=material, now=NOW,
        )
    assert registered_rows(storage) == 0
