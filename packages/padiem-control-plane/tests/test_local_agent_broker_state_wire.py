from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import (
    LocalAgentBrokerStateSnapshot,
    StateBackedLocalAgentBrokerAuthority,
)
from padiem_control_plane import local_agent_broker_state_wire as wire_module
from padiem_control_plane.local_agent_broker_state_wire import (
    ATOMIC_SERIALIZED_BACKEND_PORT,
    BOUNDED_SERIALIZED_STATE,
    BROKER_STATE_JSON_CODEC,
    CANONICAL_SNAPSHOT_VALIDATION_REUSED,
    CLOSED_WIRE_SCHEMA,
    DATABASE_DRIVER_SELECTED,
    DETERMINISTIC_WIRE_ENCODING,
    DUPLICATE_JSON_KEY_REJECTED,
    IN_MEMORY_SERIALIZED_BACKEND_COUNTS_AS_DURABLE,
    PICKLE_OR_ARBITRARY_OBJECT_DESERIALIZATION,
    PRODUCTION_MUTATION,
    PRODUCTION_READY,
    PRODUCTION_STORE_CONFIGURED,
    PROVIDER_SPECIFIC_SQL,
    RAW_DEVICE_CREDENTIAL_SERIALIZED,
    SERIALIZED_STATE_ADAPTER_TO_M2F,
    InMemorySerializedLocalAgentBrokerStateBackend,
    LocalAgentBrokerStateJsonCodec,
    SerializedLocalAgentBrokerStatePort,
)

BASE = datetime(2026, 9, 4, 2, 0, tzinfo=timezone.utc)
PEPPER = b"serialized-broker-state-test-pepper"
CREDENTIAL_1 = b"serialized-device-credential-1"
CREDENTIAL_2 = b"serialized-device-credential-2"
FINGERPRINT_1 = "a" * 64
FINGERPRINT_2 = "b" * 64
AUTHORITY_REF = "control-plane.local-agent-broker.wire-test.v1"


def _port(
    backend: InMemorySerializedLocalAgentBrokerStateBackend | None = None,
) -> SerializedLocalAgentBrokerStatePort:
    return SerializedLocalAgentBrokerStatePort(
        backend=backend or InMemorySerializedLocalAgentBrokerStateBackend(),
    )


def _authority(port: SerializedLocalAgentBrokerStatePort) -> StateBackedLocalAgentBrokerAuthority:
    return StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=port,
    )


def _register(authority: StateBackedLocalAgentBrokerAuthority):
    return authority.register_binding(
        binding_ref="binding.wire.1",
        device_id="device.wire.1",
        account_ref="account.wire.1",
        workspace_ref="workspace.wire.1",
        credential=CREDENTIAL_1,
        now=BASE,
    )


def _session(
    authority: StateBackedLocalAgentBrokerAuthority,
    *,
    session_id: str = "session.wire.1",
    credential: bytes = CREDENTIAL_1,
    now: datetime = BASE + timedelta(seconds=1),
):
    return authority.open_session(
        session_id=session_id,
        binding_ref="binding.wire.1",
        credential=credential,
        account_ref="account.wire.1",
        workspace_ref="workspace.wire.1",
        now=now,
    )


def _queued_snapshot() -> tuple[LocalAgentBrokerStateSnapshot, str]:
    backend = InMemorySerializedLocalAgentBrokerStateBackend()
    port = _port(backend)
    authority = _authority(port)
    binding = _register(authority)
    _session(authority)
    authority.enqueue_command(
        command_id="command.wire.1",
        binding_ref=binding.binding_ref,
        run_id="run.wire.1",
        tool_request_ref="tool-request.wire.1",
        request_fingerprint=FINGERPRINT_1,
        now=BASE + timedelta(seconds=2),
    )
    stored = port.load(authority_ref=AUTHORITY_REF)
    return stored.snapshot, stored.snapshot.bindings[0].credential_digest


def _wire_dict(snapshot: LocalAgentBrokerStateSnapshot) -> dict[str, object]:
    return json.loads(LocalAgentBrokerStateJsonCodec().encode(snapshot).decode("utf-8"))


def _wire_bytes(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_codec_is_deterministic_and_roundtrips_complete_snapshot() -> None:
    snapshot, _ = _queued_snapshot()
    codec = LocalAgentBrokerStateJsonCodec()

    first = codec.encode(snapshot)
    second = codec.encode(snapshot)
    decoded = codec.decode(first)

    assert first == second
    assert decoded == snapshot
    assert codec.encode(decoded) == first
    assert b'"issued_at":"2026-09-04T02:00:00Z"' in first
    assert b"+00:00" not in first


def test_serialized_restart_preserves_sequence_poll_and_command_authority() -> None:
    backend = InMemorySerializedLocalAgentBrokerStateBackend()
    first_port = _port(backend)
    first_process = _authority(first_port)
    _register(first_process)
    session = _session(first_process)
    first = first_process.enqueue_command(
        command_id="command.wire.1",
        binding_ref="binding.wire.1",
        run_id="run.wire.1",
        tool_request_ref="tool-request.wire.1",
        request_fingerprint=FINGERPRINT_1,
        now=BASE + timedelta(seconds=2),
    )
    assert first.sequence == 1

    restarted = _authority(_port(backend))
    second = restarted.enqueue_command(
        command_id="command.wire.2",
        binding_ref="binding.wire.1",
        run_id="run.wire.2",
        tool_request_ref="tool-request.wire.2",
        request_fingerprint=FINGERPRINT_2,
        now=BASE + timedelta(seconds=3),
    )
    assert second.sequence == 2
    polled = restarted.poll(
        session_id=session.session_id,
        binding_ref="binding.wire.1",
        credential=CREDENTIAL_1,
        after_sequence=0,
        now=BASE + timedelta(seconds=4),
    )
    assert [item.sequence for item in polled] == [1, 2]


def test_rotation_revocation_admission_and_ack_states_roundtrip() -> None:
    backend = InMemorySerializedLocalAgentBrokerStateBackend()
    authority = _authority(_port(backend))
    _register(authority)
    first_session = _session(authority)
    command = authority.enqueue_command(
        command_id="command.wire.1",
        binding_ref="binding.wire.1",
        run_id="run.wire.1",
        tool_request_ref="tool-request.wire.1",
        request_fingerprint=FINGERPRINT_1,
        now=BASE + timedelta(seconds=2),
    )
    admission = authority.admit_command(
        admission_ref="admission.wire.1",
        evidence_ref="evidence.wire.1",
        session_id=first_session.session_id,
        binding_ref="binding.wire.1",
        credential=CREDENTIAL_1,
        command_id=command.command_id,
        request_fingerprint=FINGERPRINT_1,
        now=BASE + timedelta(seconds=3),
    )
    authority.acknowledge(
        session_id=first_session.session_id,
        binding_ref="binding.wire.1",
        credential=CREDENTIAL_1,
        command_id=command.command_id,
        admission_ref=admission.admission_ref,
        evidence_ref=admission.evidence_ref,
        now=BASE + timedelta(seconds=4),
    )

    after_ack = _authority(_port(backend))
    stored = after_ack._state_port.load(authority_ref=AUTHORITY_REF).snapshot
    assert stored.commands[0].state.value == "acknowledged"
    assert stored.commands[0].admission_ref == admission.admission_ref
    assert stored.commands[0].evidence_ref == admission.evidence_ref

    rotated = after_ack.rotate_credential(
        "binding.wire.1",
        expected_generation=1,
        new_credential=CREDENTIAL_2,
        now=BASE + timedelta(seconds=5),
    )
    assert rotated.credential_generation == 2
    after_rotation = _authority(_port(backend))
    rotation_state = after_rotation._state_port.load(authority_ref=AUTHORITY_REF).snapshot
    assert rotation_state.sessions == ()

    _session(
        after_rotation,
        session_id="session.wire.2",
        credential=CREDENTIAL_2,
        now=BASE + timedelta(seconds=6),
    )
    after_rotation.revoke_binding("binding.wire.1", now=BASE + timedelta(seconds=7))
    revoked_restart = _authority(_port(backend))
    revoked_state = revoked_restart._state_port.load(authority_ref=AUTHORITY_REF).snapshot
    assert revoked_state.bindings[0].state.value == "revoked"
    assert revoked_state.sessions == ()
    with pytest.raises(ControlPlaneContractError) as denied:
        _session(
            revoked_restart,
            session_id="session.wire.3",
            credential=CREDENTIAL_2,
            now=BASE + timedelta(seconds=8),
        )
    assert denied.value.code == "device_binding_revoked"


def test_raw_credential_is_never_serialized_but_digest_is_internal_only() -> None:
    snapshot, digest = _queued_snapshot()
    codec = LocalAgentBrokerStateJsonCodec()
    encoded = codec.encode(snapshot)

    assert CREDENTIAL_1 not in encoded
    assert base64.b64encode(CREDENTIAL_1) not in encoded
    assert digest.encode("ascii") in encoded
    assert snapshot.safe_dict()["credential_digest_exposed"] is False
    assert codec.safe_dict()["credential_digest_safe_projection"] is False
    assert codec.safe_dict()["raw_device_credential_serialized"] is False


def test_duplicate_json_key_and_unknown_fields_fail_closed() -> None:
    codec = LocalAgentBrokerStateJsonCodec()
    duplicate = (
        b'{"wire_version":"padiem.local-agent-broker-state-wire.v1",'
        b'"wire_version":"duplicate"}'
    )
    with pytest.raises(ControlPlaneContractError) as duplicate_error:
        codec.decode(duplicate)
    assert duplicate_error.value.code == "duplicate_local_agent_broker_state_wire_key"

    snapshot, _ = _queued_snapshot()
    wire = _wire_dict(snapshot)
    wire["unknown"] = "forbidden"
    with pytest.raises(ControlPlaneContractError) as top_unknown:
        codec.decode(_wire_bytes(wire))
    assert top_unknown.value.code == "invalid_local_agent_broker_state_wire"

    wire = _wire_dict(snapshot)
    bindings = wire["bindings"]
    assert isinstance(bindings, list)
    bindings[0]["unknown"] = "forbidden"
    with pytest.raises(ControlPlaneContractError) as record_unknown:
        codec.decode(_wire_bytes(wire))
    assert record_unknown.value.code == "invalid_local_agent_broker_state_wire"


@pytest.mark.parametrize(
    ("field_path", "bad_value"),
    [
        (("bindings", 0, "state"), "future-state"),
        (("bindings", 0, "issued_at"), "2026-09-04T11:00:00+09:00"),
        (("bindings", 0, "credential_generation"), "1"),
        (("commands", 0, "sequence"), True),
    ],
)
def test_enum_timestamp_and_integer_coercion_fail_closed(field_path, bad_value) -> None:
    snapshot, _ = _queued_snapshot()
    wire = _wire_dict(snapshot)
    collection_name, index, field_name = field_path
    collection = wire[collection_name]
    assert isinstance(collection, list)
    collection[index][field_name] = bad_value

    with pytest.raises(ControlPlaneContractError) as caught:
        LocalAgentBrokerStateJsonCodec().decode(_wire_bytes(wire))
    assert caught.value.code == "invalid_local_agent_broker_state_wire"


def test_payload_and_collection_bounds_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    codec = LocalAgentBrokerStateJsonCodec()
    oversized = b"{" + b" " * wire_module.MAX_BROKER_STATE_WIRE_BYTES + b"}"
    with pytest.raises(ControlPlaneContractError) as bytes_error:
        codec.decode(oversized)
    assert bytes_error.value.code == "local_agent_broker_state_wire_too_large"

    snapshot, _ = _queued_snapshot()
    monkeypatch.setattr(wire_module, "MAX_BROKER_STATE_COLLECTION_ITEMS", 0)
    with pytest.raises(ControlPlaneContractError) as collection_error:
        codec.encode(snapshot)
    assert collection_error.value.code == "local_agent_broker_state_wire_too_large"


def test_cross_record_invariants_are_revalidated_after_decode() -> None:
    snapshot, _ = _queued_snapshot()
    wire = _wire_dict(snapshot)
    sessions = wire["sessions"]
    assert isinstance(sessions, list)
    sessions[0]["account_ref"] = "account.other"

    with pytest.raises(ControlPlaneContractError) as caught:
        LocalAgentBrokerStateJsonCodec().decode(_wire_bytes(wire))
    assert caught.value.code == "invalid_local_agent_broker_state"


def test_serialized_backend_cas_rejects_stale_writer_and_is_not_durable() -> None:
    backend = InMemorySerializedLocalAgentBrokerStateBackend()
    port = _port(backend)
    initial = port.load(authority_ref=AUTHORITY_REF)
    first = port.compare_and_swap(
        authority_ref=AUTHORITY_REF,
        expected_version=0,
        snapshot=initial.snapshot,
    )
    assert first.version == 1

    with pytest.raises(ControlPlaneContractError) as stale:
        port.compare_and_swap(
            authority_ref=AUTHORITY_REF,
            expected_version=0,
            snapshot=initial.snapshot,
        )
    assert stale.value.code == "stale_local_agent_broker_state"
    assert port.durable is False
    assert backend.safe_dict()["durable"] is False


def test_existing_rpc_facade_remains_compatible_with_serialized_state_port() -> None:
    backend = InMemorySerializedLocalAgentBrokerStateBackend()
    port = _port(backend)
    rpc = LocalAgentBrokerRpcFacade(authority=_authority(port))
    result = rpc.register_binding(
        {
            "binding_ref": "binding.wire.1",
            "device_id": "device.wire.1",
            "account_ref": "account.wire.1",
            "workspace_ref": "workspace.wire.1",
            "credential_b64": base64.b64encode(CREDENTIAL_1).decode("ascii"),
            "now": BASE.isoformat(),
        }
    )
    assert result["ok"] is True
    assert result["binding"]["credential_digest_exposed"] is False
    assert port.load(authority_ref=AUTHORITY_REF).version == 1
    raw = backend.load(authority_ref=AUTHORITY_REF)
    assert raw is not None
    assert CREDENTIAL_1 not in raw.payload


def test_m2g_source_truth_does_not_claim_database_or_production() -> None:
    backend = InMemorySerializedLocalAgentBrokerStateBackend()
    safe = _port(backend).safe_dict()
    assert safe["backend_durable"] is False
    assert BROKER_STATE_JSON_CODEC is True
    assert DETERMINISTIC_WIRE_ENCODING is True
    assert CLOSED_WIRE_SCHEMA is True
    assert DUPLICATE_JSON_KEY_REJECTED is True
    assert BOUNDED_SERIALIZED_STATE is True
    assert ATOMIC_SERIALIZED_BACKEND_PORT is True
    assert SERIALIZED_STATE_ADAPTER_TO_M2F is True
    assert CANONICAL_SNAPSHOT_VALIDATION_REUSED is True
    assert RAW_DEVICE_CREDENTIAL_SERIALIZED is False
    assert PICKLE_OR_ARBITRARY_OBJECT_DESERIALIZATION is False
    assert IN_MEMORY_SERIALIZED_BACKEND_COUNTS_AS_DURABLE is False
    assert DATABASE_DRIVER_SELECTED is False
    assert PROVIDER_SPECIFIC_SQL is False
    assert PRODUCTION_STORE_CONFIGURED is False
    assert PRODUCTION_MUTATION is False
    assert PRODUCTION_READY is False
