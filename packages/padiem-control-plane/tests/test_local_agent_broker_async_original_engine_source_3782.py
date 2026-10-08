"""#3782 actual Broker durable join CAS fed by independent async Engine D1 client.

Hermetic authorities only: a fake original Broker association is NOT proof of
production provenance and the fake Engine client is NOT a human P01 decision.
No Worker RPC, product activation, or browser input is enabled.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from local_agent_broker_original_engine_async_source import (
    BROKER_ORIGINAL_ENGINE_ASYNC_SOURCE_WIRED,
    ServerOwnedBrokerOriginalRunAssociation,
    SourceOnlyAsyncBrokerOriginalEngineAdmission,
)
from test_local_agent_broker_async_engine_bridge_3782 import (
    _FakeAuthenticatedEngineClient,
)
from test_local_agent_broker_browser_authenticated_take_3782 import (
    DEVICE_CREDENTIAL,
    NOW,
    _Env,
)
from test_local_agent_broker_browser_control_take_3782 import taken_count
from test_local_agent_broker_engine_p01_bridge_3782 import _harness


class _BrokerOriginalAssociationFixture:
    def __init__(self, row):
        self.row = row
        self.calls = 0

    def resolve_for_admitted_command(self, *, scope, now):
        self.calls += 1
        return self.row


class _EngineOriginalD1Fixture:
    """Deliberately synthetic transport, only proves caller contract."""

    def __init__(self, join):
        self.app_id = join.engine_app_id
        self.join = join
        self.calls = []
        self.reply = {
            "app_id": join.engine_app_id,
            "continuation_ref": join.engine_continuation_ref,
            "user_subject_id": join.engine_user_subject_id,
            "original_request_fingerprint": join.engine_request_sha256,
            "original_admission_decision_id": join.engine_original_admission_decision_id,
            "run_id": join.engine_run_id,
            "invocation_sha256": join.browser_invocation_sha256,
            "user_approval_evidence_ref": join.user_p01_evidence_ref,
        }

    async def read_browser_control_original_admission(self, *, continuation_ref):
        self.calls.append(continuation_ref)
        await asyncio.sleep(0)
        return self.reply


def _prepared():
    storage, _broker, scope, material, join_port, receipt, local = _harness()
    join = join_port.result
    assoc = _BrokerOriginalAssociationFixture(ServerOwnedBrokerOriginalRunAssociation(
        command_ref=join.command_ref,
        binding_ref=join.binding_ref,
        request_id=join.request_id,
        run_ref=join.run_ref,
        broker_request_fingerprint=join.broker_request_fingerprint,
        admission_ref=join.admission_ref,
        revision_ref=join.revision_ref,
        engine_app_id=join.engine_app_id,
        engine_continuation_ref=join.engine_continuation_ref,
    ))
    engine = _EngineOriginalD1Fixture(join)
    source = SourceOnlyAsyncBrokerOriginalEngineAdmission(
        association_port=assoc, engine_client=engine,
    )
    broker = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), original_engine_join_source=source,
        browser_admission_clock=lambda: NOW,
    )
    return storage, broker, scope, material, join, receipt, local, assoc, engine


def _bind(broker, scope, credential=DEVICE_CREDENTIAL):
    return asyncio.run(broker._bind_original_browser_engine_join_async(
        scope=scope, credential=credential, now=NOW,
    ))


def _count(storage):
    return storage.connection.execute(
        "SELECT COUNT(*) FROM local_agent_browser_engine_original_join"
    ).fetchone()[0]


def test_authenticated_original_d1_async_maps_into_durable_broker_join_after_restart():
    storage, broker, scope, material, join, receipt, local, assoc, engine = _prepared()
    assert BROKER_ORIGINAL_ENGINE_ASYNC_SOURCE_WIRED is False
    result = _bind(broker, scope)
    assert result["stored"] is True and result["browser_action_executed"] is False
    assert _count(storage) == 1
    assert assoc.calls == 1
    assert engine.calls == [join.engine_continuation_ref]
    reopened = LocalAgentBrokerDurableRuntime(storage=storage, env=_Env())
    assert reopened.browser_engine_join_store.resolve_for_admitted_command(
        scope=scope, now=NOW,
    ) == join
    assert reopened._original_engine_join_source is None

    # The joined D1 execution still does NOT grant a browser command. Re-read
    # current P01 independently, compare its invocation digest, then CAS.
    from local_agent_broker_engine_p01_bridge import (
        AsyncBrokerEngineBrowserP01Bridge,
        AuthenticatedAsyncEngineReceiptClientPort,
    )

    p01_client = _FakeAuthenticatedEngineClient(join, receipt.projection)
    approved = AsyncBrokerEngineBrowserP01Bridge(
        join_port=reopened.browser_engine_join_store,
        engine_port=AuthenticatedAsyncEngineReceiptClientPort(engine_client=p01_client),
        local_port=local,
    )
    active = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), p01_approval_source=approved,
        browser_admission_clock=lambda: NOW,
    )
    assert asyncio.run(active._bind_browser_material_to_admitted_command_async(
        scope=scope, credential=DEVICE_CREDENTIAL, material=material, now=NOW,
    ))["stored"] is True
    taken = asyncio.run(active._take_authenticated_browser_control_command_async(
        scope=scope, credential=DEVICE_CREDENTIAL, now=NOW,
    ))
    assert taken == material
    assert taken_count(storage) == 1
    assert len(p01_client.calls) == 2


@pytest.mark.parametrize("field,value", [
    ("binding_ref", "other.binding"),
    ("admission_ref", "other.admission"),
    ("revision_ref", "other.revision"),
    ("command_ref", "other.command"),
    ("broker_request_fingerprint", "f" * 64),
    ("engine_app_id", "other.engine.app"),
])
def test_unauthorized_original_binding_never_queries_engine_or_persists(field, value):
    storage, broker, scope, _material, _join, _receipt, _local, assoc, engine = _prepared()
    assoc.row = replace(assoc.row, **{field: value})
    with pytest.raises(ValueError):
        _bind(broker, scope)
    assert engine.calls == []
    assert _count(storage) == 0


@pytest.mark.parametrize("field,value", [
    ("app_id", "other.engine.app"),
    ("continuation_ref", "cont_other_engine_run"),
    ("user_subject_id", "other.user"),
    ("run_id", 123),
    ("invocation_sha256", "not-a-sha"),
    ("user_approval_evidence_ref", ""),
])
def test_engine_client_wrong_original_d1_dimensions_refuse_join(field, value):
    storage, broker, scope, _material, _join, _receipt, _local, assoc, engine = _prepared()
    engine.reply = {**engine.reply, field: value}
    with pytest.raises(ValueError):
        _bind(broker, scope)
    assert len(engine.calls) == 1 and assoc.calls == 1
    assert _count(storage) == 0


def test_device_auth_preflight_fails_before_original_engine_fetch():
    storage, broker, scope, _material, _join, _receipt, _local, assoc, engine = _prepared()
    with pytest.raises(ValueError):
        _bind(broker, scope, credential=b"bad-device-credential")
    assert assoc.calls == 0 and engine.calls == []
    assert _count(storage) == 0


def test_not_wired_or_synchronous_engine_transport_fail_closed():
    storage, broker, scope, _material, _join, _receipt, _local, _assoc, engine = _prepared()
    empty = LocalAgentBrokerDurableRuntime(storage=storage, env=_Env())
    with pytest.raises(ValueError, match="not wired"):
        _bind(empty, scope)
    engine.read_browser_control_original_admission = lambda **_: dict(engine.reply)
    with pytest.raises(ValueError, match="asynchronous"):
        _bind(broker, scope)
    assert _count(storage) == 0


def test_no_worker_gateway_for_original_engine_join_cas():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    worker = (root / "local_agent_broker_worker.py").read_text(encoding="utf-8")
    assert "_bind_original_browser_engine_join_async" not in worker
    assert "resolve_original_admission_async" not in worker
    source = (root / "local_agent_broker_original_engine_async_source.py").read_text(encoding="utf-8")
    assert "BROKER_ORIGINAL_ENGINE_ASYNC_SOURCE_WIRED = False" in source
