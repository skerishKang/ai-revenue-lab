"""Async cross-DO host tests; no live API or credential store is fabricated."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest

from app.canonical_connector_enrollment_async_host import CanonicalConnectorEnrollmentAsyncHost
from app.canonical_connector_credential_handoff import (
    DeviceCredentialInstallAck,
    INSTALL_ACK_TRANSCRIPT_VERSION,
    installation_proof,
)
from app.control_plane_identity import IdentityBridgeError

NOW = datetime.now(timezone.utc)
CHALLENGE = {
    "challenge_id": "pairing."+"a"*32, "account_ref": "account.1",
    "workspace_ref": "workspace.1", "issued_at": NOW.isoformat(),
    "expires_at": (NOW+timedelta(minutes=5)).isoformat(),
}
CONSENT = {
    "consent_id": "consent.1", "device_id": "device.1",
    "owner_subject_id": "subject.1", "account_ref": "account.1",
    "workspace_ref": "workspace.1", "granted_at": NOW.isoformat(), "withdrawn_at": None,
}
BINDING = {
    "challenge_id": CHALLENGE["challenge_id"], "consent_ref": "consent.1",
    "owner_ref": "subject.1", "account_ref": "account.1",
    "workspace_ref": "workspace.1", "device_id": "device.1",
    "bound_at": NOW.isoformat(),
}
ENROLLMENT = {
    "binding_ref": "pairing-binding.1", "device_id": "device.1",
    "account_ref": "account.1", "workspace_ref": "workspace.1",
    "credential_generation": 1, "credential_expires_at": (NOW+timedelta(days=30)).isoformat(),
}


class Identity:
    def __init__(self):
        self.calls = []
        self.authorization_count = 0
        self.fail_reauthorization = False
        self.withdraw_after_install = False
        self.fail_bind = False
        self.withdraw_during_issue = False

    async def resolve_connector_enrollment_consent_for_device(self, *, session_id, device_id):
        self.calls.append(("consent", session_id, device_id))
        assert device_id == CONSENT["device_id"]
        current = dict(CONSENT)
        if self.withdraw_during_issue and sum(call[0] == "consent" for call in self.calls) >= 2:
            current["withdrawn_at"] = NOW.isoformat()
        return current

    async def bind_connector_enrollment_challenge(self, *, session_id, challenge_id, expires_at):
        self.calls.append(("bind", session_id, challenge_id, expires_at))
        if self.fail_bind:
            raise IdentityBridgeError(503, "store_unavailable", "offline")
        return {"challenge_id": challenge_id}

    async def authorize_connector_enrollment_redeem(self, **kwargs):
        self.calls.append(("authorize", kwargs))
        self.authorization_count += 1
        if (
            (self.fail_reauthorization and self.authorization_count >= 2)
            or (self.withdraw_after_install and self.authorization_count >= 3)
        ):
            raise IdentityBridgeError(403, "enrollment_consent_withdrawn", "withdrawn")
        return {
            "challenge_id": kwargs["challenge_id"], "consent_id": CONSENT["consent_id"],
            "device_id": kwargs["device_id"], "owner_subject_id": kwargs["owner_ref"],
            "account_ref": kwargs["account_ref"], "workspace_ref": kwargs["workspace_ref"],
        }


class Broker:
    def __init__(self):
        self.calls = []
        self.fail_revoke = False
        self.credential = b"one-time-secret-with-length"
    async def issue_enrollment_challenge(self, **kwargs):
        self.calls.append(("issue", kwargs))
        return dict(CHALLENGE), "f"*32
    async def get_enrollment_binding(self, *, challenge_id):
        self.calls.append(("binding", challenge_id))
        return dict(BINDING)
    async def verify_enrollment_bootstrap(self, **kwargs):
        self.calls.append(("preflight", kwargs))
        if getattr(self, "reject_bootstrap", False):
            raise IdentityBridgeError(403, "invalid_pairing_proof", "invalid")
        return {
            "challenge_id": kwargs["challenge_id"],
            "device_id": kwargs["device_id"],
            "proof_valid": True,
            "challenge_consumed": False,
        }

    async def redeem_enrollment(self, **kwargs):
        self.calls.append(("redeem", kwargs))
        return dict(ENROLLMENT), self.credential
    async def revoke_binding(self, *, binding_ref):
        self.calls.append(("revoke", binding_ref))
        if self.fail_revoke:
            raise IdentityBridgeError(503, "broker_revoke_unavailable", "offline")
        return {"binding_ref": binding_ref, "state": "revoked"}


class Handoff:
    def __init__(self, *, ready=True, delivered=True, authenticated=True, tamper=None):
        self._ready = ready
        self.delivered = delivered
        self.authenticated = authenticated
        self.tamper = tamper
        self.calls = []
    async def ready(self, *, challenge_id, device_id):
        self.calls.append(("ready", challenge_id, device_id))
        return self._ready
    async def deliver_once(self, *, challenge_id, device_id, credential, enrollment, now):
        self.calls.append(("deliver", challenge_id, device_id, credential, enrollment, now))
        assert credential == b"one-time-secret-with-length"
        if not self.delivered:
            return False  # a transport bool must not attest installation
        ack = DeviceCredentialInstallAck(
            challenge_id=challenge_id, device_id=device_id,
            binding_ref=enrollment["binding_ref"],
            credential_generation=enrollment["credential_generation"],
            proof_kind="protected_store_save_readback",
            transcript_version=INSTALL_ACK_TRANSCRIPT_VERSION,
            local_store_confirmed=True,
            proof_hex=installation_proof(
                credential=credential, challenge_id=challenge_id, device_id=device_id,
                binding_ref=enrollment["binding_ref"],
                credential_generation=enrollment["credential_generation"],
            ),
        )
        return replace(ack, **self.tamper) if self.tamper else ack

    async def verify_authenticated_ack(self, *, challenge_id, device_id, ack):
        self.calls.append(("verify", challenge_id, device_id))
        # Test double models a reviewed existing device-gateway identity check,
        # NOT evidence of a live Windows credential store.
        assert ack.challenge_id == challenge_id and ack.device_id == device_id
        return self.authenticated


def issue_host(identity=None, broker=None, handoff=None):
    return CanonicalConnectorEnrollmentAsyncHost(
        identity=identity or Identity(), broker=broker or Broker(),
        credential_handoff=handoff,
    )


def test_issue_binds_challenge_to_original_session_before_releasing_code():
    identity, broker = Identity(), Broker()
    result = asyncio.run(issue_host(identity, broker).issue(
        canonical_session_id="session.original.1", device_id="device.1"
    ))
    assert result["pairing_code"] == "f"*32
    assert result["challenge"]["challenge_id"] == CHALLENGE["challenge_id"]
    assert result["dispatch_authorized"] is False
    assert [x[0] for x in identity.calls] == ["consent", "consent", "bind"]
    assert [x[0] for x in broker.calls] == ["issue"]


def test_issue_fails_without_releasing_code_if_session_binding_cannot_persist():
    identity, broker = Identity(), Broker()
    identity.fail_bind = True
    with pytest.raises(IdentityBridgeError):
        asyncio.run(issue_host(identity, broker).issue(
            canonical_session_id="session.original.1", device_id="device.1"
        ))
    assert len(broker.calls) == 1  # an orphan challenge exists but no code is returned


def test_issue_does_not_release_code_if_consent_is_withdrawn_after_challenge_creation():
    identity, broker = Identity(), Broker()
    identity.withdraw_during_issue = True
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(issue_host(identity, broker).issue(
            canonical_session_id="session.original.1", device_id="device.1"
        ))
    assert exc.value.code == "enrollment_consent_changed_during_issue"
    assert [x[0] for x in broker.calls] == ["issue"]  # challenge is left unbound and unusable
    assert [x[0] for x in identity.calls] == ["consent", "consent"]


def test_redeem_does_not_consume_challenge_without_protected_handoff_ready():
    identity, broker, handoff = Identity(), Broker(), Handoff(ready=False)
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"], device_id="device.1",
            proof_ref="pairing-proof:"+"a"*64,
        ))
    assert exc.value.code == "credential_handoff_unavailable"
    assert [x[0] for x in broker.calls] == ["binding"]
    assert [x[0] for x in handoff.calls] == ["ready"]


def test_broker_rejects_wrong_pairing_proof_before_gateway_ready_or_redeem():
    identity, broker, handoff = Identity(), Broker(), Handoff()
    broker.reject_bootstrap = True
    with pytest.raises(IdentityBridgeError) as error:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"], device_id="device.1",
            proof_ref="pairing-proof:" + "b" * 64,
        ))
    assert error.value.code == "invalid_pairing_proof"
    assert [x[0] for x in broker.calls] == ["binding", "preflight"]
    assert handoff.calls == []  # no gateway reservation

def test_success_rechecks_current_consent_and_never_returns_raw_credential():
    identity, broker, handoff = Identity(), Broker(), Handoff()
    result = asyncio.run(issue_host(identity, broker, handoff).redeem(
        challenge_id=CHALLENGE["challenge_id"], device_id="device.1",
        proof_ref="pairing-proof:"+"a"*64,
    ))
    assert [x[0] for x in identity.calls] == ["authorize", "authorize", "authorize"]
    assert [x[0] for x in broker.calls] == ["binding", "preflight", "redeem"]
    assert [x[0] for x in handoff.calls] == ["ready", "deliver", "verify"]
    assert result["lifecycle"] == "paired_offline"
    assert result["consent_id"] == CONSENT["consent_id"]
    assert result["raw_device_credential"] is False
    assert result["credential_installed_by_canonical_handoff"] is True
    assert "credential" not in result and b"one-time-secret" not in repr(result).encode()


def test_consent_withdrawal_between_broker_redemption_and_handoff_revokes_binding():
    identity, broker, handoff = Identity(), Broker(), Handoff()
    identity.fail_reauthorization = True
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"], device_id="device.1",
            proof_ref="pairing-proof:"+"a"*64,
        ))
    assert exc.value.code == "enrollment_consent_changed_during_redeem"
    assert [x[0] for x in broker.calls] == ["binding", "preflight", "redeem", "revoke"]
    assert [x[0] for x in handoff.calls] == ["ready"]


def test_failed_handoff_revokes_canonical_binding_before_reporting_failure():
    identity, broker, handoff = Identity(), Broker(), Handoff(delivered=False)
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"], device_id="device.1",
            proof_ref="pairing-proof:"+"a"*64,
        ))
    assert exc.value.code == "enrollment_credential_handoff_failed"
    assert broker.calls[-1] == ("revoke", "pairing-binding.1")


def test_failed_handoff_and_failed_revoke_is_a_distinct_security_blocker():
    identity, broker, handoff = Identity(), Broker(), Handoff(delivered=False)
    broker.fail_revoke = True
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"], device_id="device.1",
            proof_ref="pairing-proof:"+"a"*64,
        ))
    assert exc.value.code == "enrollment_handoff_revoke_unconfirmed"


def test_server_binding_device_must_match_connectors_requested_device():
    identity, broker, handoff = Identity(), Broker(), Handoff()
    broker.get_enrollment_binding = async_mismatch
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"], device_id="device.other",
            proof_ref="pairing-proof:"+"a"*64,
        ))
    assert exc.value.code == "enrollment_device_swap_denied"


async def async_mismatch(*, challenge_id):
    return {**BINDING, "device_id": "device.1"}


def test_server_never_treats_untrusted_channel_bool_as_windows_installation():
    identity, broker, handoff = Identity(), Broker(), Handoff(delivered=False)
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"], device_id="device.1",
            proof_ref="pairing-proof:"+"a"*64,
        ))
    assert exc.value.code == "enrollment_credential_handoff_failed"
    assert [x[0] for x in handoff.calls] == ["ready", "deliver"]
    assert broker.calls[-1] == ("revoke", "pairing-binding.1")


def test_server_refuses_proof_from_untrusted_gateway_and_revokes_binding():
    identity, broker, handoff = Identity(), Broker(), Handoff(authenticated=False)
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"], device_id="device.1",
            proof_ref="pairing-proof:"+"a"*64,
        ))
    assert exc.value.code == "enrollment_credential_handoff_failed"
    assert [x[0] for x in handoff.calls] == ["ready", "deliver", "verify"]
    assert broker.calls[-1] == ("revoke", "pairing-binding.1")


@pytest.mark.parametrize("tamper", [
    {"challenge_id": "pairing.another"},
    {"device_id": "device.other"},
    {"binding_ref": "pairing-binding.other"},
    {"credential_generation": 2},
    {"proof_hex": "f" * 64},
])
def test_mismatched_or_forged_install_ack_revokes_without_reporting_paired(tamper):
    identity, broker, handoff = Identity(), Broker(), Handoff(tamper=tamper)
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"], device_id="device.1",
            proof_ref="pairing-proof:"+"a"*64,
        ))
    assert exc.value.code == "enrollment_credential_handoff_failed"
    assert broker.calls[-1] == ("revoke", "pairing-binding.1")


def test_missing_authenticated_ack_verifier_blocks_before_challenge_consumption():
    handoff = Handoff()
    handoff.verify_authenticated_ack = None
    identity, broker = Identity(), Broker()
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"], device_id="device.1",
            proof_ref="pairing-proof:"+"a"*64,
        ))
    assert exc.value.code == "credential_handoff_unavailable"
    assert [x[0] for x in broker.calls] == []


def test_consent_loss_after_authenticated_store_ack_revokes_canonical_binding():
    identity, broker, handoff = Identity(), Broker(), Handoff()
    identity.withdraw_after_install = True
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"], device_id="device.1",
            proof_ref="pairing-proof:"+"a"*64,
        ))
    assert exc.value.code == "enrollment_consent_changed_during_redeem"
    assert identity.authorization_count == 3
    assert [x[0] for x in handoff.calls] == ["ready", "deliver", "verify"]
    assert broker.calls[-1] == ("revoke", "pairing-binding.1")


def test_unconfirmed_revoke_after_completed_install_remains_security_hold():
    identity, broker, handoff = Identity(), Broker(), Handoff()
    identity.withdraw_after_install = True
    broker.fail_revoke = True
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"], device_id="device.1",
            proof_ref="pairing-proof:"+"a"*64,
        ))
    assert exc.value.code == "enrollment_consent_race_revoke_unconfirmed"
    assert broker.calls[-1] == ("revoke", "pairing-binding.1")


@pytest.mark.parametrize(("revoke_receipt", "label"), [
    (None, "missing_receipt"),
    (True, "boolean_transport_ack"),
    ({}, "empty_object"),
    ({"binding_ref": "pairing-binding.1"}, "missing_state"),
    ({"binding_ref": "pairing-binding.other", "state": "revoked"}, "wrong_binding"),
    ({"binding_ref": "pairing-binding.1", "state": "active"}, "not_revoked"),
    (
        {"binding_ref": "pairing-binding.1", "state": "revoked", "credential_b64": "forbidden"},
        "unreviewed_extra_field",
    ),
])
@pytest.mark.parametrize("failure_phase", [
    "consent_before_install", "handoff", "consent_after_install",
])
def test_ambiguous_broker_revoke_receipts_are_security_hold_on_every_failure_phase(
    revoke_receipt, label, failure_phase,
):
    """No exception is NOT a canonical Broker revoke confirmation.

    Broker redemption is already consumed. Even a truthy/foreign/malformed
    revoke receipt cannot make the server report a safe compensated failure,
    unlock a repeat of this challenge, or claim paired/online state.
    """
    identity, broker, handoff = Identity(), Broker(), Handoff()
    if failure_phase == "consent_before_install":
        identity.fail_reauthorization = True
    elif failure_phase == "handoff":
        handoff.delivered = False
    else:
        identity.withdraw_after_install = True

    async def forged_revoke(*, binding_ref):
        broker.calls.append(("revoke", binding_ref))
        return revoke_receipt

    broker.revoke_binding = forged_revoke
    with pytest.raises(IdentityBridgeError) as caught:
        asyncio.run(issue_host(identity, broker, handoff).redeem(
            challenge_id=CHALLENGE["challenge_id"],
            device_id="device.1",
            proof_ref="pairing-proof:" + "a" * 64,
        ))

    expected = (
        "enrollment_handoff_revoke_unconfirmed"
        if failure_phase == "handoff"
        else "enrollment_consent_race_revoke_unconfirmed"
    )
    assert caught.value.code == expected, label
    assert [name for name, *_ in broker.calls].count("redeem") == 1
    assert [name for name, *_ in broker.calls].count("revoke") == 1
    assert broker.calls[-1] == ("revoke", "pairing-binding.1")
    assert [name for name, *_ in handoff.calls].count("deliver") == (
        0 if failure_phase == "consent_before_install" else 1
    )
    assert "credential" not in caught.value.code
