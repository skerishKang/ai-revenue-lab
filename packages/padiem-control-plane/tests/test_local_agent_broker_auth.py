from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_auth import (
    AUTHENTICATION_STATE_MUTATION,
    CANONICAL_BROKER_CREDENTIAL_VERIFIER_REUSED,
    RAW_DEVICE_CREDENTIAL_RETURNED,
    READ_ONLY_BINDING_AUTHENTICATION,
    SECOND_CREDENTIAL_VERIFIER,
    StateBackedLocalAgentBindingAuthenticator,
)
from padiem_control_plane.local_agent_broker_state import (
    InMemoryLocalAgentBrokerStatePort,
    StateBackedLocalAgentBrokerAuthority,
)


BASE = datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.auth-test.v1"
PEPPER = b"read-only-auth-test-pepper-value"
CREDENTIAL_1 = b"read-only-auth-device-credential-1"
CREDENTIAL_2 = b"read-only-auth-device-credential-2"


class _DurableMemoryStatePort(InMemoryLocalAgentBrokerStatePort):
    durable = True


def _fixture():
    state = _DurableMemoryStatePort()
    authority = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=state,
    )
    authority.register_binding(
        binding_ref="binding.auth.1",
        device_id="device.auth.1",
        account_ref="account.auth.1",
        workspace_ref="workspace.auth.1",
        credential=CREDENTIAL_1,
        now=BASE,
        credential_ttl_seconds=3600,
    )
    authenticator = StateBackedLocalAgentBindingAuthenticator(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=state,
    )
    return state, authority, authenticator


def test_read_only_binding_auth_reuses_canonical_verifier_without_state_write() -> None:
    state, _, authenticator = _fixture()
    before = state.load(authority_ref=AUTHORITY_REF)

    binding = authenticator.authenticate(
        binding_ref="binding.auth.1",
        credential=CREDENTIAL_1,
        now=BASE + timedelta(seconds=1),
    )

    after = state.load(authority_ref=AUTHORITY_REF)
    assert binding.binding_ref == "binding.auth.1"
    assert binding.device_id == "device.auth.1"
    assert binding.account_ref == "account.auth.1"
    assert binding.workspace_ref == "workspace.auth.1"
    assert after.version == before.version
    assert after.snapshot == before.snapshot
    safe = authenticator.safe_dict()
    assert safe["read_only_binding_authentication"] is True
    assert safe["canonical_broker_credential_verifier_reused"] is True
    assert safe["second_credential_verifier"] is False
    assert safe["state_mutation"] is False
    assert safe["credential_digest_exposed"] is False
    assert safe["raw_device_credential_returned"] is False


def test_wrong_rotated_revoked_and_expired_credentials_fail_closed() -> None:
    _, authority, authenticator = _fixture()

    with pytest.raises(ControlPlaneContractError) as wrong:
        authenticator.authenticate(
            binding_ref="binding.auth.1",
            credential=b"wrong-device-credential",
            now=BASE + timedelta(seconds=1),
        )
    assert wrong.value.code == "invalid_device_credential"

    authority.rotate_credential(
        "binding.auth.1",
        expected_generation=1,
        new_credential=CREDENTIAL_2,
        now=BASE + timedelta(minutes=1),
        credential_ttl_seconds=3600,
    )
    with pytest.raises(ControlPlaneContractError) as stale:
        authenticator.authenticate(
            binding_ref="binding.auth.1",
            credential=CREDENTIAL_1,
            now=BASE + timedelta(minutes=1, seconds=1),
        )
    assert stale.value.code == "invalid_device_credential"

    rotated = authenticator.authenticate(
        binding_ref="binding.auth.1",
        credential=CREDENTIAL_2,
        now=BASE + timedelta(minutes=1, seconds=1),
    )
    assert rotated.credential_generation == 2

    authority.revoke_binding("binding.auth.1", now=BASE + timedelta(minutes=2))
    with pytest.raises(ControlPlaneContractError) as revoked:
        authenticator.authenticate(
            binding_ref="binding.auth.1",
            credential=CREDENTIAL_2,
            now=BASE + timedelta(minutes=2, seconds=1),
        )
    assert revoked.value.code == "device_binding_revoked"

    state = _DurableMemoryStatePort()
    expiring = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref="control-plane.local-agent-broker.expiry-test.v1",
        state_port=state,
    )
    expiring.register_binding(
        binding_ref="binding.expiry.1",
        device_id="device.expiry.1",
        account_ref="account.expiry.1",
        workspace_ref="workspace.expiry.1",
        credential=CREDENTIAL_1,
        now=BASE,
        credential_ttl_seconds=300,
    )
    expiry_auth = StateBackedLocalAgentBindingAuthenticator(
        pepper=PEPPER,
        authority_ref="control-plane.local-agent-broker.expiry-test.v1",
        state_port=state,
    )
    with pytest.raises(ControlPlaneContractError) as expired:
        expiry_auth.authenticate(
            binding_ref="binding.expiry.1",
            credential=CREDENTIAL_1,
            now=BASE + timedelta(seconds=300),
        )
    assert expired.value.code == "device_credential_expired"


def test_authentication_boundary_truth_constants() -> None:
    assert READ_ONLY_BINDING_AUTHENTICATION is True
    assert CANONICAL_BROKER_CREDENTIAL_VERIFIER_REUSED is True
    assert SECOND_CREDENTIAL_VERIFIER is False
    assert AUTHENTICATION_STATE_MUTATION is False
    assert RAW_DEVICE_CREDENTIAL_RETURNED is False
