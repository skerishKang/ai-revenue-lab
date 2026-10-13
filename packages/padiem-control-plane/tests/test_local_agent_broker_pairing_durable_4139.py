"""#4139 durable pairing challenge contract against existing Broker DO SQLite."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from local_agent_broker_pairing_durable import (
    PAIRING_PUBLIC_ROUTE_CONFIGURED,
    PAIRING_PRODUCTION_ACTIVATED,
    PAIRING_SCHEMA_INSTALLED_BY_DEFAULT,
    DurableBrokerPairingAuthority,
)
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import (
    BrokerBindingState,
    InMemoryLocalAgentBrokerAuthority,
)
from padiem_control_plane.local_agent_broker_pairing import pairing_proof_ref
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state_wire import SerializedLocalAgentBrokerStatePort
from local_agent_broker_sql_state import CloudflareDurableObjectSerializedStateBackend
from canonical_broker_gateway_bootstrap import (
    DurableBrokerGatewayBootstrap,
    install_gateway_bootstrap_schema,
    bootstrap_mac,
    session_mac,
    BOOTSTRAP_PRODUCTION_ENABLED,
    BOOTSTRAP_HTTP_ROUTE_MOUNTED,
)

NOW = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.test.v1"
ACCOUNT = "account.owner.1"
WORKSPACE = "workspace.owner.1"
DEVICE = "device.office.1"
OWNER = "subject.owner.1"
CONSENT = "consent.owner.1"


class Cursor:
    def __init__(self, cur):
        self._cur = cur
        self.rowsWritten = max(0, cur.rowcount)
    def toArray(self):
        if self._cur.description is None:
            return []
        names = [col[0] for col in self._cur.description]
        return [dict(zip(names, row, strict=True)) for row in self._cur.fetchall()]


class Sql:
    def __init__(self, db):
        self.db = db
    def exec(self, statement, *args):
        return Cursor(self.db.execute(statement, args))


class Storage:
    def __init__(self):
        self.sql = Sql(sqlite3.connect(":memory:", isolation_level=None))
    def transactionSync(self, operation):
        self.sql.db.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
            self.sql.db.execute("COMMIT")
            return result
        except Exception:
            self.sql.db.execute("ROLLBACK")
            raise


class Harness:
    def __init__(self, *, storage=None, limit=4, migration=True):
        self.storage = storage or Storage()
        # The canonical Broker state uses the same SQLite DO storage.
        backend = CloudflareDurableObjectSerializedStateBackend(self.storage)
        port = SerializedLocalAgentBrokerStatePort(backend=backend)
        self.broker = StateBackedLocalAgentBrokerAuthority(
            pepper=b"b" * 32, authority_ref=AUTHORITY_REF, state_port=port,
        )
        self.pairing = DurableBrokerPairingAuthority(
            storage=self.storage, broker=self.broker, pepper=b"p" * 32,
            issuance_rate_limit=limit, schema_migration_enabled=migration,
        )


def active_bindings(h):
    stored = h.broker._state_port.load(authority_ref=AUTHORITY_REF)
    return [x for x in stored.snapshot.bindings if x.state is BrokerBindingState.ACTIVE]


def install(h):
    h.pairing.install_schema(migration_id="canonical-broker-pairing-v1")


def issue(h, *, device=DEVICE, ttl=300):
    return h.pairing.issue_enrollment_challenge(
        account_ref=ACCOUNT, workspace_ref=WORKSPACE,
        consent_ref=CONSENT, owner_ref=OWNER, device_id=device,
        now=NOW, ttl_seconds=ttl,
    )


def proof(challenge, code, *, device=DEVICE):
    return pairing_proof_ref(
        challenge_id=challenge.challenge_id, device_id=device, pairing_code=code
    )


def test_pairing_schema_is_explicit_and_not_auto_installed():
    h = Harness(migration=False)
    with pytest.raises(ControlPlaneContractError) as exc:
        h.pairing.install_schema(migration_id="canonical-broker-pairing-v1")
    assert exc.value.code == "durable_pairing_schema_install_disabled"
    with pytest.raises(Exception):
        h.pairing.issue_challenge(account_ref=ACCOUNT, workspace_ref=WORKSPACE, now=NOW)
    assert PAIRING_SCHEMA_INSTALLED_BY_DEFAULT is False
    assert PAIRING_PUBLIC_ROUTE_CONFIGURED is False
    assert PAIRING_PRODUCTION_ACTIVATED is False


def test_challenge_and_one_time_code_work_after_reconstructing_adapter_and_broker():
    h = Harness()
    install(h)
    challenge, code = issue(h)
    persisted = h.storage.sql.exec(
        "SELECT challenge_id,code_nonce,consent_ref,owner_ref,enrollment_device_id AS device_id FROM canonical_local_agent_pairing_challenge"
    ).toArray()
    assert len(persisted) == 1
    assert persisted[0]["challenge_id"] == challenge.challenge_id
    assert persisted[0]["code_nonce"] not in code
    assert persisted[0]["consent_ref"] == CONSENT
    assert persisted[0]["device_id"] == DEVICE

    # Simulate another request / fresh object wrapper on the same DO storage.
    reopened = Harness(storage=h.storage)
    correct_proof = proof(challenge, code)
    enrollment, raw_credential = reopened.pairing.redeem_enrollment(
        challenge_id=challenge.challenge_id, device_id=DEVICE,
        proof_ref=correct_proof, consent_ref=CONSENT, owner_ref=OWNER,
        account_ref=ACCOUNT, workspace_ref=WORKSPACE, now=NOW+timedelta(seconds=1),
    )
    assert enrollment.device_id == DEVICE
    assert raw_credential and isinstance(raw_credential, bytes)
    assert len(active_bindings(reopened)) == 1
    record = reopened.storage.sql.exec(
        "SELECT redeemed_at,redeemed_device_id,redeemed_binding_ref FROM canonical_local_agent_pairing_challenge WHERE challenge_id=?",
        challenge.challenge_id,
    ).toArray()[0]
    assert record["redeemed_at"] is not None
    assert record["redeemed_device_id"] == DEVICE
    assert record["redeemed_binding_ref"] == enrollment.binding_ref
    # The raw credential must not be persisted in either challenge rows or the
    # serialized canonical Broker state; the latter stores only a digest.
    payload = reopened.storage.sql.exec("SELECT payload_text FROM local_agent_broker_state").toArray()[0]["payload_text"]
    assert raw_credential.hex() not in payload
    assert raw_credential.decode("latin1") not in payload


def test_generic_redeem_cannot_bypass_persistent_enrollment_binding():
    h = Harness()
    install(h)
    challenge, code = issue(h)
    valid = proof(challenge, code)
    with pytest.raises(ControlPlaneContractError) as exc:
        h.pairing.redeem(
            challenge_id=challenge.challenge_id, device_id=DEVICE,
            proof_ref=valid, now=NOW+timedelta(seconds=1),
        )
    assert exc.value.code == "enrollment_bound_challenge_requires_scoped_redemption"
    assert not active_bindings(h)
    rows = h.storage.sql.exec(
        "SELECT redeemed_at FROM canonical_local_agent_pairing_challenge WHERE challenge_id=?",
        challenge.challenge_id,
    ).toArray()
    assert rows[0]["redeemed_at"] is None
    assert h.pairing.redeem_enrollment(
        challenge_id=challenge.challenge_id, device_id=DEVICE, proof_ref=valid,
        consent_ref=CONSENT, owner_ref=OWNER, account_ref=ACCOUNT,
        workspace_ref=WORKSPACE, now=NOW+timedelta(seconds=2),
    )[0].device_id == DEVICE


def test_wrong_proof_and_wrong_scope_do_not_consume_or_create_binding():
    h = Harness()
    install(h)
    challenge, code = issue(h)
    with pytest.raises(ControlPlaneContractError) as wrong_scope:
        h.pairing.redeem_enrollment(
            challenge_id=challenge.challenge_id, device_id=DEVICE,
            proof_ref=proof(challenge, code), consent_ref="consent.other",
            owner_ref=OWNER, account_ref=ACCOUNT, workspace_ref=WORKSPACE,
            now=NOW+timedelta(seconds=1),
        )
    assert wrong_scope.value.code == "enrollment_consent_swap_denied"
    assert not active_bindings(h)
    with pytest.raises(ControlPlaneContractError) as wrong_proof:
        h.pairing.redeem_enrollment(
            challenge_id=challenge.challenge_id, device_id=DEVICE,
            proof_ref="pairing-proof:"+"0"*64, consent_ref=CONSENT,
            owner_ref=OWNER, account_ref=ACCOUNT, workspace_ref=WORKSPACE,
            now=NOW+timedelta(seconds=1),
        )
    assert wrong_proof.value.code == "invalid_pairing_proof"
    assert not active_bindings(h)
    pending = h.storage.sql.exec(
        "SELECT redeemed_at FROM canonical_local_agent_pairing_challenge WHERE challenge_id=?",
        challenge.challenge_id,
    ).toArray()[0]
    assert pending["redeemed_at"] is None
    enrolled, credential = h.pairing.redeem_enrollment(
        challenge_id=challenge.challenge_id, device_id=DEVICE,
        proof_ref=proof(challenge, code), consent_ref=CONSENT, owner_ref=OWNER,
        account_ref=ACCOUNT, workspace_ref=WORKSPACE, now=NOW+timedelta(seconds=2),
    )
    assert enrolled.device_id == DEVICE and credential
    assert len(active_bindings(h)) == 1


def test_replay_remains_denied_after_reopening_adapter():
    h = Harness()
    install(h)
    challenge, code = issue(h)
    proof_ref = proof(challenge, code)
    h.pairing.redeem_enrollment(
        challenge_id=challenge.challenge_id, device_id=DEVICE, proof_ref=proof_ref,
        consent_ref=CONSENT, owner_ref=OWNER, account_ref=ACCOUNT,
        workspace_ref=WORKSPACE, now=NOW+timedelta(seconds=1),
    )
    reopened = Harness(storage=h.storage)
    with pytest.raises(ControlPlaneContractError) as exc:
        reopened.pairing.redeem_enrollment(
            challenge_id=challenge.challenge_id, device_id=DEVICE,
            proof_ref=proof_ref, consent_ref=CONSENT, owner_ref=OWNER,
            account_ref=ACCOUNT, workspace_ref=WORKSPACE, now=NOW+timedelta(seconds=2),
        )
    assert exc.value.code == "pairing_challenge_already_redeemed"
    assert len(active_bindings(reopened)) == 1


def test_issuance_rate_limit_survives_reopening():
    h = Harness(limit=1)
    install(h)
    issue(h, device=DEVICE)
    reopened = Harness(storage=h.storage, limit=1)
    with pytest.raises(ControlPlaneContractError) as exc:
        issue(reopened, device="device.office.2")
    assert exc.value.code == "pairing_issuance_rate_limited"


def test_duplicate_active_binding_from_one_device_is_not_minted_by_replay():
    h = Harness()
    install(h)
    challenge, code = issue(h)
    h.pairing.redeem_enrollment(
        challenge_id=challenge.challenge_id, device_id=DEVICE,
        proof_ref=proof(challenge, code), consent_ref=CONSENT, owner_ref=OWNER,
        account_ref=ACCOUNT, workspace_ref=WORKSPACE, now=NOW+timedelta(seconds=1),
    )
    with pytest.raises(ControlPlaneContractError) as exc:
        h.pairing.redeem_enrollment(
            challenge_id=challenge.challenge_id, device_id=DEVICE,
            proof_ref=proof(challenge, code), consent_ref=CONSENT, owner_ref=OWNER,
            account_ref=ACCOUNT, workspace_ref=WORKSPACE, now=NOW+timedelta(seconds=2),
        )
    assert exc.value.code == "pairing_challenge_already_redeemed"
    assert len(active_bindings(h)) == 1


def test_nonconsuming_bootstrap_proof_is_read_only_across_durable_adapter_reopen():
    h = Harness()
    install(h)
    challenge, code = issue(h)
    verified_proof = proof(challenge, code)
    reopened = Harness(storage=h.storage)
    kwargs = {
        "challenge_id": challenge.challenge_id, "device_id": DEVICE,
        "proof_ref": verified_proof, "consent_ref": CONSENT,
        "owner_ref": OWNER, "account_ref": ACCOUNT,
        "workspace_ref": WORKSPACE, "now": NOW + timedelta(seconds=1),
    }
    before = h.storage.sql.exec(
        "SELECT * FROM canonical_local_agent_pairing_challenge"
    ).toArray()
    assert reopened.pairing.verify_enrollment_bootstrap(**kwargs) == {
        "challenge_id": challenge.challenge_id,
        "device_id": DEVICE, "proof_valid": True, "challenge_consumed": False,
    }
    after = h.storage.sql.exec(
        "SELECT * FROM canonical_local_agent_pairing_challenge"
    ).toArray()
    assert before == after
    assert active_bindings(h) == []
    for swap, reason in [
        ({"proof_ref": "pairing-proof:" + "f" * 64}, "invalid_pairing_proof"),
        ({"device_id": "device.attacker"}, "enrollment_bootstrap_scope_mismatch"),
        ({"consent_ref": "consent.other"}, "enrollment_bootstrap_scope_mismatch"),
        ({"account_ref": "account.other"}, "enrollment_bootstrap_scope_mismatch"),
        ({"owner_ref": "subject.other"}, "enrollment_bootstrap_scope_mismatch"),
        ({"now": NOW + timedelta(hours=1)}, "pairing_challenge_expired"),
    ]:
        with pytest.raises(ControlPlaneContractError) as error:
            reopened.pairing.verify_enrollment_bootstrap(**{**kwargs, **swap})
        assert error.value.code == reason
    enrollment, key = reopened.pairing.redeem_enrollment(**kwargs)
    assert key and enrollment.binding_ref
    with pytest.raises(ControlPlaneContractError) as error:
        reopened.pairing.verify_enrollment_bootstrap(**kwargs)
    assert error.value.code == "pairing_challenge_already_redeemed"


def gateway_lease(h):
    install_gateway_bootstrap_schema(
        storage=h.storage, migration_id="canonical-broker-gateway-bootstrap-v1",
        operator_gate=True,
    )
    return DurableBrokerGatewayBootstrap(
        storage=h.storage, pairing=h.pairing,
        nonce_factory=lambda: "a" * 64,
        lease_factory=lambda: "gateway." + "b" * 32,
    )


def test_gateway_nonce_is_canonical_broker_do_durable_and_nonconsuming():
    h = Harness()
    install(h)
    challenge, code = issue(h)
    gateway = gateway_lease(h)
    assert BOOTSTRAP_PRODUCTION_ENABLED is False
    assert BOOTSTRAP_HTTP_ROUTE_MOUNTED is False
    # A challenge ID and device ID are public correlation, not permission to
    # reserve the one-use nonce. An invalid proof must create zero SQL rows.
    with pytest.raises(ControlPlaneContractError) as denied:
        gateway.begin(challenge_id=challenge.challenge_id, device_id=DEVICE,
                      proof_ref="pairing-proof:" + "f" * 64, now=NOW)
    assert denied.value.code == "invalid_pairing_proof"
    assert h.storage.sql.exec(
        "SELECT * FROM canonical_local_agent_gateway_bootstrap"
    ).toArray() == []
    started = gateway.begin(
        challenge_id=challenge.challenge_id, device_id=DEVICE,
        proof_ref=proof(challenge, code), now=NOW,
    )
    assert started["nonce_hex"] == "a" * 64
    assert started["lease_ref"] == "gateway." + "b" * 32
    assert started["credential"] is False and started["challenge_consumed"] is False
    assert not active_bindings(h)
    assert len(h.storage.sql.exec(
        "SELECT * FROM canonical_local_agent_gateway_bootstrap"
    ).toArray()) == 1
    with pytest.raises(ControlPlaneContractError):
        gateway.begin(challenge_id=challenge.challenge_id, device_id=DEVICE, proof_ref=proof(challenge, code), now=NOW)
    reopened = Harness(storage=h.storage)
    gateway2 = DurableBrokerGatewayBootstrap(storage=h.storage, pairing=reopened.pairing)
    signed = bootstrap_mac(
        pairing_code=code, challenge_id=challenge.challenge_id, device_id=DEVICE,
        nonce_hex=started["nonce_hex"], lease_ref=started["lease_ref"],
    )
    ok = gateway2.finish(
        challenge_id=challenge.challenge_id, device_id=DEVICE,
        lease_ref=started["lease_ref"], proof_hex=signed, now=NOW + timedelta(seconds=1),
    )
    assert ok["verified"] is True and ok["challenge_consumed"] is False
    assert not active_bindings(h)

    body1 = b'{"intent":"credential_fetch"}'
    kwargs = dict(
        pairing_code=code, challenge_id=challenge.challenge_id, device_id=DEVICE,
        nonce_hex=started["nonce_hex"], lease_ref=started["lease_ref"],
    )
    import hashlib
    def signed_action(action, counter, body):
        return session_mac(**kwargs, action=action, counter=counter,
                           payload_sha256=hashlib.sha256(body).hexdigest())
    # An installation ACK before the canonical Broker actually consumes the
    # challenge must never be accepted just because a gateway MAC is valid.
    premature = b'{"ack":true}'
    with pytest.raises(ControlPlaneContractError) as before_redeem:
        gateway2.authorize_action(
            challenge_id=challenge.challenge_id, device_id=DEVICE,
            lease_ref=started["lease_ref"], action="install_ack", counter=2,
            body=premature, proof_hex=signed_action("install_ack", 2, premature),
            now=NOW + timedelta(seconds=2),
        )
    assert before_redeem.value.code == "gateway_bootstrap_action_refused"
    for step, action, body in [
        (1, "credential_fetch", body1),
        (2, "install_ack", b'{"ack":true}'),
        (3, "revoke_verdict", b'{"request":"status"}'),
    ]:
        if step == 2:
            enrollment, credential = reopened.pairing.redeem_enrollment(
                challenge_id=challenge.challenge_id, device_id=DEVICE,
                proof_ref=proof(challenge, code), consent_ref=CONSENT,
                owner_ref=OWNER, account_ref=ACCOUNT, workspace_ref=WORKSPACE,
                now=NOW + timedelta(seconds=2),
            )
            assert enrollment.device_id == DEVICE and credential
        signed_mac = signed_action(action, step, body)
        x = gateway2.authorize_action(
            challenge_id=challenge.challenge_id, device_id=DEVICE,
            lease_ref=started["lease_ref"], action=action, counter=step,
            body=body, proof_hex=signed_mac, now=NOW + timedelta(seconds=step+1),
        )
        assert x["authenticated"] is True and x["counter"] == step
        with pytest.raises(ControlPlaneContractError):
            gateway2.authorize_action(
                challenge_id=challenge.challenge_id, device_id=DEVICE,
                lease_ref=started["lease_ref"], action=action, counter=step,
                body=body, proof_hex=signed_mac, now=NOW + timedelta(seconds=step+1),
            )
    persisted = h.storage.sql.exec(
        "SELECT next_counter,terminal_action FROM canonical_local_agent_gateway_bootstrap"
    ).toArray()
    assert persisted == [{"next_counter": 4, "terminal_action": "revoke_verdict"}]
    assert len(active_bindings(h)) == 1
    assert h.storage.sql.exec(
        "SELECT redeemed_at FROM canonical_local_agent_pairing_challenge"
    ).toArray()[0]["redeemed_at"] is not None
    assert "credential" not in persisted[0]

def test_gateway_invalid_proof_attempts_are_persisted_across_reopens():
    h = Harness()
    install(h)
    challenge, code = issue(h)
    gateway = gateway_lease(h)
    started = gateway.begin(challenge_id=challenge.challenge_id, device_id=DEVICE, proof_ref=proof(challenge, code), now=NOW)
    invalid = "f" * 64
    for count in range(1, 4):
        reopened = Harness(storage=h.storage)
        checker = DurableBrokerGatewayBootstrap(storage=h.storage, pairing=reopened.pairing)
        with pytest.raises(ControlPlaneContractError) as err:
            checker.finish(
                challenge_id=challenge.challenge_id, device_id=DEVICE,
                lease_ref=started["lease_ref"], proof_hex=invalid,
                now=NOW + timedelta(seconds=count),
            )
        assert err.value.code == "gateway_bootstrap_proof_invalid"
        assert h.storage.sql.exec(
            "SELECT failed_proofs FROM canonical_local_agent_gateway_bootstrap"
        ).toArray()[0]["failed_proofs"] == count
    valid = bootstrap_mac(
        pairing_code=code, challenge_id=challenge.challenge_id, device_id=DEVICE,
        nonce_hex=started["nonce_hex"], lease_ref=started["lease_ref"],
    )
    with pytest.raises(ControlPlaneContractError) as err:
        checker.finish(
            challenge_id=challenge.challenge_id, device_id=DEVICE,
            lease_ref=started["lease_ref"], proof_hex=valid, now=NOW + timedelta(seconds=4),
        )
    assert err.value.code == "gateway_bootstrap_lease_unavailable"


def test_gateway_expiry_cross_device_and_schema_install_refuse_before_auth():
    h = Harness()
    install(h)
    challenge, code = issue(h)
    with pytest.raises(ControlPlaneContractError) as disabled:
        install_gateway_bootstrap_schema(
            storage=h.storage, migration_id="canonical-broker-gateway-bootstrap-v1",
            operator_gate=False,
        )
    assert disabled.value.code == "gateway_bootstrap_schema_disabled"
    gateway = gateway_lease(h)
    for swapped in ["device.attacker", "device.other"]:
        with pytest.raises(ControlPlaneContractError):
            gateway.begin(challenge_id=challenge.challenge_id, device_id=swapped, proof_ref=proof(challenge, code), now=NOW)
    started = gateway.begin(challenge_id=challenge.challenge_id, device_id=DEVICE, proof_ref=proof(challenge, code), now=NOW)
    valid = bootstrap_mac(
        pairing_code=code, challenge_id=challenge.challenge_id, device_id=DEVICE,
        nonce_hex=started["nonce_hex"], lease_ref=started["lease_ref"],
    )
    with pytest.raises(ControlPlaneContractError):
        gateway.finish(
            challenge_id=challenge.challenge_id, device_id=DEVICE,
            lease_ref=started["lease_ref"], proof_hex=valid,
            now=NOW + timedelta(seconds=61),
        )
    with pytest.raises(ControlPlaneContractError):
        gateway.begin(challenge_id=challenge.challenge_id, device_id=DEVICE, proof_ref=proof(challenge, code), now=NOW)
