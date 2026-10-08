"""#3782 original Engine association survives Broker DO restart without a grant.

All original admissions are test-only synthetic joins; no product issuer exists.
Broker must still independently read real Engine P01 plus live local permission
before any browser command material can be registered or consumed.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from local_agent_broker_engine_p01_join_store import (
    BROKER_ORIGINAL_ENGINE_JOIN_PRODUCT_ISSUER_WIRED,
)
from test_local_agent_broker_browser_authenticated_take_3782 import (
    DEVICE_CREDENTIAL,
    NOW,
    _Env,
)
from test_local_agent_broker_engine_p01_bridge_3782 import _harness


class _OriginalEngineOwner:
    """Fixture only: authenticating a real Engine admission is NOT implemented."""

    def __init__(self, join):
        self.join = join
        self.calls = 0

    def resolve_original_admission(self, *, scope, now):
        self.calls += 1
        return self.join


def prepared():
    storage, _unused_broker, scope, _material, join, _engine, _local = _harness()
    issuer = _OriginalEngineOwner(join.result)
    broker = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), original_engine_join_source=issuer,
    )
    return storage, broker, scope, issuer


def bind(broker, scope, *, credential=DEVICE_CREDENTIAL):
    return broker._bind_original_browser_engine_join(
        scope=scope, credential=credential, now=NOW,
    )


def count(storage):
    return storage.connection.execute(
        "SELECT COUNT(*) FROM local_agent_browser_engine_original_join"
    ).fetchone()[0]


def test_canonical_broker_join_persists_across_restart_and_requires_same_scope():
    storage, broker, scope, issuer = prepared()
    assert BROKER_ORIGINAL_ENGINE_JOIN_PRODUCT_ISSUER_WIRED is False
    result = bind(broker, scope)
    assert result == {
        "stored": True, "command_ref": scope.command_ref,
        "browser_action_executed": False, "engine_approval_recorded": False,
    }
    assert issuer.calls == 1
    assert count(storage) == 1
    reader = LocalAgentBrokerDurableRuntime(storage=storage, env=_Env())
    joined = reader.browser_engine_join_store.resolve_for_admitted_command(
        scope=scope, now=NOW,
    )
    assert joined == issuer.join
    assert joined.engine_request_sha256 != joined.broker_request_fingerprint
    assert joined.engine_run_id != joined.run_ref
    assert reader._original_engine_join_source is None
    assert reader._p01_approval_source is None
    with pytest.raises(ValueError, match="not wired"):
        bind(reader, scope)
    assert count(storage) == 1


def test_no_second_registration_even_if_original_owner_returns_same_join():
    storage, broker, scope, issuer = prepared()
    bind(broker, scope)
    with pytest.raises(ValueError, match="already bound"):
        bind(broker, scope)
    assert count(storage) == 1
    assert issuer.calls == 2


@pytest.mark.parametrize("bad_field", [
    "command_ref", "binding_ref", "request_id", "run_ref",
    "broker_request_fingerprint", "admission_ref", "revision_ref",
    "engine_user_subject_id",
])
def test_fake_or_other_original_engine_run_cannot_bind(bad_field):
    storage, broker, scope, issuer = prepared()
    value = "f" * 64 if bad_field == "broker_request_fingerprint" else "other.3782"
    issuer.join = replace(issuer.join, **{bad_field: value})
    with pytest.raises(ValueError, match="does not match"):
        bind(broker, scope)
    assert count(storage) == 0


def test_broker_evidence_mismatch_never_creates_original_join():
    storage, broker, scope, issuer = prepared()
    issuer.join = replace(issuer.join, user_p01_evidence_ref="other.evidence")
    with pytest.raises(ValueError, match="evidence"):
        bind(broker, scope)
    assert count(storage) == 0


def test_live_device_credential_required_before_original_owner_read():
    storage, broker, scope, issuer = prepared()
    with pytest.raises(ValueError):
        bind(broker, scope, credential=b"wrong")
    assert issuer.calls == 0
    assert count(storage) == 0


@pytest.mark.parametrize("operation", ["rotate", "revoke"])
def test_device_revoke_or_rotate_purges_original_engine_association(operation):
    storage, broker, scope, _issuer = prepared()
    bind(broker, scope)
    if operation == "rotate":
        import base64

        changed = broker.rotate_credential({
            "binding_ref": scope.binding_ref,
            "expected_generation": 1,
            "new_credential_b64": base64.b64encode(b"new.credential.3782").decode(),
            "now": (NOW + timedelta(seconds=1)).isoformat(),
        })
    else:
        changed = broker.revoke_binding({
            "binding_ref": scope.binding_ref,
            "now": (NOW + timedelta(seconds=1)).isoformat(),
        })
    assert changed["ok"] is True
    assert count(storage) == 0
    with pytest.raises(ValueError, match="not registered"):
        broker.browser_engine_join_store.resolve_for_admitted_command(
            scope=scope, now=NOW + timedelta(seconds=2),
        )


def test_changed_correlated_scope_or_expired_original_join_refuses():
    storage, broker, scope, _issuer = prepared()
    bind(broker, scope)
    for field in ("binding_ref", "admission_ref", "revision_ref", "request_fingerprint"):
        value = "f" * 64 if field == "request_fingerprint" else "other.3782"
        with pytest.raises(ValueError):
            broker.browser_engine_join_store.resolve_for_admitted_command(
                scope=replace(scope, **{field: value}), now=NOW,
            )
    with pytest.raises(ValueError, match="expired"):
        broker.browser_engine_join_store.resolve_for_admitted_command(
            scope=scope, now=NOW + timedelta(hours=1),
        )
    assert count(storage) == 1


def test_no_public_original_engine_join_registration_on_deployed_worker():
    from pathlib import Path

    worker = (
        Path(__file__).resolve().parents[1] / "local_agent_broker_worker.py"
    ).read_text(encoding="utf-8")
    assert "bind_original_browser_engine_join" not in worker
    assert "register_original_browser_engine_join" not in worker
    storage, broker, _scope, _issuer = prepared()
    assert not hasattr(broker, "register_original_browser_engine_join")
    assert count(storage) == 0


def test_persisted_original_join_is_used_by_real_async_broker_cas():
    """Synthetic D1 receipt, but real durable join plus Broker one-shot CAS."""
    from local_agent_broker_engine_p01_bridge import (
        AsyncBrokerEngineBrowserP01Bridge,
        AuthenticatedAsyncEngineReceiptClientPort,
    )
    from test_local_agent_broker_async_engine_bridge_3782 import _system
    from test_local_agent_broker_browser_control_take_3782 import taken_count

    storage, _prior, scope, material, join, local, client = _system()
    owner = _OriginalEngineOwner(join.result)
    persisted = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), original_engine_join_source=owner,
        browser_admission_clock=lambda: NOW,
    )
    assert bind(persisted, scope)["stored"] is True
    assert owner.calls == 1
    bridge = AsyncBrokerEngineBrowserP01Bridge(
        join_port=persisted.browser_engine_join_store,
        engine_port=AuthenticatedAsyncEngineReceiptClientPort(engine_client=client),
        local_port=local,
    )
    broker = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), p01_approval_source=bridge,
        browser_admission_clock=lambda: NOW,
    )
    import asyncio

    accepted = asyncio.run(broker._bind_browser_material_to_admitted_command_async(
        scope=scope, credential=DEVICE_CREDENTIAL, material=material, now=NOW,
    ))
    assert accepted["stored"] is True
    assert accepted["action_executed"] is False
    restarted = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), p01_approval_source=bridge,
        browser_admission_clock=lambda: NOW,
    )
    assert asyncio.run(restarted._take_authenticated_browser_control_command_async(
        scope=scope, credential=DEVICE_CREDENTIAL, now=NOW,
    )) == material
    assert taken_count(storage) == 1
    assert len(client.calls) == 2
    assert local.calls == 2
    with pytest.raises(ValueError, match="already taken"):
        asyncio.run(restarted._take_authenticated_browser_control_command_async(
            scope=scope, credential=DEVICE_CREDENTIAL, now=NOW,
        ))
    assert taken_count(storage) == 1


def test_terminal_command_purge_removes_only_corresponding_engine_association():
    """Synthetic rows; deletion is exact and restart-safe, not a P01 grant."""
    from dataclasses import replace

    storage, broker, scope, issuer = prepared()
    bind(broker, scope)
    other_scope = replace(scope, command_ref="command.3782.sibling")
    other_join = replace(issuer.join, command_ref=other_scope.command_ref)
    storage.transactionSync(lambda: broker.browser_engine_join_store._register_in_existing_transaction(
        scope=other_scope, original=other_join, now=NOW,
        expires_at=NOW + timedelta(seconds=60),
    ))
    assert count(storage) == 2
    assert storage.transactionSync(
        lambda: broker.browser_engine_join_store.purge_command(scope.command_ref)
    ) == 1
    assert count(storage) == 1
    assert broker.browser_engine_join_store.resolve_for_admitted_command(
        scope=other_scope, now=NOW,
    ) == other_join
    restarted = LocalAgentBrokerDurableRuntime(storage=storage, env=_Env())
    with pytest.raises(ValueError, match="not registered"):
        restarted.browser_engine_join_store.resolve_for_admitted_command(
            scope=scope, now=NOW,
        )
    assert restarted.browser_engine_join_store.purge_command(scope.command_ref) == 0
    assert count(storage) == 1


def test_terminal_cleanup_rejects_bad_ids_without_broad_delete():
    storage, broker, scope, _issuer = prepared()
    bind(broker, scope)
    for bad in ("", "../other", "x" * 257, None):
        with pytest.raises(ValueError):
            broker.browser_engine_join_store.purge_command(bad)
    assert count(storage) == 1


def test_terminal_acknowledge_and_reconcile_use_exact_atomic_join_purge():
    """Source invariant: both terminal lifecycle paths purge in the DO txn."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "local_agent_broker_durable_runtime.py"
    ).read_text(encoding="utf-8")
    for method in ("acknowledge", "reconcile_expired_command"):
        block = source.split(f"    def {method}(self, payload: dict) -> dict:", 1)[1]
        block = block.split("        return self.transaction(operation)", 1)[0]
        assert "self.material_store.purge_command(command_id)" in block
        assert "self.browser_engine_join_store.purge_command(command_id)" in block
        assert block.index("self.material_store.purge_command(command_id)") < block.index(
            "self.browser_engine_join_store.purge_command(command_id)"
        )
        assert "if result.get(\"ok\") is True:" in block
    worker = (
        Path(__file__).resolve().parents[1] / "local_agent_broker_worker.py"
    ).read_text(encoding="utf-8")
    assert "purge_command(" not in worker
    assert "original_engine_join" not in worker


def test_canonical_terminal_ack_cleans_seeded_original_join_in_same_durable_object(tmp_path):
    """Real Broker enqueue/admit/ack; the linked row is synthetic test data.

    The ordinary process.execute route is reused only to exercise the shared
    terminal lifecycle. This does NOT assert browser.control is producible.
    """
    from test_local_agent_broker_enqueue_material_atomicity import (
        BASE,
        _ack_payload,
        _admit_payload,
        _enqueue_payload,
        _material_body,
        _register_and_open,
        _runtime,
    )

    file = tmp_path / "broker-original-terminal.sqlite3"
    broker = _runtime(file)
    _register_and_open(broker)
    command_id = "command.original.cleanup"
    enqueued = broker.enqueue_command_with_material(
        _enqueue_payload(command_id, now=BASE + timedelta(seconds=2)),
        _material_body(command_id),
    )
    assert enqueued["ok"] is True
    command = enqueued["command"]
    assert broker.admit_command(
        _admit_payload(command, at=BASE + timedelta(seconds=3)),
    )["ok"] is True

    # Simulate an existing association whose owner was verified earlier.
    # The terminal code must clean by exact canonical command ID only.
    broker._storage.sql.exec(
        "INSERT INTO local_agent_browser_engine_original_join "
        "(command_ref,binding_ref,request_fingerprint,admission_ref,"
        "revision_ref,expires_at,join_json) VALUES (?,?,?,?,?,?,?)",
        command_id, command["binding_ref"], command["request_fingerprint"],
        "admission." + command_id, command["revision_ref"],
        (BASE + timedelta(minutes=4)).isoformat(), "{}",
    )
    assert broker._storage.connection.execute(
        "SELECT count(*) FROM local_agent_browser_engine_original_join"
    ).fetchone()[0] == 1
    bad = _ack_payload(command, at=BASE + timedelta(seconds=4))
    bad["admission_ref"] = "admission.foreign"
    try:
        refused = broker.acknowledge(bad)
        assert refused.get("ok") is not True
    except ValueError:
        pass
    assert broker._storage.connection.execute(
        "SELECT count(*) FROM local_agent_browser_engine_original_join"
    ).fetchone()[0] == 1

    assert broker.acknowledge(
        _ack_payload(command, at=BASE + timedelta(seconds=5)),
    )["ok"] is True
    assert broker._storage.connection.execute(
        "SELECT count(*) FROM local_agent_browser_engine_original_join"
    ).fetchone()[0] == 0
    del broker
    restarted = _runtime(file)
    assert restarted._storage.connection.execute(
        "SELECT count(*) FROM local_agent_browser_engine_original_join"
    ).fetchone()[0] == 0

def test_terminal_lifecycle_also_purges_browser_action_material():
    """Both terminal transitions purge the browser take and original association."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "local_agent_broker_durable_runtime.py"
    ).read_text(encoding="utf-8")
    for name in ("acknowledge", "reconcile_expired_command"):
        branch = source.split(f"    def {name}(self, payload: dict) -> dict:", 1)[1]
        branch = branch.split("        return self.transaction(operation)", 1)[0]
        assert "self.browser_control_take_store.purge_command(command_id)" in branch
        assert "self.browser_engine_join_store.purge_command(command_id)" in branch
        assert branch.index("self.browser_control_take_store.purge_command(command_id)") < branch.index(
            "self.browser_engine_join_store.purge_command(command_id)"
        )
