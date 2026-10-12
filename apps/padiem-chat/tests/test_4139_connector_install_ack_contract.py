"""#4139 pure server contract tests; no network or real Windows store."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.canonical_connector_credential_handoff import (
    DeviceCredentialInstallAck,
    INSTALL_ACK_TRANSCRIPT_VERSION,
    PROTECTED_INSTALL_TRANSPORT_WIRED,
    PROTECTED_INSTALL_PRODUCTION_ENABLED,
    UnconfiguredProtectedDeviceHandoff,
    installation_proof,
    verify_install_ack,
)

SECRET = b"synthetic-broker-credential-only"
CHALLENGE = "pairing." + "a" * 32
DEVICE = "device.pc.1"
BINDING = "pairing-binding.1"
ENROLLMENT = {
    "binding_ref": BINDING, "device_id": DEVICE, "credential_generation": 1,
}


def make_ack(*, credential=SECRET, challenge_id=CHALLENGE,
             device_id=DEVICE, binding_ref=BINDING, generation=1):
    return DeviceCredentialInstallAck(
        challenge_id=challenge_id, device_id=device_id, binding_ref=binding_ref,
        credential_generation=generation,
        transcript_version=INSTALL_ACK_TRANSCRIPT_VERSION,
        proof_kind="protected_store_save_readback",
        local_store_confirmed=True,
        proof_hex=installation_proof(
            credential=credential, challenge_id=challenge_id, device_id=device_id,
            binding_ref=binding_ref, credential_generation=generation,
        ),
    )


def verified(ack, *, credential=SECRET):
    return verify_install_ack(
        ack=ack, credential=credential, challenge_id=CHALLENGE,
        device_id=DEVICE, enrollment=ENROLLMENT,
    )


def test_exact_keyed_ack_without_raw_credential_is_valid_for_expected_binding():
    ack = make_ack()
    assert verified(ack) is True
    assert set(ack.safe_dict()) == {
        "challenge_id", "device_id", "binding_ref", "credential_generation",
        "transcript_version", "proof_kind", "local_store_confirmed", "proof_hex",
    }
    assert SECRET not in repr(ack).encode()
    assert SECRET not in repr(ack.safe_dict()).encode()


@pytest.mark.parametrize("wrong", [
    b"wrong-secret-must-be-long-enough",
    b"synthetic-broker-credential-other",
])
def test_wrong_or_stale_credential_cannot_validate_install_ack(wrong):
    assert verified(make_ack(), credential=wrong) is False


@pytest.mark.parametrize("change", [
    {"challenge_id": "pairing.other"},
    {"device_id": "device.other"},
    {"binding_ref": "pairing-binding.other"},
    {"credential_generation": 2},
    {"proof_hex": "0"*64},
])
def test_replayed_or_swapped_ack_fails_for_original_pairing(change):
    ack = replace(make_ack(), **change)
    assert verified(ack) is False


@pytest.mark.parametrize("change", [
    {"local_store_confirmed": False},
    {"local_store_confirmed": 1},
    {"transcript_version": "old"},
    {"proof_kind": "server_says_installed"},
    {"credential_generation": True},
    {"proof_hex": "not-a-proof"},
])
def test_boolean_self_assertions_or_unreviewed_attestations_rejected(change):
    with pytest.raises(ValueError):
        replace(make_ack(), **change)


@pytest.mark.parametrize("bad_ack", [
    True,
    False,
    {"installed": True},
    {"proof_hex": "0"*64},
    None,
])
def test_bare_bool_or_untrusted_dict_is_not_install_ack(bad_ack):
    assert verified(bad_ack) is False


def test_proof_keyed_to_every_binding_field():
    base = installation_proof(
        credential=SECRET, challenge_id=CHALLENGE, device_id=DEVICE,
        binding_ref=BINDING, credential_generation=1,
    )
    for fields in (
        {"challenge_id": "pairing.other"},
        {"device_id": "device.other"},
        {"binding_ref": "pairing-binding.other"},
        {"credential_generation": 2},
    ):
        data = dict(
            credential=SECRET, challenge_id=CHALLENGE, device_id=DEVICE,
            binding_ref=BINDING, credential_generation=1,
        )
        data.update(fields)
        assert installation_proof(**data) != base


def test_handoff_is_default_off_even_with_valid_synthetic_receipt():
    assert PROTECTED_INSTALL_TRANSPORT_WIRED is False
    assert PROTECTED_INSTALL_PRODUCTION_ENABLED is False
    disabled = UnconfiguredProtectedDeviceHandoff()
    assert asyncio.run(disabled.ready(challenge_id=CHALLENGE, device_id=DEVICE)) is False
    assert asyncio.run(disabled.verify_authenticated_ack(
        challenge_id=CHALLENGE, device_id=DEVICE, ack=make_ack(),
    )) is False
    with pytest.raises(RuntimeError):
        asyncio.run(disabled.deliver_once(
            challenge_id=CHALLENGE, device_id=DEVICE,
            credential=SECRET, enrollment=ENROLLMENT, now=None,
        ))


def test_bad_credential_never_becomes_a_valid_proof():
    for bad in (b"", b"short", "string-not-bytes", None):
        with pytest.raises(ValueError):
            installation_proof(
                credential=bad, challenge_id=CHALLENGE,
                device_id=DEVICE, binding_ref=BINDING,
                credential_generation=1,
            )
