from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_pairing import (
    BROKER_PAIRING_AUTHORITY,
    CANONICAL_BROKER_BINDING_AUTHORITY_REUSED,
    DURABLE_PAIRING_STORE_CONFIGURED,
    IN_MEMORY_COUNTS_AS_DURABLE,
    MAX_PENDING_PAIRING_CHALLENGES,
    PAIRING_CODE_HEX_CHARS,
    PAIRING_CODE_SINGLE_USE,
    PAIRING_PROOF_TRANSCRIPT,
    PRODUCTION_READY,
    PUBLIC_INBOUND_PORT_REQUIRED,
    RAW_DEVICE_CREDENTIAL_PERSISTED,
    RAW_DEVICE_CREDENTIAL_RETURNED_ONCE,
    RAW_PAIRING_CODE_PERSISTED,
    SECOND_CREDENTIAL_VERIFIER,
    SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY,
    SERVER_OWNED_PAIRING_REFS,
    BrokerPairingChallenge,
    InMemoryBrokerPairingAuthority,
    UnconfiguredBrokerPairingAuthority,
    pairing_proof_message,
    pairing_proof_ref,
)

NOW = datetime(2026, 9, 26, 4, 0, tzinfo=timezone.utc)
BROKER_PEPPER = b"control-plane-local-agent-broker-pepper"
PAIRING_PEPPER = b"control-plane-local-agent-pairing-pepper"
CREDENTIAL = b"pairing-redeemed-device-credential"
CODE = "0123456789abcdef0123456789abcdef"


def broker_authority() -> InMemoryLocalAgentBrokerAuthority:
    return InMemoryLocalAgentBrokerAuthority(
        pepper=BROKER_PEPPER,
        authority_ref="control-plane.local-agent-broker.v1",
    )


def pairing_authority(
    *,
    authority: InMemoryLocalAgentBrokerAuthority | None = None,
    code_nonce: str = "a" * 32,
) -> tuple[InMemoryBrokerPairingAuthority, InMemoryLocalAgentBrokerAuthority]:
    broker = authority or broker_authority()
    pairing = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER,
        authority=broker,
        code_nonce_factory=lambda: code_nonce,
        credential_factory=lambda: CREDENTIAL,
    )
    return pairing, broker


def issue(
    pairing: InMemoryBrokerPairingAuthority,
    *,
    now: datetime = NOW,
    ttl_seconds: int = 300,
    account_ref: str = "account.1",
    workspace_ref: str = "workspace.1",
) -> tuple[BrokerPairingChallenge, str]:
    return pairing.issue_challenge(
        account_ref=account_ref,
        workspace_ref=workspace_ref,
        now=now,
        ttl_seconds=ttl_seconds,
    )


def test_pairing_authority_satisfies_its_port() -> None:
    pairing, _ = pairing_authority()
    for method_name in ("issue_challenge", "redeem"):
        assert callable(getattr(pairing, method_name, None))
    assert callable(getattr(UnconfiguredBrokerPairingAuthority(), "issue_challenge", None))
    assert callable(getattr(UnconfiguredBrokerPairingAuthority(), "redeem", None))


def test_pairing_challenge_is_short_lived_and_never_exposes_code_material() -> None:
    pairing, _ = pairing_authority()
    challenge, code = issue(pairing)

    rendered = challenge.safe_dict()
    assert rendered["single_use"] is True
    assert rendered["raw_pairing_secret"] is False
    assert rendered["client_time_authority"] is False
    assert rendered["account_ref"] == "account.1"
    assert rendered["workspace_ref"] == "workspace.1"
    assert code != challenge.challenge_id
    assert code.islower() and len(code) == PAIRING_CODE_HEX_CHARS and all(char in "0123456789abcdef" for char in code)
    assert code not in str(rendered)

    with pytest.raises(ControlPlaneContractError):
        BrokerPairingChallenge(
            challenge_id="pairing.x",
            account_ref="account.1",
            workspace_ref="workspace.1",
            issued_at=NOW,
            expires_at=NOW + timedelta(seconds=601),
        )
    with pytest.raises(ControlPlaneContractError):
        issue(pairing, ttl_seconds=10)
    with pytest.raises(ControlPlaneContractError):
        issue(pairing, ttl_seconds=601)


def test_redeem_registers_the_canonical_broker_binding_and_returns_one_credential() -> None:
    pairing, broker = pairing_authority()
    challenge, code = issue(pairing)
    proof = pairing_proof_ref(challenge_id=challenge.challenge_id, device_id="device.1", pairing_code=code)

    enrollment, credential = pairing.redeem(
        challenge_id=challenge.challenge_id,
        device_id="device.1",
        proof_ref=proof,
        now=NOW + timedelta(seconds=1),
    )

    assert credential == CREDENTIAL
    assert enrollment.device_id == "device.1"
    assert enrollment.account_ref == "account.1"
    assert enrollment.workspace_ref == "workspace.1"
    assert enrollment.credential_generation == 1
    assert enrollment.credential_expires_at > enrollment.issued_at
    rendered = enrollment.safe_dict()
    assert rendered["server_owned_binding_refs"] is True
    assert rendered["raw_device_credential"] is False
    assert CREDENTIAL.decode() not in str(rendered)

    # The redeemed credential is a real canonical broker credential.
    session = broker.open_session(
        session_id="session.pairing.1",
        binding_ref=enrollment.binding_ref,
        credential=credential,
        account_ref="account.1",
        workspace_ref="workspace.1",
        now=NOW + timedelta(seconds=2),
    )
    assert session.device_id == "device.1"
    assert session.credential_generation == enrollment.credential_generation

    # Only the deployment-pepper digest of the credential is retained by the broker.
    stored = broker._bindings[enrollment.binding_ref]
    assert credential not in stored.credential_digest.encode("utf-8")
    assert stored.safe_dict()["credential_digest_exposed"] is False
    assert stored.safe_dict()["raw_device_credential"] is False

    with pytest.raises(ControlPlaneContractError) as replay:
        pairing.redeem(
            challenge_id=challenge.challenge_id,
            device_id="device.1",
            proof_ref=proof,
            now=NOW + timedelta(seconds=3),
        )
    assert replay.value.code == "pairing_challenge_already_redeemed"


def test_bad_proof_expired_and_unknown_challenges_fail_closed() -> None:
    pairing, broker = pairing_authority()
    challenge, code = issue(pairing, ttl_seconds=60)

    with pytest.raises(ControlPlaneContractError) as unknown:
        pairing.redeem(
            challenge_id="pairing.ffffffffffffffffffffffffffffffff",
            device_id="device.1",
            proof_ref=pairing_proof_ref(
                challenge_id="pairing.ffffffffffffffffffffffffffffffff",
                device_id="device.1",
                pairing_code=CODE,
            ),
            now=NOW,
        )
    assert unknown.value.code == "pairing_challenge_not_found"

    wrong_device = pairing_proof_ref(
        challenge_id=challenge.challenge_id,
        device_id="device.2",
        pairing_code=code,
    )
    with pytest.raises(ControlPlaneContractError) as mismatch:
        pairing.redeem(
            challenge_id=challenge.challenge_id,
            device_id="device.1",
            proof_ref=wrong_device,
            now=NOW,
        )
    assert mismatch.value.code == "invalid_pairing_proof"

    with pytest.raises(ControlPlaneContractError) as malformed:
        pairing.redeem(
            challenge_id=challenge.challenge_id,
            device_id="device.1",
            proof_ref="pairing-proof:not-a-digest",
            now=NOW,
        )
    assert malformed.value.code == "invalid_pairing_proof"

    # Rejected proofs never consume the challenge or mint a binding.
    expired_at = challenge.expires_at
    with pytest.raises(ControlPlaneContractError) as expired:
        pairing.redeem(
            challenge_id=challenge.challenge_id,
            device_id="device.1",
            proof_ref=pairing_proof_ref(
                challenge_id=challenge.challenge_id,
                device_id="device.1",
                pairing_code=code,
            ),
            now=expired_at,
        )
    assert expired.value.code == "pairing_challenge_expired"
    assert broker._bindings == {}


def test_duplicate_device_redeem_consumes_the_challenge_without_minting_a_binding() -> None:
    broker = broker_authority()
    nonces = iter(["b" * 32, "c" * 32])
    pairing = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER,
        authority=broker,
        code_nonce_factory=lambda: next(nonces),
        credential_factory=lambda: CREDENTIAL,
    )
    first, first_code = issue(pairing)
    first_entry, _ = pairing.redeem(
        challenge_id=first.challenge_id,
        device_id="device.1",
        proof_ref=pairing_proof_ref(
            challenge_id=first.challenge_id,
            device_id="device.1",
            pairing_code=first_code,
        ),
        now=NOW,
    )
    second, second_code = issue(pairing, now=NOW + timedelta(seconds=1))

    with pytest.raises(ControlPlaneContractError) as duplicate:
        pairing.redeem(
            challenge_id=second.challenge_id,
            device_id="device.1",
            proof_ref=pairing_proof_ref(
                challenge_id=second.challenge_id,
                device_id="device.1",
                pairing_code=second_code,
            ),
            now=NOW + timedelta(seconds=1),
        )
    assert duplicate.value.code == "duplicate_device_binding"

    # The burned second challenge cannot be retried into a second binding.
    with pytest.raises(ControlPlaneContractError) as replay:
        pairing.redeem(
            challenge_id=second.challenge_id,
            device_id="device.1",
            proof_ref=pairing_proof_ref(
                challenge_id=second.challenge_id,
                device_id="device.1",
                pairing_code=second_code,
            ),
            now=NOW + timedelta(seconds=2),
        )
    assert replay.value.code == "pairing_challenge_already_redeemed"
    assert set(broker._bindings) == {first_entry.binding_ref}


def test_pending_challenge_capacity_and_unconfigured_authority_fail_closed() -> None:
    counter = {"value": 0}

    def nonce() -> str:
        counter["value"] += 1
        return f"{counter['value']:032x}"

    pairing = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER,
        authority=broker_authority(),
        code_nonce_factory=nonce,
    )
    for _ in range(MAX_PENDING_PAIRING_CHALLENGES):
        issue(pairing)
    assert pairing.pending_challenge_count == MAX_PENDING_PAIRING_CHALLENGES
    with pytest.raises(ControlPlaneContractError) as exhausted:
        issue(pairing)
    assert exhausted.value.code == "pairing_capacity_exhausted"

    with pytest.raises(RuntimeError):
        UnconfiguredBrokerPairingAuthority().issue_challenge(
            account_ref="account.1",
            workspace_ref="workspace.1",
            now=NOW,
        )
    with pytest.raises(RuntimeError):
        UnconfiguredBrokerPairingAuthority().redeem(
            challenge_id="pairing.x",
            device_id="device.1",
            proof_ref="pairing-proof:" + "0" * 64,
            now=NOW,
        )
    with pytest.raises(ControlPlaneContractError):
        InMemoryBrokerPairingAuthority(pepper=b"short", authority=broker_authority())
    with pytest.raises(ControlPlaneContractError):
        InMemoryBrokerPairingAuthority(pepper=PAIRING_PEPPER, authority=object())


def test_pairing_transcript_is_versioned_and_code_entropy_is_not_persisted() -> None:
    message = pairing_proof_message(challenge_id="pairing.1", device_id="device.1")
    assert message == b"claw-local-agent-pairing-proof.v1\npairing.1\ndevice.1"
    assert PAIRING_PROOF_TRANSCRIPT == "claw-local-agent-pairing-proof.v1"

    pairing, _ = pairing_authority()
    challenge, code = issue(pairing)
    proof = pairing_proof_ref(challenge_id=challenge.challenge_id, device_id="device.1", pairing_code=code)
    assert proof.startswith("pairing-proof:")
    assert len(proof) == len("pairing-proof:") + 64

    # Two challenges never share a code, and the code is not a function of the public id alone.
    other_nonce = "f" * 32
    pairing_two = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER,
        authority=broker_authority(),
        code_nonce_factory=lambda: other_nonce,
    )
    _, other_code = issue(pairing_two)
    assert other_code != code
    with pytest.raises(ControlPlaneContractError) as bad_code:
        pairing_proof_ref(
            challenge_id=challenge.challenge_id,
            device_id="device.1",
            pairing_code="NOT-HEX",
        )
    assert bad_code.value.code == "invalid_pairing_code"

    rendered = pairing.safe_dict()
    assert rendered["pairing_proof_algorithm"] == "HMAC-SHA256"
    assert rendered["raw_pairing_code_persisted"] is False
    assert rendered["raw_device_credential_persisted"] is False
    assert rendered["raw_device_credential_returned_once"] is True
    assert rendered["server_owned_credential_digests"] is True
    assert rendered["canonical_broker_binding_authority_reused"] is True
    assert rendered["second_credential_verifier"] is False
    assert rendered["pending_challenge_count"] == 1


def test_state_backed_authority_persists_redeemed_bindings_through_the_canonical_cas_boundary() -> None:
    from padiem_control_plane.local_agent_broker_state import (
        InMemoryLocalAgentBrokerStatePort,
        StateBackedLocalAgentBrokerAuthority,
    )

    state_port = InMemoryLocalAgentBrokerStatePort()
    authority_ref = "control-plane.local-agent-broker.state-backed.v1"
    broker = StateBackedLocalAgentBrokerAuthority(
        pepper=BROKER_PEPPER,
        authority_ref=authority_ref,
        state_port=state_port,
    )
    pairing, _ = pairing_authority(authority=broker)
    challenge, code = issue(pairing)
    enrollment, credential = pairing.redeem(
        challenge_id=challenge.challenge_id,
        device_id="device.1",
        proof_ref=pairing_proof_ref(
            challenge_id=challenge.challenge_id,
            device_id="device.1",
            pairing_code=code,
        ),
        now=NOW,
    )

    # A fresh state-backed instance reloads the redeemed binding through CAS.
    reloaded = StateBackedLocalAgentBrokerAuthority(
        pepper=BROKER_PEPPER,
        authority_ref=authority_ref,
        state_port=state_port,
    )
    session = reloaded.open_session(
        session_id="session.state_backed.1",
        binding_ref=enrollment.binding_ref,
        credential=credential,
        account_ref="account.1",
        workspace_ref="workspace.1",
        now=NOW + timedelta(seconds=1),
    )
    assert session.device_id == "device.1"

    # Pairing challenge state is explicitly ephemeral and is not part of that
    # durable broker snapshot.
    assert pairing.pending_challenge_count == 1
    assert state_port.durable is False
    assert IN_MEMORY_COUNTS_AS_DURABLE is False


def test_pairing_authority_truth_constants_do_not_overclaim() -> None:
    assert BROKER_PAIRING_AUTHORITY is True
    assert PAIRING_CODE_SINGLE_USE is True
    assert RAW_DEVICE_CREDENTIAL_RETURNED_ONCE is True
    assert SERVER_OWNED_PAIRING_REFS is True
    assert CANONICAL_BROKER_BINDING_AUTHORITY_REUSED is True
    assert RAW_PAIRING_CODE_PERSISTED is False
    assert RAW_DEVICE_CREDENTIAL_PERSISTED is False
    assert SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY is False
    assert SECOND_CREDENTIAL_VERIFIER is False
    assert PUBLIC_INBOUND_PORT_REQUIRED is False
    assert DURABLE_PAIRING_STORE_CONFIGURED is False
    assert IN_MEMORY_COUNTS_AS_DURABLE is False
    assert PRODUCTION_READY is False
