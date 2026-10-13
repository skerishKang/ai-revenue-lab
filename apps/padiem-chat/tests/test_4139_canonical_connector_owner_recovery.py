"""#4139 OWNER recovery tests: no network, real Worker, or device enrollment."""
from __future__ import annotations

import asyncio
import hashlib
import pytest

from app.canonical_connector_owner_recovery import (
    CanonicalConnectorOwnerRecovery,
    OWNER_RECOVERY_ROUTE_MOUNTED,
    OWNER_RECOVERY_PRODUCTION_ENABLED,
)
from app.control_plane_identity import IdentityBridgeError
from app.control_plane_broker_pairing_client import CloudflareCanonicalBrokerPairingClient

SESSION = "session.test"
CID = "pairing." + "a" * 32
DEVICE = "device.1"
OWNER = "sub_" + "b" * 32
CONSENT = "consent.1"
ACCOUNT = "account.1"
WORKSPACE = "workspace.1"
REF = "pairing-binding." + hashlib.sha256(f"{CID}:{DEVICE}".encode()).hexdigest()[:32]


class Identity:
    def __init__(self):
        self.calls = 0
        self.granted = True
        self.owner = OWNER
    async def resolve_connector_enrollment_consent_for_device(self, *, session_id, device_id):
        self.calls += 1
        if session_id != SESSION or device_id != DEVICE:
            raise IdentityBridgeError(401, "not_authenticated", "invalid")
        return {
            "device_id": device_id, "consent_id": CONSENT,
            "owner_subject_id": self.owner, "account_ref": ACCOUNT,
            "workspace_ref": WORKSPACE, "granted_at": "2026-10-13T00:00:00Z",
            "withdrawn_at": None if self.granted else "2026-10-13T01:00:00Z",
        }


class Broker:
    def __init__(self, state="revoked"):
        self.calls = []
        self.state = state
        self.available = True
        self.owner_ref = OWNER
        self.binding_ref = REF
        self.raw = False
        self.consumed = True
        self.generation = 1
    async def get_enrollment_binding(self, *, challenge_id):
        self.calls.append("original")
        return {"challenge_id": challenge_id, "consent_ref": CONSENT,
                "owner_ref": self.owner_ref, "account_ref": ACCOUNT,
                "workspace_ref": WORKSPACE, "device_id": DEVICE}
    async def recovery_verdict(self, **kwargs):
        self.calls.append("recovery")
        assert kwargs == {
            "challenge_id": CID, "device_id": DEVICE,
            "consent_ref": CONSENT, "owner_ref": OWNER,
            "account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
            "binding_ref": REF, "credential_generation": 1,
        }
        confirmed = self.consumed and self.state == "revoked" and self.generation == 1
        return {
            "challenge_id": CID, "device_id": DEVICE, "binding_ref": REF,
            "credential_generation": 1, "disposition": "revoked" if confirmed else "security_hold",
            "canonical_revocation_confirmed": confirmed,
            "can_retry_challenge": False, "raw_device_credential": False,
        }
    async def owner_device_directory(self, *, account_ref, workspace_ref):
        assert (account_ref, workspace_ref) == (ACCOUNT, WORKSPACE)
        self.calls.append("directory")
        if not self.available:
            return {"available": False, "devices": []}
        return {"available": True, "devices": [{
            "canonical_state": self.state, "binding": {
                "binding_ref": self.binding_ref, "device_id": DEVICE,
                "account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
                "credential_generation": 1, "issued_at": "2026-10-13T00:00:00Z",
                "credential_expires_at": "2026-10-14T00:00:00Z",
                "credential_digest_exposed": False,
                "raw_device_credential": self.raw,
            }, "session": None, "heartbeat_last_seen_at": None,
        }]}


def check(identity=None, broker=None, *, session=SESSION, challenge=CID, device=DEVICE):
    a, b = identity or Identity(), broker or Broker()
    result = asyncio.run(CanonicalConnectorOwnerRecovery(
        identity=a, broker=b,
    ).check(canonical_session_id=session, challenge_id=challenge, device_id=device))
    return result, a, b


def test_no_route_or_production_activation_and_canonical_confirmed_revoke_only():
    assert OWNER_RECOVERY_ROUTE_MOUNTED is False
    assert OWNER_RECOVERY_PRODUCTION_ENABLED is False
    result, i, b = check()
    assert result == {
        "challenge_id": CID, "device_id": DEVICE,
        "disposition": "revoked", "canonical_revocation_confirmed": True,
        "can_retry_challenge": False, "raw_device_credential": False,
        "dispatch_authorized": False,
    }
    assert i.calls == 1 and b.calls == ["original", "directory", "recovery"]


@pytest.mark.parametrize("state", ["paired_offline", "credential_expired"])
def test_an_active_or_expired_binding_is_never_accepted_as_revoked(state):
    result, _, b = check(broker=Broker(state))
    assert result["disposition"] == "security_hold"
    assert result["canonical_revocation_confirmed"] is False
    assert result["can_retry_challenge"] is False
    assert b.calls == ["original", "directory"]


def test_missing_or_other_historical_binding_is_a_hold_not_a_revoke():
    for variant in ["absent", "wrong_ref"]:
        b = Broker()
        if variant == "absent":
            b.available = False
        else:
            b.binding_ref = "pairing-binding." + "f" * 32
        result, _, _ = check(broker=b)
        assert result["disposition"] == "security_hold"


def test_unsigned_or_wrong_owner_session_blocks_any_broker_read():
    for wrong_session in ("session.other", "unauthorized"):
        b = Broker()
        with pytest.raises(IdentityBridgeError):
            check(broker=b, session=wrong_session)
        assert b.calls == []


def test_withdrawn_original_consent_does_not_allow_owner_recovery():
    i, b = Identity(), Broker()
    i.granted = False
    with pytest.raises(IdentityBridgeError):
        check(identity=i, broker=b)
    assert b.calls == []


def test_new_owner_cannot_read_old_challenge_or_hijack_revoke_verdict():
    i, b = Identity(), Broker()
    i.owner = "sub_" + "f" * 32
    with pytest.raises(IdentityBridgeError) as e:
        check(identity=i, broker=b)
    assert e.value.code == "recovery_scope_mismatch"
    assert b.calls == ["original"]


@pytest.mark.parametrize("state", ["online", "unknown", True, None])
def test_broker_cannot_invent_online_or_unreviewed_state(state):
    b = Broker()
    b.state = state
    with pytest.raises(IdentityBridgeError):
        check(broker=b)


def test_malformed_directory_secret_leak_is_fail_closed():
    b = Broker()
    b.raw = True
    with pytest.raises(IdentityBridgeError):
        check(broker=b)


def test_owner_directory_is_existing_private_service_binding_only():
    class RealBinding:
        def __init__(self):
            self.calls = []
        async def device_directory(self, payload):
            self.calls.append(payload)
            return {"ok": True, "available": False, "reason": "no_device_binding"}
    port = RealBinding()
    client = CloudflareCanonicalBrokerPairingClient(port)
    result = asyncio.run(client.owner_device_directory(
        account_ref=ACCOUNT, workspace_ref=WORKSPACE,
    ))
    assert result == {"available": False, "devices": []}
    assert port.calls == [{"account_ref": ACCOUNT, "workspace_ref": WORKSPACE}]
    assert not hasattr(client, "recovery_redeem")


def test_fake_scoped_directory_with_unexpected_data_rejected():
    class Binding:
        async def device_directory(self, payload):
            return {"ok": True, "available": True, "owner_scoped": True,
                    "device_count": 1, "max_devices": 25, "devices": [],
                    "credential_b64": "wrong"}
    client = CloudflareCanonicalBrokerPairingClient(Binding())
    with pytest.raises(IdentityBridgeError):
        asyncio.run(client.owner_device_directory(
            account_ref=ACCOUNT, workspace_ref=WORKSPACE,
        ))


def test_revoked_directory_without_consumed_challenge_never_confirms():
    b = Broker()
    b.consumed = False
    result, _, _ = check(broker=b)
    assert result["disposition"] == "security_hold"
    assert b.calls == ["original", "directory", "recovery"]


def test_broker_generation_rotation_cannot_prove_original_revoke():
    b = Broker()
    b.generation = 2
    result, _, _ = check(broker=b)
    assert result["disposition"] == "security_hold"


def test_recovery_rpc_timeout_retains_unconfirmed_state():
    class Timeout(Broker):
        async def recovery_verdict(self, **kwargs):
            raise TimeoutError("Broker unavailable")
    with pytest.raises(TimeoutError):
        check(broker=Timeout())


def test_fake_broker_recovery_claims_are_rejected():
    class Bogus(Broker):
        async def recovery_verdict(self, **kwargs):
            return {"disposition": "revoked", "canonical_revocation_confirmed": True}
    with pytest.raises(IdentityBridgeError) as exc:
        check(broker=Bogus())
    assert exc.value.code == "recovery_verdict_invalid"
