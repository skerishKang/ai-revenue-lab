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
        "SELECT challenge_id,code_nonce,consent_ref,owner_ref,device_id FROM canonical_local_agent_pairing_challenge"
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
