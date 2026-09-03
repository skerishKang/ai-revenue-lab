from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import (
    ADMISSION_BEFORE_ACK,
    BOUND_BROKER_SESSION,
    COMMAND_CREDENTIAL_GENERATION_BOUND,
    EXACT_REQUEST_FINGERPRINT,
    KEYED_DEVICE_CREDENTIAL_DIGEST_ONLY,
    MONOTONIC_COMMAND_SEQUENCE,
    P01_AUTHORITY_DUPLICATED,
    PRODUCTION_DEPLOYMENT,
    PRODUCTION_READY,
    PUBLIC_HTTP_ENDPOINT,
    RAW_ARGV_IN_BROKER_COMMAND,
    RAW_DEVICE_CREDENTIAL_PERSISTED,
    SERVER_SIDE_LOCAL_AGENT_BROKER_AUTHORITY,
    BrokerBindingState,
    BrokerCommandState,
    InMemoryLocalAgentBrokerAuthority,
)

NOW = datetime(2026, 9, 3, 13, 30, tzinfo=timezone.utc)
PEPPER = b"padiem-local-agent-broker-test-pepper"
CREDENTIAL_1 = b"device-credential-generation-one"
CREDENTIAL_2 = b"device-credential-generation-two"
FINGERPRINT_1 = "1" * 64
FINGERPRINT_2 = "2" * 64


def authority() -> InMemoryLocalAgentBrokerAuthority:
    return InMemoryLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref="control-plane.local-agent-broker.v1",
    )


def register(service: InMemoryLocalAgentBrokerAuthority, *, now: datetime = NOW):
    return service.register_binding(
        binding_ref="binding.1",
        device_id="device.1",
        account_ref="account.1",
        workspace_ref="workspace.1",
        credential=CREDENTIAL_1,
        now=now,
    )


def open_session(
    service: InMemoryLocalAgentBrokerAuthority,
    *,
    credential: bytes = CREDENTIAL_1,
    session_id: str = "session.1",
    now: datetime = NOW + timedelta(seconds=1),
):
    return service.open_session(
        session_id=session_id,
        binding_ref="binding.1",
        credential=credential,
        account_ref="account.1",
        workspace_ref="workspace.1",
        now=now,
    )


def enqueue(
    service: InMemoryLocalAgentBrokerAuthority,
    *,
    command_id: str = "command.1",
    fingerprint: str = FINGERPRINT_1,
    now: datetime = NOW + timedelta(seconds=2),
):
    return service.enqueue_command(
        command_id=command_id,
        binding_ref="binding.1",
        run_id="run.1",
        tool_request_ref=f"tool-request.{command_id}",
        request_fingerprint=fingerprint,
        now=now,
    )


def admit(
    service: InMemoryLocalAgentBrokerAuthority,
    *,
    command_id: str = "command.1",
    fingerprint: str = FINGERPRINT_1,
    credential: bytes = CREDENTIAL_1,
    session_id: str = "session.1",
    now: datetime = NOW + timedelta(seconds=3),
):
    return service.admit_command(
        admission_ref=f"admission.{command_id}",
        evidence_ref=f"evidence.{command_id}",
        session_id=session_id,
        binding_ref="binding.1",
        credential=credential,
        command_id=command_id,
        request_fingerprint=fingerprint,
        now=now,
    )


def error_code(exc_info) -> str:
    assert isinstance(exc_info.value, ControlPlaneContractError)
    return exc_info.value.code


def test_binding_keeps_only_keyed_digest_and_safe_projection_redacts_it():
    service = authority()
    binding = register(service)

    assert binding.credential_digest != CREDENTIAL_1.decode()
    assert len(binding.credential_digest) == 64
    public = binding.safe_dict()
    assert public["credential_digest_exposed"] is False
    assert public["raw_device_credential"] is False
    assert "credential_digest" not in public
    assert CREDENTIAL_1.decode() not in repr(public)


def test_wrong_credential_and_scope_fail_closed():
    service = authority()
    register(service)

    with pytest.raises(ControlPlaneContractError) as wrong_credential:
        open_session(service, credential=b"wrong-credential")
    assert error_code(wrong_credential) == "invalid_device_credential"

    with pytest.raises(ControlPlaneContractError) as wrong_scope:
        service.open_session(
            session_id="session.bad-scope",
            binding_ref="binding.1",
            credential=CREDENTIAL_1,
            account_ref="account.other",
            workspace_ref="workspace.1",
            now=NOW + timedelta(seconds=1),
        )
    assert error_code(wrong_scope) == "device_binding_scope_mismatch"


def test_session_is_bounded_by_current_credential_expiry():
    service = authority()
    service.register_binding(
        binding_ref="binding.1",
        device_id="device.1",
        account_ref="account.1",
        workspace_ref="workspace.1",
        credential=CREDENTIAL_1,
        now=NOW,
        credential_ttl_seconds=300,
    )
    session = open_session(service, now=NOW + timedelta(seconds=1))
    assert session.expires_at == NOW + timedelta(seconds=300)

    with pytest.raises(ControlPlaneContractError) as expired:
        service.poll(
            session_id=session.session_id,
            binding_ref="binding.1",
            credential=CREDENTIAL_1,
            after_sequence=0,
            now=session.expires_at,
        )
    assert error_code(expired) in {"device_credential_expired", "device_session_expired"}


def test_enqueue_and_poll_use_monotonic_sequence_and_after_cursor():
    service = authority()
    register(service)
    session = open_session(service)
    first = enqueue(service, command_id="command.1", fingerprint=FINGERPRINT_1)
    second = enqueue(
        service,
        command_id="command.2",
        fingerprint=FINGERPRINT_2,
        now=NOW + timedelta(seconds=3),
    )

    assert (first.sequence, second.sequence) == (1, 2)
    all_items = service.poll(
        session_id=session.session_id,
        binding_ref="binding.1",
        credential=CREDENTIAL_1,
        after_sequence=0,
        now=NOW + timedelta(seconds=4),
    )
    assert [item.command_id for item in all_items] == ["command.1", "command.2"]

    after_first = service.poll(
        session_id=session.session_id,
        binding_ref="binding.1",
        credential=CREDENTIAL_1,
        after_sequence=1,
        now=NOW + timedelta(seconds=4),
    )
    assert [item.command_id for item in after_first] == ["command.2"]


def test_admission_requires_exact_fingerprint_and_is_single_use():
    service = authority()
    register(service)
    open_session(service)
    enqueue(service)

    with pytest.raises(ControlPlaneContractError) as mismatch:
        admit(service, fingerprint=FINGERPRINT_2)
    assert error_code(mismatch) == "broker_command_fingerprint_mismatch"

    admission = admit(service)
    public = admission.to_public_dict()
    assert admission.authority_ref == "control-plane.local-agent-broker.v1"
    assert admission.request_fingerprint == FINGERPRINT_1
    assert public["raw_argv"] is False
    assert public["raw_device_credential"] is False

    with pytest.raises(ControlPlaneContractError) as replay:
        admit(service, now=NOW + timedelta(seconds=4))
    assert error_code(replay) == "broker_command_replay"


def test_ack_requires_exact_admission_evidence_and_is_single_use():
    service = authority()
    register(service)
    open_session(service)
    enqueue(service)

    with pytest.raises(ControlPlaneContractError) as before_admission:
        service.acknowledge(
            session_id="session.1",
            binding_ref="binding.1",
            credential=CREDENTIAL_1,
            command_id="command.1",
            admission_ref="admission.command.1",
            evidence_ref="evidence.command.1",
            now=NOW + timedelta(seconds=3),
        )
    assert error_code(before_admission) == "broker_ack_without_admission"

    admit(service)
    with pytest.raises(ControlPlaneContractError) as wrong_evidence:
        service.acknowledge(
            session_id="session.1",
            binding_ref="binding.1",
            credential=CREDENTIAL_1,
            command_id="command.1",
            admission_ref="admission.command.1",
            evidence_ref="evidence.wrong",
            now=NOW + timedelta(seconds=4),
        )
    assert error_code(wrong_evidence) == "broker_ack_correlation_mismatch"

    acked = service.acknowledge(
        session_id="session.1",
        binding_ref="binding.1",
        credential=CREDENTIAL_1,
        command_id="command.1",
        admission_ref="admission.command.1",
        evidence_ref="evidence.command.1",
        now=NOW + timedelta(seconds=4),
    )
    assert acked.state is BrokerCommandState.ACKNOWLEDGED

    with pytest.raises(ControlPlaneContractError) as replay_ack:
        service.acknowledge(
            session_id="session.1",
            binding_ref="binding.1",
            credential=CREDENTIAL_1,
            command_id="command.1",
            admission_ref="admission.command.1",
            evidence_ref="evidence.command.1",
            now=NOW + timedelta(seconds=5),
        )
    assert error_code(replay_ack) == "broker_ack_without_admission"


def test_rotation_invalidates_old_sessions_credentials_and_queued_generation():
    service = authority()
    register(service)
    old_session = open_session(service)
    old_command = enqueue(service)
    assert old_command.credential_generation == 1

    rotated = service.rotate_credential(
        "binding.1",
        expected_generation=1,
        new_credential=CREDENTIAL_2,
        now=NOW + timedelta(seconds=10),
    )
    assert rotated.credential_generation == 2

    with pytest.raises(ControlPlaneContractError) as old_credential:
        service.open_session(
            session_id="session.old-credential",
            binding_ref="binding.1",
            credential=CREDENTIAL_1,
            account_ref="account.1",
            workspace_ref="workspace.1",
            now=NOW + timedelta(seconds=11),
        )
    assert error_code(old_credential) == "invalid_device_credential"

    with pytest.raises(ControlPlaneContractError) as old_session_missing:
        service.poll(
            session_id=old_session.session_id,
            binding_ref="binding.1",
            credential=CREDENTIAL_2,
            after_sequence=0,
            now=NOW + timedelta(seconds=11),
        )
    assert error_code(old_session_missing) == "device_session_not_found"

    new_session = open_session(
        service,
        credential=CREDENTIAL_2,
        session_id="session.2",
        now=NOW + timedelta(seconds=12),
    )
    assert service.poll(
        session_id=new_session.session_id,
        binding_ref="binding.1",
        credential=CREDENTIAL_2,
        after_sequence=0,
        now=NOW + timedelta(seconds=13),
    ) == ()

    with pytest.raises(ControlPlaneContractError) as stale_command:
        service.admit_command(
            admission_ref="admission.old",
            evidence_ref="evidence.old",
            session_id=new_session.session_id,
            binding_ref="binding.1",
            credential=CREDENTIAL_2,
            command_id="command.1",
            request_fingerprint=FINGERPRINT_1,
            now=NOW + timedelta(seconds=13),
        )
    assert error_code(stale_command) == "stale_broker_command_generation"

    fresh = enqueue(
        service,
        command_id="command.2",
        fingerprint=FINGERPRINT_2,
        now=NOW + timedelta(seconds=14),
    )
    assert fresh.credential_generation == 2
    assert fresh.sequence == 2


def test_revoke_blocks_future_session_and_poll():
    service = authority()
    register(service)
    session = open_session(service)
    service.revoke_binding("binding.1", now=NOW + timedelta(seconds=5))

    with pytest.raises(ControlPlaneContractError) as revoked_session:
        service.open_session(
            session_id="session.after-revoke",
            binding_ref="binding.1",
            credential=CREDENTIAL_1,
            account_ref="account.1",
            workspace_ref="workspace.1",
            now=NOW + timedelta(seconds=6),
        )
    assert error_code(revoked_session) == "device_binding_revoked"

    with pytest.raises(ControlPlaneContractError) as revoked_poll:
        service.poll(
            session_id=session.session_id,
            binding_ref="binding.1",
            credential=CREDENTIAL_1,
            after_sequence=0,
            now=NOW + timedelta(seconds=6),
        )
    assert error_code(revoked_poll) == "device_binding_revoked"


def test_expired_command_is_not_polled_or_admitted():
    service = authority()
    register(service)
    session = open_session(service)
    enqueue(service, now=NOW + timedelta(seconds=2))
    expired_at = NOW + timedelta(seconds=302)

    assert service.poll(
        session_id=session.session_id,
        binding_ref="binding.1",
        credential=CREDENTIAL_1,
        after_sequence=0,
        now=expired_at,
    ) == ()

    with pytest.raises(ControlPlaneContractError) as expired:
        admit(service, now=expired_at)
    assert error_code(expired) == "broker_command_expired"


def test_safe_command_projection_contains_only_bounded_metadata():
    service = authority()
    register(service)
    command = enqueue(service)
    public = command.safe_dict()

    assert public["raw_argv"] is False
    assert public["raw_file_content"] is False
    assert public["raw_device_credential"] is False
    assert public["p01_approval_payload"] is False
    assert "credential_digest" not in public
    assert "credential" not in public


def test_source_truth_constants_preserve_non_live_boundaries():
    assert SERVER_SIDE_LOCAL_AGENT_BROKER_AUTHORITY is True
    assert KEYED_DEVICE_CREDENTIAL_DIGEST_ONLY is True
    assert BOUND_BROKER_SESSION is True
    assert MONOTONIC_COMMAND_SEQUENCE is True
    assert COMMAND_CREDENTIAL_GENERATION_BOUND is True
    assert EXACT_REQUEST_FINGERPRINT is True
    assert ADMISSION_BEFORE_ACK is True
    assert RAW_ARGV_IN_BROKER_COMMAND is False
    assert RAW_DEVICE_CREDENTIAL_PERSISTED is False
    assert P01_AUTHORITY_DUPLICATED is False
    assert PUBLIC_HTTP_ENDPOINT is False
    assert PRODUCTION_DEPLOYMENT is False
    assert PRODUCTION_READY is False
