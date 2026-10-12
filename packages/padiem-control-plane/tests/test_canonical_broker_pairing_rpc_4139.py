"""Private Broker Durable Object S1 RPC contract, using the same SQLite state."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import sqlite3
from types import SimpleNamespace

import pytest

from canonical_broker_pairing_rpc import CanonicalBrokerPairingRPC
from local_agent_broker_sql_state import CloudflareDurableObjectSerializedStateBackend
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state_wire import SerializedLocalAgentBrokerStatePort
from padiem_control_plane.local_agent_broker_pairing import pairing_proof_ref

NOW = datetime.now(timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.rpc.test.v1"
ACCOUNT = "account.owner.1"
WORKSPACE = "workspace.owner.1"
OWNER = "subject.owner.1"
CONSENT = "consent.owner.1"
DEVICE = "device.office.1"


class Cursor:
    def __init__(self, cur):
        self.cur = cur
        self.rowsWritten = max(0, cur.rowcount)
    def toArray(self):
        if self.cur.description is None:
            return []
        keys = [x[0] for x in self.cur.description]
        return [dict(zip(keys, row, strict=True)) for row in self.cur.fetchall()]


class Sql:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
    def exec(self, sql, *args):
        return Cursor(self.db.execute(sql, args))


class Storage:
    def __init__(self):
        self.sql = Sql()
    def transactionSync(self, fn):
        self.sql.db.execute("BEGIN IMMEDIATE")
        try:
            result = fn()
            self.sql.db.execute("COMMIT")
            return result
        except Exception:
            self.sql.db.execute("ROLLBACK")
            raise


class Harness(CanonicalBrokerPairingRPC):
    def __init__(self, *, limit=4, rpc=True, schema_installed=False, migration=True):
        self._storage = Storage()
        self._backend = CloudflareDurableObjectSerializedStateBackend(self._storage)
        self._port = SerializedLocalAgentBrokerStatePort(backend=self._backend)
        self._runtime = SimpleNamespace(state_port=self._port)
        self.env = SimpleNamespace(
            LOCAL_AGENT_BROKER_PAIRING_RPC_ENABLED="true" if rpc else "false",
            LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALLED="true" if schema_installed else "false",
            LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALL_ENABLED="true" if migration else "false",
            LOCAL_AGENT_BROKER_PAIRING_ISSUANCE_RATE_LIMIT=str(limit),
            LOCAL_AGENT_BROKER_PEPPER="b"*32,
            LOCAL_AGENT_BROKER_AUTHORITY_REF=AUTHORITY_REF,
        )

    def install(self):
        return asyncio.run(self.install_pairing_schema({"migration_id":"canonical-broker-pairing-v1"}))

    def issue(self, device=DEVICE):
        return asyncio.run(self.issue_enrollment_challenge({
            "account_ref": ACCOUNT, "workspace_ref": WORKSPACE, "consent_ref": CONSENT,
            "owner_ref": OWNER, "device_id": device,
        }))

    def binding(self, challenge_id):
        return asyncio.run(self.get_enrollment_binding({"challenge_id":challenge_id}))

    def redeem(self, challenge_id, device, proof, *, consent=CONSENT):
        return asyncio.run(self.redeem_enrollment({
            "challenge_id": challenge_id, "device_id": device, "proof_ref": proof,
            "consent_ref": consent, "owner_ref": OWNER,
            "account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
        }))


def test_pairing_hmac_is_domain_separated_from_canonical_broker_authenticator():
    h = Harness()
    h.install()
    h.env.LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALLED = "true"
    pairing = h._durable_pairing()
    raw_broker_secret = h.env.LOCAL_AGENT_BROKER_PEPPER.encode("utf-8")
    assert pairing._pepper != raw_broker_secret
    assert len(pairing._pepper) == 32
    assert pairing._broker.authority_ref() == AUTHORITY_REF


def test_schema_and_pairing_rpc_are_separately_gated_off_by_default():
    h = Harness(rpc=False, migration=False)
    assert h.install()["ok"] is False
    # Even with a caller-crafted exact payload, issue remains off.
    assert h.issue()["ok"] is False
    assert h._storage.sql.exec(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='canonical_local_agent_pairing_challenge'"
    ).toArray() == []


def test_install_issue_reconstruct_binding_and_redeem_using_persisted_challenge():
    h = Harness()
    installed = h.install()
    assert installed == {"ok": True, "schema": "canonical-broker-pairing-v1", "installed_by_default": False}
    h.env.LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALLED = "true"

    issued = h.issue()
    assert issued["ok"] is True
    challenge_id = issued["challenge"]["challenge_id"]
    code = issued["pairing_code"]
    assert code and len(code) == 32

    # A new RPC object using the SAME canonical SQLite DO recovers the challenge
    # and uses the same state backend, simulating another request or warm restart.
    again = Harness()
    again._storage = h._storage
    again._backend = CloudflareDurableObjectSerializedStateBackend(again._storage)
    again._port = SerializedLocalAgentBrokerStatePort(backend=again._backend)
    again._runtime = SimpleNamespace(state_port=again._port)
    again.env = h.env
    binding = again.binding(challenge_id)
    assert binding["ok"] is True
    assert binding["binding"]["consent_ref"] == CONSENT
    assert binding["binding"]["device_id"] == DEVICE

    proof = pairing_proof_ref(challenge_id=challenge_id, device_id=DEVICE, pairing_code=code)
    redeemed = again.redeem(challenge_id, DEVICE, proof)
    assert redeemed["ok"] is True
    assert redeemed["enrollment"]["device_id"] == DEVICE
    assert redeemed["credential_returned_once"] is True
    assert redeemed["credential_b64"]
    assert redeemed["public_http_route"] is False

    replay = h.redeem(challenge_id, DEVICE, proof)
    assert replay["ok"] is False
    assert replay["error"]["code"] == "pairing_challenge_already_redeemed"


def test_generic_or_wrong_consent_route_cannot_consume_durable_enrollment():
    h = Harness()
    h.install()
    h.env.LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALLED = "true"
    issued = h.issue()
    challenge_id, code = issued["challenge"]["challenge_id"], issued["pairing_code"]
    proof = pairing_proof_ref(challenge_id=challenge_id, device_id=DEVICE, pairing_code=code)
    wrong = h.redeem(challenge_id, DEVICE, proof, consent="consent.other")
    assert wrong["ok"] is False
    assert wrong["error"]["code"] == "enrollment_consent_swap_denied"
    binding = h.binding(challenge_id)
    assert binding["ok"] is True
    good = h.redeem(challenge_id, DEVICE, proof)
    assert good["ok"] is True


def test_issuance_rate_limit_is_enforced_by_private_durable_rpc():
    h = Harness(limit=1)
    h.install()
    h.env.LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALLED = "true"
    assert h.issue(DEVICE)["ok"] is True
    # The next request gets a fresh RPC wrapper but the same DO storage and
    # therefore cannot reset the account/workspace issuance budget.
    h2 = Harness(limit=1)
    h2._storage = h._storage
    h2._backend = CloudflareDurableObjectSerializedStateBackend(h2._storage)
    h2._port = SerializedLocalAgentBrokerStatePort(backend=h2._backend)
    h2._runtime = SimpleNamespace(state_port=h2._port)
    h2.env = h.env
    response = h2.issue("device.office.2")
    assert response["ok"] is False
    assert response["error"]["code"] == "pairing_issuance_rate_limited"


@pytest.mark.parametrize("payload", [
    {"challenge_id":"pairing.a","device_id":DEVICE},
    {"challenge_id":"pairing.a","owner_ref":OWNER},
])
def test_private_binding_rpc_rejects_unreviewed_fields(payload):
    h = Harness()
    h.install()
    h.env.LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALLED = "true"
    assert asyncio.run(h.get_enrollment_binding(payload))["ok"] is False
